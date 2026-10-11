"""Local audio-generation UI. Does not control a radio or PTT."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from selcal import make_wav, validate
from tail_mapping import describe_tail, selcal_to_tail, tail_to_selcal, VERSION
import json
import os

class Handler(BaseHTTPRequestHandler):
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
        if url.path == '/api/convert':
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                if ('tail_number' in query) == ('code' in query):
                    raise ValueError('tail_number または code のどちらか一方を指定してください。')
                result = describe_tail(query['tail_number'][0]) if 'tail_number' in query else describe_tail(selcal_to_tail(query['code'][0]))
            except ValueError as exc:
                return self.reply(400, 'application/json; charset=utf-8', json.dumps({'error':str(exc)},ensure_ascii=False).encode())
            return self.reply(200, 'application/json; charset=utf-8', json.dumps(result).encode())
        if url.path == '/tone.wav':
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                if ('tail_number' in query) == ('code' in query):
                    raise ValueError('tail_number または code のどちらか一方を指定してください。')
                tail = query['tail_number'][0] if 'tail_number' in query else None
                code = validate(tail_to_selcal(tail)) if tail is not None else validate(query['code'][0])
                level = float(query.get('level', ['0.5'])[0])
                body = make_wav(code, level)
            except (ValueError, TypeError) as exc:
                return self.reply(400, 'text/plain; charset=utf-8', str(exc).encode())
            extra = {'Content-Disposition': f'inline; filename="HACS-{tail or code}.wav"', 'X-HACS-SELCAL-Code':code[:2]+'-'+code[2:]}
            if tail is not None:
                extra['X-HACS-Mapping-Version'] = VERSION
            return self.reply(200, 'audio/wav', body, extra)
        self.reply(404, 'text/plain', b'Not found')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8787'))
    print(f'HACS audio UI: http://localhost:{port}', flush=True)
    ThreadingHTTPServer((os.environ.get('HOST', '127.0.0.1'), port), Handler).serve_forever()
