"""Local audio-generation UI. Does not control a radio or PTT."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from selcal import make_wav, validate, tones_for
from rotation import configured_mapping
from presets import Presets
from preset_exports import build_list, csv_bytes
import sqlite3
import key_admin
from wav_context import attach
import json
import os

class Handler(BaseHTTPRequestHandler):
    mapping = None
    presets = None

    def snapshot(self):
        return (self.mapping or configured_mapping()).snapshot()

    def reply(self, status, mime, body, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/':
            return self.reply(200, 'text/html; charset=utf-8', Path(__file__).with_name('index.html').read_bytes())
        if url.path == '/keys_ui.js':
            return self.reply(200, 'text/javascript; charset=utf-8', Path(__file__).with_name('keys_ui.js').read_bytes())
        if url.path == '/presets_ui.js':
            return self.reply(200, 'text/javascript; charset=utf-8', Path(__file__).with_name('presets_ui.js').read_bytes())
        if url.path == '/api/keys':
            try:
                if not key_admin.authorized(self.headers.get('Authorization')):
                    return self.reply(401,'application/json',b'{"error":"Administrator token required"}')
                store = key_admin.writable_store()
                data = {'events':store.events(), **self.snapshot().metadata()}
            except ValueError as exc:
                return self.reply(503,'application/json; charset=utf-8',json.dumps({'error':str(exc)},ensure_ascii=False).encode())
            return self.reply(200,'application/json',json.dumps(data).encode())
        if url.path in ('/api/presets/codes', '/api/presets/export.csv'):
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                snapshot = self.snapshot()
                snapshot.check_expected(query.get('period_id', [None])[0], query.get('key_id', [None])[0])
                data = build_list((self.presets or Presets()).list(), snapshot)
            except ValueError as exc:
                return self.reply(400, 'application/json; charset=utf-8', json.dumps({'error':str(exc)}, ensure_ascii=False).encode())
            except (OSError, sqlite3.Error):
                return self.reply(503, 'application/json', b'{"error":"Preset storage unavailable"}')
            if url.path.endswith('.csv'):
                period = data['period_id'] or 'fixed'
                return self.reply(200, 'text/csv; charset=utf-8', csv_bytes(data), {
                    'Content-Disposition': f'attachment; filename="HACS-presets-{period}.csv"',
                    'X-HACS-Period': data['period_id'] or '',
                    'X-HACS-Key-ID': data['key_id'] or '',
                })
            return self.reply(200, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False).encode())
        if url.path == '/api/presets':
            try:
                data = {'presets':(self.presets or Presets()).list()}
            except (OSError, sqlite3.Error):
                return self.reply(503, 'application/json; charset=utf-8', json.dumps({'error':'プリセット保存先を利用できません。'}).encode())
            return self.reply(200, 'application/json; charset=utf-8', json.dumps(data).encode())
        if url.path == '/rotation_ui.js':
            return self.reply(200, 'text/javascript; charset=utf-8', Path(__file__).with_name('rotation_ui.js').read_bytes())
        if url.path == '/api/rotation':
            try:
                data = self.snapshot().metadata()
            except ValueError as exc:
                return self.reply(503, 'application/json; charset=utf-8', json.dumps({'error':str(exc)},ensure_ascii=False).encode())
            return self.reply(200, 'application/json; charset=utf-8', json.dumps(data).encode())
        if url.path == '/api/convert':
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                mapping = self.snapshot()
                mapping.check_expected(query.get('period_id', [None])[0], query.get('key_id',[None])[0])
                mode = query.get('mode', ['selcal16'])[0]
                tones_for(mode)
                if ('tail_number' in query) == ('code' in query):
                    raise ValueError('tail_number または code のどちらか一方を指定してください。')
                result = mapping.describe(query['tail_number'][0], mode) if 'tail_number' in query else mapping.describe(mapping.to_tail(query['code'][0], mode), mode)
            except ValueError as exc:
                return self.reply(400, 'application/json; charset=utf-8', json.dumps({'error':str(exc)},ensure_ascii=False).encode())
            return self.reply(200, 'application/json; charset=utf-8', json.dumps(result).encode())
        if url.path == '/tone.wav':
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                mapping = self.snapshot()
                mapping.check_expected(query.get('period_id', [None])[0], query.get('key_id',[None])[0])
                mode = query.get('mode', ['selcal16'])[0]
                tones_for(mode)
                if ('tail_number' in query) == ('code' in query):
                    raise ValueError('tail_number または code のどちらか一方を指定してください。')
                tail = query['tail_number'][0] if 'tail_number' in query else None
                code = validate(mapping.to_code(tail, mode), mode) if tail is not None else validate(query['code'][0], mode)
                level = float(query.get('level', ['0.5'])[0])
                body = make_wav(code, level, mode)
                if mapping.period_id and tail is not None:
                    body = attach(body, mapping.metadata())
            except (ValueError, TypeError) as exc:
                return self.reply(400, 'text/plain; charset=utf-8', str(exc).encode())
            extra = {'Content-Disposition': f'inline; filename="HACS-{tail or code}.wav"', 'X-HACS-SELCAL-Code':code[:2]+'-'+code[2:], 'X-HACS-Mode':mode, 'X-HACS-Period':mapping.period_id or '', 'X-HACS-Key-ID':mapping.metadata()['key_id'] or '', 'X-HACS-Next-Update':mapping.metadata()['next_update_jst'] or ''}
            if tail is not None:
                extra['X-HACS-Mapping-Version'] = mapping.version(mode)
            return self.reply(200, 'audio/wav', body, extra)
        self.reply(404, 'text/plain', b'Not found')

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ('/api/presets','/api/keys'):
            return self.reply(404, 'application/json', b'{}')
        origin = self.headers.get('Origin')
        if origin and (urlparse(origin).scheme not in ('http','https') or urlparse(origin).netloc != self.headers.get('Host')):
            return self.reply(403,'application/json',b'{"error":"Cross-origin mutation refused"}')
        if self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
            return self.reply(415,'application/json',b'{"error":"application/json required"}')
        if path == '/api/keys':
            try:
                if not key_admin.authorized(self.headers.get('Authorization')):
                    return self.reply(401,'application/json',b'{"error":"Administrator token required"}')
            except ValueError as exc:
                return self.reply(503,'application/json',json.dumps({'error':str(exc)}).encode())
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 8192:
                return self.reply(413, 'application/json', b'{"error":"Request too large or empty"}')
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('JSONオブジェクトが必要です。')
            if path == '/api/keys':
                if data.get('action') != 'rotate':
                    raise ValueError('共通鍵管理の操作はrotateで指定してください。')
                if not isinstance(data.get('expected_key_id'),str):
                    raise ValueError('現在の鍵識別子が必要です。')
                result = key_admin.writable_store().rotate(data['expected_key_id'], data.get('reason'))
                return self.reply(200,'application/json',json.dumps(result).encode())
            store = self.presets or Presets()
            action = data.get('action')
            if action == 'delete':
                store.delete(data.get('id'))
                result = {'deleted':True}
            elif action in ('create','update'):
                if action == 'create' and data.get('id') is not None:
                    raise ValueError('新規登録ではIDを指定しないでください。')
                if action == 'update' and data.get('id') is None:
                    raise ValueError('更新対象のIDが必要です。')
                result = {'preset':store.save(data)}
            else:
                raise ValueError('操作はcreate、update、deleteで指定してください。')
        except (ValueError, UnicodeError) as exc:
            return self.reply(400, 'application/json; charset=utf-8', json.dumps({'error':str(exc)},ensure_ascii=False).encode())
        except (OSError, sqlite3.Error):
            return self.reply(503, 'application/json; charset=utf-8', json.dumps({'error':'プリセット保存先を利用できません。'}).encode())
        return self.reply(200, 'application/json; charset=utf-8', json.dumps(result).encode())

if __name__ == '__main__':
    if os.environ.get('HACS_ADMIN_TOKEN_FILE'):
        key_admin.admin_token()
    configured_mapping()  # Fail startup rather than falling back if key settings are invalid.
    port = int(os.environ.get('PORT', '8787'))
    print(f'HACS audio UI: http://localhost:{port}', flush=True)
    ThreadingHTTPServer((os.environ.get('HOST', '127.0.0.1'), port), Handler).serve_forever()
