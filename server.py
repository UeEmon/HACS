"""Local audio-generation UI. Does not control a radio or PTT."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from selcal import make_wav, validate
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
        if url.path == '/tone.wav':
            query = parse_qs(url.query)
            try:
                code = validate(query.get('code', [''])[0])
                level = float(query.get('level', ['0.5'])[0])
                body = make_wav(code, level)
            except (ValueError, TypeError) as exc:
                return self.reply(400, 'text/plain; charset=utf-8', str(exc).encode())
            return self.reply(200, 'audio/wav', body, {'Content-Disposition': f'inline; filename="SELCAL-{code}.wav"'})
        self.reply(404, 'text/plain', b'Not found')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8787'))
    print(f'HACS audio UI: http://localhost:{port}', flush=True)
    ThreadingHTTPServer((os.environ.get('HOST', '127.0.0.1'), port), Handler).serve_forever()
