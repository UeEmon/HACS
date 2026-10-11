"""Administrative token for emergency root-key replacement."""
import hmac
import os
from pathlib import Path
import re

from key_store import KeyStore


def admin_token():
    filename = os.environ.get('HACS_ADMIN_TOKEN_FILE')
    if not filename:
        raise ValueError('共通鍵管理の管理トークンが未設定です。')
    try:
        token = Path(filename).read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-fA-F]{64}', token):
            raise ValueError
        return token
    except (OSError, UnicodeError, ValueError):
        raise ValueError('管理トークンファイルを読み込めないか、形式が不正です。') from None


def authorized(header):
    expected = admin_token()
    return isinstance(header, str) and hmac.compare_digest(header.encode('utf-8'), ('Bearer '+expected).encode('ascii'))


def writable_store():
    filename = os.environ.get('HACS_KEY_STORE')
    if not filename or os.environ.get('HACS_KEY_READONLY') == '1' or os.environ.get('HACS_ROTATION','off') == 'off':
        raise ValueError('共通鍵管理には自動更新と書込み可能な共有鍵ストアが必要です。')
    return KeyStore(filename)
