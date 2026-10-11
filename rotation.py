"""JST epoch selection and shared-root keyed mappings, not RF encryption."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hmac
import os
from pathlib import Path
import re
import secrets

import tail_mapping as base
from key_store import KeyStore, key_id

JST = timezone(timedelta(hours=9))


def period_at(cadence, now):
    if now.tzinfo is None:
        raise ValueError('タイムゾーン付き日時が必要です。')
    local = now.astimezone(JST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if cadence == 'daily':
        return 'D-'+start.strftime('%Y-%m-%d'), start, start+timedelta(days=1)
    if cadence == 'weekly':
        start -= timedelta(days=start.weekday())
        return 'W-'+start.strftime('%Y-%m-%d'), start, start+timedelta(days=7)
    if cadence == 'monthly':
        start = start.replace(day=1)
        end = (start.replace(year=start.year+1, month=1) if start.month == 12
               else start.replace(month=start.month+1))
        return 'M-'+start.strftime('%Y-%m'), start, end
    raise ValueError('更新周期はdaily、weekly、monthlyで指定してください。')


def parse_period(cadence, identifier):
    try:
        prefix = {'daily':'D-', 'weekly':'W-', 'monthly':'M-'}[cadence]
        pattern = r'[0-9]{4}-[0-9]{2}' + ('' if cadence == 'monthly' else r'-[0-9]{2}')
        if not identifier.startswith(prefix) or not re.fullmatch(pattern, identifier[2:]):
            raise ValueError
        date = identifier[2:] + ('-01' if cadence == 'monthly' else '')
        now = datetime.fromisoformat(date).replace(tzinfo=JST)
        result = period_at(cadence, now)
        if result[0] != identifier:
            raise ValueError
        return result
    except (ValueError, KeyError, AttributeError, OverflowError):
        raise ValueError('生成期間の形式が不正、または更新周期と一致しません。') from None


@lru_cache(maxsize=6)
def _permutation(root, period_id, mode):
    base.mapping_version(mode)
    period_key = hmac.digest(root, b'HACS-period-v1\0'+period_id.encode('ascii'), 'sha256')
    domain = ('HACS-KTN'+('16' if mode == 'selcal16' else '32')+'-v1').encode()+b'\0'
    ordered = sorted(range(10000), key=lambda n: (
        hmac.digest(period_key, domain+f'{n:04d}'.encode('ascii'), 'sha256'), n))
    positions = [0]*10000
    for position, number in enumerate(ordered):
        positions[number] = position
    return tuple(ordered), tuple(positions)


class Mapping:
    def __init__(self, root=None, cadence='off', key_info=None):
        if cadence not in ('off','daily','weekly','monthly'):
            raise ValueError('更新周期が不正です。')
        if cadence != 'off' and (not isinstance(root, bytes) or len(root) != 32):
            raise ValueError('自動更新には32バイトの共通鍵が必要です。')
        self._root = root
        self.cadence = cadence
        self.key_info = key_info or {}

    def snapshot(self, now=None, test_period_id=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('タイムゾーン付き日時が必要です。')
        if self.cadence == 'off':
            if test_period_id:
                raise ValueError('鍵なし設定では生成期間を指定できません。')
            return Snapshot(self, now, None, None, None, False)
        identifier, start, end = period_at(self.cadence, now)
        historical = False
        if test_period_id:
            selected = parse_period(self.cadence, test_period_id)
            if selected[1] > now.astimezone(JST):
                raise ValueError('未来の生成期間は試験に使用できません。')
            historical = selected[0] != identifier
            identifier, start, end = selected
        return Snapshot(self, now, identifier, start, end, historical)


class Snapshot:
    def __init__(self, mapping, now, identifier, start, end, historical):
        self._mapping = mapping
        self.now, self.period_id, self.start, self.end = now, identifier, start, end
        self.historical = historical

    def version(self, mode):
        version = base.mapping_version(mode)
        return version if self.period_id is None else version.replace('HACS-TN','HACS-RKTN')

    def to_code(self, tail, mode='selcal16'):
        number = int(base.validate_tail(tail))
        if self.period_id is not None:
            number = _permutation(self._mapping._root, self.period_id, mode)[1][number]
        return base.tail_to_selcal(f'{number:04d}', mode)

    def to_tail(self, code, mode='selcal16'):
        number = int(base.selcal_to_tail(code, mode))
        if self.period_id is not None:
            number = _permutation(self._mapping._root, self.period_id, mode)[0][number]
        return f'{number:04d}'

    def describe(self, tail, mode='selcal16'):
        return {'tail_number':base.validate_tail(tail), 'selcal_code':self.to_code(tail, mode),
                'mapping_version':self.version(mode), 'mode':mode, **self.metadata()}

    def check_expected(self, expected, expected_key=None):
        if expected is not None and expected != (self.period_id or ''):
            raise ValueError('鍵の期間が更新されました。設定コードを確認して音声を再生成してください。')
        current_key = key_id(self._mapping._root) if self.period_id else ''
        if expected_key is not None and expected_key != current_key:
            raise ValueError('共通鍵が更新されました。設定コードを確認して音声を再生成してください。')

    def metadata(self):
        root = self._mapping._root
        return {'rotation_enabled':self.period_id is not None, 'cadence':self._mapping.cadence,
                'period_id':self.period_id, 'historical_test':self.historical,
                'key_id':key_id(root) if self.period_id else None,
                'period_start_jst':self.start.isoformat() if self.start else None,
                'next_update_jst':self.end.isoformat() if self.end else None,
                'seconds_until_update':max(0,(self.end-self.now).total_seconds()) if self.end else None,
                'server_time_jst':self.now.astimezone(JST).isoformat(), **self._mapping.key_info}


def configured_mapping():
    cadence = os.environ.get('HACS_ROTATION', 'off')
    if cadence == 'off':
        return Mapping()
    if cadence not in ('daily','weekly','monthly'):
        raise ValueError('HACS_ROTATIONはoff、daily、weekly、monthlyで指定してください。')
    store_path = os.environ.get('HACS_KEY_STORE')
    store = KeyStore(store_path, os.environ.get('HACS_KEY_READONLY') == '1') if store_path else None
    if store and store.filename.exists():
        root, info = store.read()
        return Mapping(root, cadence, info)
    if store and os.environ.get('HACS_KEY_CREATE') == '1':
        store.initialize(secrets.token_bytes(32))
        root, info = store.read()
        return Mapping(root, cadence, info)
    filename = os.environ.get('HACS_KEY_FILE')
    if not filename:
        raise ValueError('HACS_KEY_FILEが未設定です。自動更新を開始できません。')
    try:
        value = Path(filename).read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
            raise ValueError
        root = bytes.fromhex(value)
    except (OSError, UnicodeError, ValueError):
        raise ValueError('共通鍵ファイルを読み込めないか、64桁の16進数ではありません。') from None
    if store:
        store.initialize(root)
        root, info = store.read()
        return Mapping(root, cadence, info)
    return Mapping(root, cadence)
