"""Radio host service: runs next to the radio, outside Docker.

SPDX-License-Identifier: Apache-2.0
Receives verified WAV jobs from the HACS main server (Bearer token), checks the
current period/key on the main server right before and after keying, and drives
host audio + serial PTT through RadioInterface. Physical output requires both a
host_audio_serial profile and --allow-physical-output; otherwise the job is a
real-time dry run that never opens a device.
"""
import argparse
import base64
import binascii
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
from pathlib import Path
import re
import threading
import time
import urllib.request
import uuid
import wave

from radio_interface import AudioOutput, PTTOutput, RadioInterface, Timing
from radio_settings import validate as validate_settings
from receiver import MAX_BYTES, decode_wav
from selcal import validate as validate_code

VERSION = 'HACS-RADIO-HOST-v1'
MAX_JOBS = 100
MAX_BODY = 3 * 1024 * 1024  # base64 of a 2 MB WAV plus JSON fields
MAX_JOB_LIFETIME = 60
SIGNAL_SECONDS = 2.2
TERMINAL = ('completed', 'failed', 'cancelled', 'rejected')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def load_token(filename):
    try:
        token = Path(filename).read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-fA-F]{64}', token):
            raise ValueError
        return token
    except (OSError, UnicodeError, ValueError):
        raise ValueError('連携トークンファイルを読み込めないか、形式が不正です。') from None


class Cancelled(Exception):
    """The job was cancelled by the main server."""


class Rejected(ValueError):
    """Checks failed before PTT; nothing was transmitted."""


def fetch_rotation(main_url, timeout=2.0):
    with urllib.request.urlopen(main_url.rstrip('/') + '/api/rotation', timeout=timeout) as resp:
        data = json.loads(resp.read())
    if not isinstance(data, dict):
        raise ValueError('本体の鍵・期間状態を取得できません。')
    return data


class SimulatedAudio(AudioOutput):
    """Dry-run audio that takes the real signal duration but opens no device."""
    def __init__(self, cancel_event):
        self.cancel_event, self.duration = cancel_event, 0.0

    def prepare(self, wav_bytes):
        with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
            self.duration = w.getnframes() / w.getframerate()

    def start(self):
        pass

    def wait_complete(self, timeout_seconds):
        if self.duration > timeout_seconds:
            self.cancel_event.wait(timeout_seconds)
            return False
        return not self.cancel_event.wait(self.duration)

    def stop(self):
        pass


class SimulatedPTT(PTTOutput):
    def activate(self):
        pass

    def release(self):
        pass


class RecordingAudio(AudioOutput):
    """Serializes start/stop with emergency stop and records events for the job."""
    def __init__(self, inner, job):
        self.inner, self.job, self.lock = inner, job, threading.Lock()

    def prepare(self, wav_bytes):
        with self.lock:
            self.job.check_cancel()
            self.inner.prepare(wav_bytes)
        self.job.event('audio_prepare')

    def start(self):
        with self.lock:
            self.job.check_cancel()
            self.inner.start()
        self.job.event('audio_start')

    def wait_complete(self, timeout_seconds):
        completed = self.inner.wait_complete(timeout_seconds)
        self.job.check_cancel()
        if completed:
            self.job.event('audio_complete')
        return completed

    def stop(self):
        with self.lock:
            self.inner.stop()
        self.job.event('audio_stop', once=True)


class RecordingPTT(PTTOutput):
    """PTT wrapper: refuses to key after cancel and releases idempotently from any thread."""
    def __init__(self, inner, job):
        self.inner, self.job, self.lock, self.active = inner, job, threading.Lock(), False

    def activate(self):
        with self.lock:
            self.job.check_cancel()
            self.active = True  # release must run even if activation fails part-way
            self.inner.activate()
        self.job.event('ptt_on')

    def release(self):
        with self.lock:
            if not self.active:
                return
            try:
                self.inner.release()
            finally:
                self.active = False
        self.job.event('ptt_off')


class Job:
    def __init__(self, payload, digest, physical, backend):
        self.id, self.digest = payload['job_id'], digest
        self.payload = {k: payload[k] for k in ('tail_number', 'mode', 'code', 'period_id', 'key_id', 'expires_at')}
        self.wav = payload['_wav']
        self.physical, self.backend = physical, backend
        self.status, self.error = 'accepted', None
        self.events, self.started = [], time.monotonic()
        self.created_utc, self.finished_utc = utc_now(), None
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self.audio = self.ptt = None
        self.done = threading.Event()

    def event(self, name, once=False, **extra):
        with self.lock:
            if once and any(e['event'] == name for e in self.events):
                return
            self.events.append({'event': name, 'utc': utc_now(),
                                'elapsed_seconds': round(time.monotonic() - self.started, 3), **extra})

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise Cancelled('送信は取り消されました。')

    def keyed(self):
        return any(e['event'] == 'ptt_on' for e in self.events)

    def public(self):
        with self.lock:
            return {'job_id': self.id, 'status': self.status, 'error': self.error,
                    **{k: v for k, v in self.payload.items() if k != 'expires_at'},
                    'backend': self.backend, 'physical_output': self.physical,
                    'created_utc': self.created_utc, 'finished_utc': self.finished_utc,
                    'events': list(self.events), 'receiver_acknowledged': False}


class HostService:
    def __init__(self, token, main_url='http://127.0.0.1:8787', allow_physical=False, *,
                 rotation=None, devices=None, drivers=None, sleep=None):
        self.token, self.main_url, self.allow_physical = token, main_url, allow_physical
        self.rotation = rotation or (lambda: fetch_rotation(self.main_url))
        self.list_devices = devices or list_devices
        self.drivers = drivers or physical_drivers
        self.base_sleep = sleep
        self.lock = threading.Lock()
        self.profile = None
        self.profile_checked_utc = None
        self.jobs = OrderedDict()
        self.current = None

    # --- authentication -------------------------------------------------
    def authorized(self, header):
        return isinstance(header, str) and hmac.compare_digest(header.encode('utf-8'), ('Bearer ' + self.token).encode('ascii'))

    # --- status / devices / profile --------------------------------------
    def busy(self):
        return self.current is not None and not self.current.done.is_set()

    def status(self):
        with self.lock:
            last = next(reversed(self.jobs.values())).public() if self.jobs else None
            p = self.profile
            summary = None
            if p:
                summary = {'name': p.get('name'), 'backend': p['backend'], 'output_level': p.get('output_level', 0.5),
                           'audio_device': p['audio_input'].get('host_output_device'),
                           'serial_port': p['ptt'].get('serial_port'), 'control_line': p['ptt'].get('control_line'),
                           'timing': p['timing'], 'standard': (p.get('standard') or {}).get('id'),
                           'checked_utc': self.profile_checked_utc}
            return {'service': VERSION, 'state': 'busy' if self.busy() else ('idle' if p else 'unconfigured'),
                    'physical_output_allowed': self.allow_physical,
                    'physical_output_ready': bool(p and p['backend'] == 'host_audio_serial' and self.allow_physical),
                    'profile': summary, 'last_job': last}

    def apply_profile(self, profile):
        validate_settings(profile)
        if profile['backend'] == 'host_audio_serial':
            check_devices(profile, self.list_devices())  # never opens the port or the stream
        with self.lock:
            if self.busy():
                raise BusyError('送信中は設定を変更できません。')
            self.profile = json.loads(json.dumps(profile))
            self.profile_checked_utc = utc_now()
        return self.status()

    def release_profile(self):
        with self.lock:
            if self.busy():
                raise BusyError('送信中は切断できません。')
            self.profile = None
            self.profile_checked_utc = None
        return self.status()

    # --- jobs -------------------------------------------------------------
    def submit(self, payload):
        payload = parse_job(payload)
        digest = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != '_wav'}, sort_keys=True).encode()
                                + hashlib.sha256(payload['_wav']).digest()).hexdigest()
        with self.lock:
            existing = self.jobs.get(payload['job_id'])
            if existing:
                if existing.digest != digest:
                    raise BusyError('同じジョブIDで異なる内容が送られました。')
                return existing.public(), False
            if self.busy():
                raise BusyError('送信中です。完了後に再試行してください。')
            if not self.profile:
                raise ValueError('ホストに無線機設定が適用されていません。')
            profile = json.loads(json.dumps(self.profile))
            physical = profile['backend'] == 'host_audio_serial'
            if physical and not self.allow_physical:
                raise ValueError('このホストサービスは実出力が許可されていません（--allow-physical-output）。')
            job = Job(payload, digest, physical, profile['backend'])
            self.jobs[job.id] = job
            while len(self.jobs) > MAX_JOBS:
                self.jobs.popitem(last=False)
            self.current = job
            accepted = job.public()  # snapshot before the worker can change the state
        threading.Thread(target=self._run, args=(job, profile), daemon=True, name=f'job-{job.id}').start()
        return accepted, True

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            raise KeyError('ジョブが見つかりません。')
        return job.public()

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            raise KeyError('ジョブが見つかりません。')
        if job.done.is_set():
            return job.public()
        job.cancel_event.set()
        job.event('cancel_requested')
        # Emergency release from this thread; the job thread also releases in its finally.
        for part in (job.ptt, job.audio):
            if part is not None:
                try:
                    part.release() if part is job.ptt else part.stop()
                except Exception as exc:  # report, keep releasing
                    job.event('release_error', detail=str(exc)[:200])
        return job.public()

    def _sleep(self, job):
        def sleep(seconds):
            if self.base_sleep:
                self.base_sleep(seconds)
                job.check_cancel()
            elif job.cancel_event.wait(seconds):
                raise Cancelled('送信は取り消されました。')
        return sleep

    def _guard(self, job, timing):
        def guard():
            job.check_cancel()
            if time.time() > job.payload['expires_at']:
                raise Rejected('ジョブの期限を過ぎました。')
            try:
                current = self.rotation()
            except Exception:
                raise Rejected('本体の鍵・期間状態を確認できません。') from None
            if (current.get('period_id') or '') != job.payload['period_id'] or (current.get('key_id') or '') != job.payload['key_id']:
                raise Rejected('本体の鍵・期間が変わりました。音声を再生成してください。')
            remaining = current.get('seconds_until_update')
            if remaining is not None and remaining <= timing.lead_seconds + SIGNAL_SECONDS + timing.tail_seconds + 0.5:
                raise Rejected('期間切替の直前です。更新後に再実行してください。')
            job.event('guard_ok')
        return guard

    def _run(self, job, profile):
        try:
            with job.lock:
                job.status = 'running'
            job.event('started', physical_output=job.physical)
            if time.time() > job.payload['expires_at']:
                raise Rejected('ジョブの期限を過ぎました。')
            timing = Timing(**profile['timing'])
            if job.physical:
                audio, ptt = self.drivers(profile)
            else:
                audio, ptt = SimulatedAudio(job.cancel_event), SimulatedPTT()
            job.audio, job.ptt = RecordingAudio(audio, job), RecordingPTT(ptt, job)
            RadioInterface(job.audio, job.ptt, timing, sleep=self._sleep(job)).run(
                job.wav, job.payload['code'], job.payload['mode'], self._guard(job, timing))
            status, error = 'completed', None
        except Cancelled as exc:
            status, error = 'cancelled', str(exc)
        except Exception as exc:
            status, error = 'failed', str(exc)[:300]
            if job.cancel_event.is_set():
                status = 'cancelled'
            elif not job.keyed() and isinstance(exc, (Rejected, ValueError)):
                status = 'rejected'
        finally:
            # RadioInterface already released; repeat defensively (idempotent wrappers).
            for part in (job.ptt, job.audio):
                if part is not None:
                    try:
                        part.release() if part is job.ptt else part.stop()
                    except Exception as exc:
                        job.event('release_error', detail=str(exc)[:200])
        with job.lock:
            job.status, job.error, job.finished_utc = status, error, utc_now()
        job.event('finished', status=status)
        job.done.set()


class BusyError(Exception):
    pass


def parse_job(data):
    if not isinstance(data, dict):
        raise ValueError('JSONオブジェクトが必要です。')
    job_id = data.get('job_id')
    try:
        if not isinstance(job_id, str) or str(uuid.UUID(job_id)) != job_id:
            raise ValueError
    except ValueError:
        raise ValueError('job_idはUUID形式で指定してください。') from None
    mode = data.get('mode')
    if mode not in ('selcal16', 'selcal32'):
        raise ValueError('方式はselcal16またはselcal32です。')
    tail = data.get('tail_number')
    if not isinstance(tail, str) or not re.fullmatch(r'[0-9]{4}', tail):
        raise ValueError('呼び出し相手先は4桁の数字です。')
    code = validate_code(data.get('code'), mode)
    period, key = data.get('period_id', ''), data.get('key_id', '')
    if not isinstance(period, str) or not isinstance(key, str) or len(period) > 40 or len(key) > 40:
        raise ValueError('期間・鍵識別子が不正です。')
    expires = data.get('expires_at')
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
        raise ValueError('expires_atが不正です。')
    if expires > time.time() + MAX_JOB_LIFETIME:
        raise ValueError('ジョブの期限が長すぎます。')
    try:
        wav = base64.b64decode(data.get('wav_base64', ''), validate=True)
    except (binascii.Error, TypeError, ValueError):
        raise ValueError('WAVのBase64形式が不正です。') from None
    if not 0 < len(wav) <= MAX_BYTES:
        raise ValueError('WAVは2 MB以下にしてください。')
    detection = decode_wav(wav, code, mode)
    if len(detection['calls']) != 1 or not detection['calls'][0]['matched']:
        raise ValueError('WAVの解析結果が期待コードと一致しません。')
    return {'job_id': job_id, 'tail_number': tail, 'mode': mode, 'code': code,
            'period_id': period, 'key_id': key, 'expires_at': float(expires), '_wav': wav}


def list_devices():
    out = {'audio': {'available': False, 'devices': []}, 'serial': {'available': False, 'ports': []}}
    try:
        from radio_drivers import sounddevice_module
        sd = sounddevice_module()
        apis = sd.query_hostapis()
        out['audio'] = {'available': True, 'devices': [
            {'id': i, 'name': d['name'], 'output_channels': d['max_output_channels'],
             'host_api': apis[d['hostapi']]['name'] if isinstance(d.get('hostapi'), int) and d['hostapi'] < len(apis) else None}
            for i, d in enumerate(sd.query_devices()) if d['max_output_channels'] > 0]}
    except Exception as exc:
        out['audio']['reason'] = str(exc)[:200]
    try:
        from serial.tools import list_ports
        out['serial'] = {'available': True, 'ports': [
            {'device': p.device, 'description': p.description, 'hwid': p.hwid} for p in list_ports.comports()]}
    except Exception as exc:
        out['serial']['reason'] = 'pyserialが必要です。' if isinstance(exc, ImportError) else str(exc)[:200]
    return out


def check_devices(profile, found):
    """Confirm the configured device and port exist without opening them."""
    audio, ptt = profile['audio_input'], profile['ptt']
    if not found['audio'].get('available'):
        raise ValueError('ホストの音声機器を確認できません：' + found['audio'].get('reason', ''))
    if not found['serial'].get('available'):
        raise ValueError('ホストのシリアルポートを確認できません：' + found['serial'].get('reason', ''))
    device, channels = audio['host_output_device'], audio.get('channels', 1)
    devices = found['audio']['devices']
    if isinstance(device, int):
        match = [d for d in devices if d['id'] == device]
    else:
        match = [d for d in devices if d['name'] == device]
    if len(match) != 1:
        raise ValueError('指定した音声出力機器が見つからないか、同名の機器が複数あります。IDで指定してください。')
    if match[0]['output_channels'] < channels:
        raise ValueError('指定した音声出力機器はチャンネル数が不足しています。')
    if ptt['serial_port'] not in [p['device'] for p in found['serial']['ports']]:
        raise ValueError('指定したシリアルポートが見つかりません。')


def physical_drivers(profile):
    from radio_drivers import SoundDeviceAudio, SerialPTT
    audio, ptt = profile['audio_input'], profile['ptt']
    return (SoundDeviceAudio(audio['host_output_device'], audio.get('channels', 1)),
            SerialPTT(ptt['serial_port'], ptt['control_line'], ptt['active_high']))


class Handler(BaseHTTPRequestHandler):
    server_version = 'HACS-radio-host'

    def log_message(self, fmt, *args):  # no Authorization or bodies in logs
        super().log_message('%s', f'{self.command} {self.path.split("?")[0]} -> {args[1] if len(args) > 1 else ""}')

    def reply(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def guarded(self):
        if self.headers.get('Origin'):
            self.reply(403, {'error': 'ブラウザからの直接接続は受け付けません。'})
            return False
        if not self.server.service.authorized(self.headers.get('Authorization')):
            self.reply(401, {'error': '連携トークンが必要です。'})
            return False
        return True

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise TypeError('application/jsonが必要です。')
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= MAX_BODY:
            raise OverflowError('要求サイズが不正です。')
        self.connection.settimeout(10)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError('要求が途中で切れています。')
        return json.loads(raw)

    def do_GET(self):
        if not self.guarded():
            return
        svc, path = self.server.service, self.path.split('?')[0]
        try:
            if path == '/v1/status':
                return self.reply(200, svc.status())
            if path == '/v1/devices':
                return self.reply(200, svc.list_devices())
            m = re.fullmatch(r'/v1/jobs/([0-9a-f-]{36})', path)
            if m:
                return self.reply(200, svc.get(m.group(1)))
        except KeyError as exc:
            return self.reply(404, {'error': exc.args[0]})
        self.reply(404, {'error': 'Not found'})

    def do_DELETE(self):
        if not self.guarded():
            return
        if self.path.split('?')[0] != '/v1/profile':
            return self.reply(404, {'error': 'Not found'})
        try:
            self.reply(200, self.server.service.release_profile())
        except BusyError as exc:
            self.reply(409, {'error': str(exc)})

    def do_POST(self):
        if not self.guarded():
            return
        svc, path = self.server.service, self.path.split('?')[0]
        try:
            m = re.fullmatch(r'/v1/jobs/([0-9a-f-]{36})/cancel', path)
            if m:
                return self.reply(200, svc.cancel(m.group(1)))
            if path not in ('/v1/profile', '/v1/jobs'):
                return self.reply(404, {'error': 'Not found'})
            data = self.body()
            if path == '/v1/profile':
                return self.reply(200, svc.apply_profile(data))
            job, created = svc.submit(data)
            return self.reply(202 if created else 200, job)
        except KeyError as exc:
            self.reply(404, {'error': exc.args[0]})
        except BusyError as exc:
            self.reply(409, {'error': str(exc)})
        except TypeError as exc:
            self.reply(415, {'error': str(exc)})
        except OverflowError as exc:
            self.reply(413, {'error': str(exc)})
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {'error': str(exc)})


def create_server(service, host='127.0.0.1', port=8791):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.service = service
    return server


def main(argv=None):
    p = argparse.ArgumentParser(description='HACS無線機ホストサービス（既定はドライラン）')
    p.add_argument('--token-file', required=True, help='連携トークン（generate_key.pyで作成）')
    p.add_argument('--bind', default='127.0.0.1', help='待受アドレス（LinuxのDockerからはブリッジのゲートウェイ）')
    p.add_argument('--port', type=int, default=8791)
    p.add_argument('--main-url', default='http://127.0.0.1:8787', help='本体のURL（鍵・期間の照合に使用）')
    p.add_argument('--allow-physical-output', action='store_true',
                   help='host_audio_serialプロファイルで実際の音声出力とPTT操作を許可する')
    args = p.parse_args(argv)
    try:
        service = HostService(load_token(args.token_file), args.main_url, args.allow_physical_output)
    except ValueError as exc:
        p.error(str(exc))
    print(f'HACS radio host service: http://{args.bind}:{args.port} '
          f'(physical output {"ALLOWED" if args.allow_physical_output else "disabled"})', flush=True)
    create_server(service, args.bind, args.port).serve_forever()


if __name__ == '__main__':
    main()
