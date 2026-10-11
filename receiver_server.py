"""Receiver simulator service. No RF reception or microphone capture."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import os
import threading
from receiver import MAX_BYTES, decode_wav
from selcal import tones_for, validate
from tail_mapping import mapping_version, tail_to_selcal, selcal_to_tail, validate_tail, describe_tail

class Handler(BaseHTTPRequestHandler):
    analysis_lock = threading.Lock()

    def reply(self, status, body, mime='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == '/':
            return self.reply(200,Path(__file__).with_name('receiver.html').read_bytes(),'text/html; charset=utf-8')
        if urlparse(self.path).path == '/api/convert':
            query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            try:
                mode = query.get('mode', ['selcal16'])[0]
                tones_for(mode)
                if ('tail_number' in query) == ('code' in query):
                    raise ValueError('tail_number または code のどちらか一方を指定してください。')
                result = describe_tail(query['tail_number'][0], mode) if 'tail_number' in query else describe_tail(selcal_to_tail(query['code'][0], mode), mode)
            except ValueError as exc:
                return self.reply(400, {'error': str(exc)})
            return self.reply(200, result)
        self.reply(404,{'error':'Not found'})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != '/api/decode':
            return self.reply(404,{'error':'Not found'})
        try:
            size = int(self.headers.get('Content-Length','0'))
        except ValueError:
            return self.reply(400,{'error':'Content-Lengthが不正です。'})
        if not 0 < size <= MAX_BYTES:
            return self.reply(413,{'error':'WAVは2 MB以下にしてください。'})
        if not self.analysis_lock.acquire(blocking=False):
            return self.reply(409,{'error':'解析中です。完了後に再試行してください。'})
        try:
            self.connection.settimeout(10)
            payload=self.rfile.read(size)
            if len(payload)!=size:
                raise ValueError('アップロードが途中で切れています。')
            query=parse_qs(url.query,keep_blank_values=True)
            mode=query.get('mode',['selcal16'])[0]
            own_mode=query.get('own_mode',[mode])[0]
            tones_for(mode)
            tones_for(own_mode)
            if mode == 'selcal16' and own_mode == 'selcal32':
                raise ValueError('16音の受信能力では32音の自機方式を設定できません。')
            if ('own_tail_number' in query) == ('own_code' in query):
                raise ValueError('own_tail_number または own_code のどちらか一方を指定してください。')
            own_tail=validate_tail(query['own_tail_number'][0]) if 'own_tail_number' in query else None
            own_code=tail_to_selcal(own_tail, own_mode) if own_tail is not None else validate(query['own_code'][0], own_mode)
            result=decode_wav(payload,own_code,mode)
            result['own_tail_number']=own_tail
            result['mapping_version']=mapping_version(own_mode) if own_tail is not None else None
            result['own_mode']=own_mode
            for call in result['calls']:
                try:
                    call_mode='selcal32' if call['extended_tones'] else 'selcal16'
                    call['tail_number']=selcal_to_tail(call['code'], call_mode)
                    call['mapping_version']=mapping_version(call_mode)
                except ValueError:
                    call['tail_number']=None
                    call['mapping_version']=None
        except (ValueError,OSError) as exc:
            self.reply(400,{'error':str(exc)})
        else:
            self.reply(200,result)
        finally:
            self.analysis_lock.release()

if __name__ == '__main__':
    port=int(os.environ.get('PORT','8788'))
    print(f'HACS receiver simulator: http://localhost:{port}',flush=True)
    ThreadingHTTPServer((os.environ.get('HOST','127.0.0.1'),port),Handler).serve_forever()
