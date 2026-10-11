"""Unsigned bench-file context; RF tones do not carry these fields."""
import json
import struct


def attach(payload, metadata):
    context = json.dumps({k:metadata[k] for k in ('period_id','key_id')}, separators=(',',':')).encode('ascii')
    chunk = b'hacs'+struct.pack('<I',len(context))+context+(b'\0' if len(context)%2 else b'')
    body = payload+chunk
    return body[:4]+struct.pack('<I',len(body)-8)+body[8:]


def read(payload):
    if len(payload)<12 or payload[:4]!=b'RIFF' or payload[8:12]!=b'WAVE':
        return None
    offset=12
    found=None
    while offset+8<=len(payload):
        name=payload[offset:offset+4]
        size=struct.unpack_from('<I',payload,offset+4)[0]
        end=offset+8+size
        if end>len(payload):
            raise ValueError('WAVチャンクが途中で切れています。')
        if name==b'hacs':
            if found is not None or size>512:
                raise ValueError('WAVの生成期間情報が不正です。')
            try:
                found=json.loads(payload[offset+8:end])
                if not isinstance(found,dict) or any(not isinstance(found.get(k),str) for k in ('period_id','key_id')):
                    raise ValueError
            except (ValueError,UnicodeError):
                raise ValueError('WAVの生成期間情報が不正です。') from None
        offset=end+(size%2)
    return found
