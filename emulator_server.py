"""Two independent, vendor-neutral WAV/PTT emulators. No physical RF I/O."""
import io
import json
import os
from pathlib import Path
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError

from receiver import MAX_BYTES, decode_wav
from rotation import configured_mapping
from selcal import tones_for, make_wav
from tail_mapping import validate_tail
from wav_context import read as read_context, attach


class Emulator:
    def __init__(self, role, mapping=None, aircraft_url=None, sleep=time.sleep):
        if role not in ('radio', 'aircraft'):
            raise ValueError('role must be radio or aircraft')
        self.role, self.mapping, self.sleep = role, mapping, sleep
        self.aircraft_url = aircraft_url or 'http://127.0.0.1:8790'
        self.lock, self.state_lock = threading.Lock(), threading.RLock()
        self.config = {'tail_number':'5501', 'mode':'selcal16', 'receive_mode':'selcal32'}
        self.state = 'idle'
        self.ptt = False
        self.last = None
        self.events = []

    def snapshot(self):
        return (self.mapping or configured_mapping()).snapshot()

    def event(self, state, ptt=False):
        with self.state_lock:
            self.state, self.ptt = state, ptt
            self.events.append({'state':state, 'ptt':ptt, 'time':time.time()})
            self.events = self.events[-40:]

    def status(self):
        with self.state_lock:
            snap = self.snapshot()
            current = snap.describe(self.config['tail_number'], self.config['mode'])
            last = self.last
            stale = bool(last and (last.get('period_id'), last.get('key_id')) !=
                         (current.get('period_id'), current.get('key_id')))
            return {'role':self.role, 'state':self.state, 'ptt':self.ptt,
                    'physical_output':False, 'config':dict(self.config), 'current':current,
                    'last':last, 'last_stale':stale, 'events':list(self.events)}

    def configure(self, data):
        if not isinstance(data, dict) or set(data) != set(self.config):
            raise ValueError('tail_number, mode, receive_modeを指定してください。')
        validate_tail(data['tail_number'])
        tones_for(data['mode']); tones_for(data['receive_mode'])
        if data['mode'] == 'selcal32' and data['receive_mode'] == 'selcal16':
            raise ValueError('32音コードには32音の受信能力が必要です。')
        with self.state_lock:
            self.config = dict(data)
            self.last = None
        return self.status()

    def check_context(self, payload, snap):
        context = read_context(payload)
        if snap.metadata()['rotation_enabled'] and not context:
            raise ValueError('鍵更新モードではHACSの期間・鍵情報付きWAVが必要です。')
        if context:
            snap.check_expected(context['period_id'], context['key_id'])

    def guard(self, snap):
        meta = snap.metadata()
        self.snapshot().check_expected(meta['period_id'] or '', meta['key_id'] or '')

    def process(self, payload):
        snap = self.snapshot()
        self.check_context(payload, snap)
        if self.role == 'aircraft':
            self.event('decoding')
            try:
                config = dict(self.config)
                code = snap.to_code(config['tail_number'], config['mode'])
                result = decode_wav(payload, code, config['receive_mode'])
                self.guard(snap)
                result.update(snap.metadata())
                result['own_tail_number'] = config['tail_number']
                result['own_mode'] = config['mode']
                with self.state_lock:
                    self.last = result
                return result
            finally:
                self.event('idle')
        # Validate PCM length/format before simulated PTT; calls need not match.
        try:
            with wave.open(io.BytesIO(payload), 'rb') as wav:
                frames, rate = wav.getnframes(), wav.getframerate()
                duration = frames / rate
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 8000 <= rate <= 96000:
                    raise ValueError('モノラル16bit PCM、8〜96kHzが必要です。')
                if not .3 <= duration <= 10 or len(wav.readframes(frames)) != frames * 2:
                    raise ValueError('WAVの長さが不正です（0.3〜10秒）。')
        except (wave.Error, EOFError) as exc:
            raise ValueError('WAVが不正です。') from exc
        with self.state_lock:
            self.last = None
        try:
            self.event('ptt_lead', True)
            self.sleep(.3)
            self.guard(snap)
            self.event('transmitting', True)
            self.sleep(duration)
            self.event('ptt_tail', True)
            self.sleep(.2)
        finally:
            self.event('idle', False)
        # HTTP delivery/decoding follows PTT release, so a failed receiver cannot
        # hold simulated PTT on. This is a buffered link, not real-time RF.
        self.guard(snap)
        self.event('delivering')
        try:
            request = Request(self.aircraft_url.rstrip('/')+'/api/input', payload,
                              {'Content-Type':'audio/wav'}, method='POST')
            with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError('受信応答が大きすぎます。')
                detection = json.loads(body)
            self.guard(snap)
            result = {'status':'delivered', 'aircraft':detection,
                      'duration_seconds':duration, 'physical_output':False, **snap.metadata()}
            with self.state_lock:
                self.last = result
            return result
        except (URLError, OSError, ValueError) as exc:
            with self.state_lock:
                self.last = {'status':'delivery_failed', **snap.metadata()}
            raise ValueError('航空機エミュレータへの転送に失敗しました。接続と鍵・期間を確認してください。') from exc
        finally:
            self.event('idle')


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, mime='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            return self.reply(200, Path(__file__).with_name('emulator.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/emulator_ui.js':
            return self.reply(200, Path(__file__).with_name('emulator_ui.js').read_bytes(), 'text/javascript; charset=utf-8')
        if path == '/api/status':
            try:
                return self.reply(200, self.server.emulator.status())
            except ValueError as exc:
                return self.reply(503, {'error':str(exc)})
        self.reply(404, {'error':'Not found'})

    def do_POST(self):
        app = self.server.emulator
        path = urlparse(self.path).path
        allowed = ('/api/config', '/api/input') if app.role == 'aircraft' else ('/api/transmit', '/api/generate')
        if path not in allowed:
            return self.reply(404, {'error':'Not found'})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.reply(403, {'error':'Origin mismatch'})
        if not app.lock.acquire(blocking=False):
            return self.reply(409, {'error':'処理中です。完了後に再試行してください。'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            limit = 8192 if path in ('/api/config', '/api/generate') else MAX_BYTES
            if not 0 < size <= limit:
                return self.reply(413, {'error':'入力サイズが不正です。'})
            self.connection.settimeout(10)
            payload = self.rfile.read(size)
            if len(payload) != size:
                raise ValueError('入力が途中で切れています。')
            if path == '/api/config':
                result = app.configure(json.loads(payload))
            elif path == '/api/generate':
                data = json.loads(payload)
                if not isinstance(data, dict):
                    raise ValueError('JSONオブジェクトが必要です。')
                snap = app.snapshot()
                mode = data.get('mode', 'selcal16')
                code = snap.to_code(data.get('tail_number', ''), mode)
                wav = make_wav(code, mode=mode)
                if snap.metadata()['rotation_enabled']:
                    wav = attach(wav, snap.metadata())
                return self.reply(200, wav, 'audio/wav')
            else:
                result = app.process(payload)
            self.reply(200, result)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self.reply(400, {'error':str(exc)})
        finally:
            app.lock.release()


def create_server(host, port, emulator):
    server = ThreadingHTTPServer((host, port), Handler)
    server.emulator = emulator
    return server


if __name__ == '__main__':
    role = os.environ.get('HACS_EMULATOR_ROLE', 'radio')
    app = Emulator(role, aircraft_url=os.environ.get('HACS_AIRCRAFT_URL'))
    port = int(os.environ.get('PORT', '8789' if role == 'radio' else '8790'))
    create_server(os.environ.get('HOST', '127.0.0.1'), port, app).serve_forever()
