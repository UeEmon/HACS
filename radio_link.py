"""Main-server side of the radio host link and server-side transmit history.

SPDX-License-Identifier: Apache-2.0
The link token is separate from the administrator token and the mapping key.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import urllib.error
import urllib.request

from radio_host_service import load_token

TERMINAL = ('completed', 'failed', 'cancelled', 'rejected', 'submit_failed')
KEEP_RECORDS = 1000


class HostUnavailable(Exception):
    """The host service could not be reached or answered unexpectedly."""


class RadioHostClient:
    def __init__(self, url=None, token_file=None, timeout=5.0):
        self.url = (url if url is not None else os.environ.get('HACS_RADIO_HOST_URL', '')).rstrip('/')
        self.token_file = token_file if token_file is not None else os.environ.get('HACS_RADIO_HOST_TOKEN_FILE', '')
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.url and self.token_file)

    def request(self, method, path, body=None):
        if not self.configured:
            raise HostUnavailable('無線機ホストサービスが設定されていません（HACS_RADIO_HOST_URL・HACS_RADIO_HOST_TOKEN_FILE）。')
        token = load_token(self.token_file)
        headers = {'Authorization': f'Bearer {token}'}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read())
            except ValueError:
                payload = {'error': f'HTTP {exc.code}'}
            if exc.code == 401:
                raise HostUnavailable('無線機ホストサービスの連携トークンが一致しません。') from None
            return exc.code, payload
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise HostUnavailable('無線機ホストサービスに接続できません。') from exc


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class TransmitLog:
    """Server-side record of transmit requests. Never stores WAV data or tokens."""
    COLUMNS = ('job_id', 'created_utc', 'updated_utc', 'tail_number', 'mode', 'code', 'period_id', 'key_id',
               'output_level', 'backend', 'physical_output', 'status', 'error', 'events')

    def __init__(self, filename=None):
        self.filename = Path(filename) if filename else Path(os.environ.get('HACS_DATA_DIR', Path(__file__).parent / 'data')) / 'transmit.sqlite3'

    def connect(self):
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.filename, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS transmit (seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL, '
                   'created_utc TEXT, updated_utc TEXT, tail_number TEXT, mode TEXT, code TEXT, period_id TEXT, key_id TEXT, '
                   'output_level REAL, backend TEXT, physical_output INTEGER, status TEXT, error TEXT, events TEXT)')
        return db

    def create(self, record):
        now = utc_now()
        row = {**{c: None for c in self.COLUMNS}, **record, 'created_utc': now, 'updated_utc': now}
        row['events'] = json.dumps(row.get('events') or [], ensure_ascii=False)
        with closing(self.connect()) as db, db:
            db.execute(f'INSERT INTO transmit ({",".join(self.COLUMNS)}) VALUES ({",".join("?" * len(self.COLUMNS))})',
                       [row[c] for c in self.COLUMNS])
            db.execute('DELETE FROM transmit WHERE seq <= (SELECT MAX(seq) FROM transmit) - ?', (KEEP_RECORDS,))
        return self.get(record['job_id'])

    def update(self, job_id, **fields):
        allowed = {k: v for k, v in fields.items() if k in ('status', 'error', 'events', 'backend', 'physical_output')}
        if 'events' in allowed:
            allowed['events'] = json.dumps(allowed['events'] or [], ensure_ascii=False)
        allowed['updated_utc'] = utc_now()
        with closing(self.connect()) as db, db:
            current = db.execute('SELECT status FROM transmit WHERE job_id=?', (job_id,)).fetchone()
            if current is None:
                raise KeyError('送信記録が見つかりません。')
            if current[0] in TERMINAL and allowed.get('status') not in (None, current[0]):
                allowed.pop('status')  # never move a finished record back
            db.execute(f'UPDATE transmit SET {",".join(k + "=?" for k in allowed)} WHERE job_id=?', [*allowed.values(), job_id])
        return self.get(job_id)

    def get(self, job_id):
        with closing(self.connect()) as db:
            row = db.execute(f'SELECT {",".join(self.COLUMNS)} FROM transmit WHERE job_id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError('送信記録が見つかりません。')
        return self._public(row)

    def list(self, limit=200):
        with closing(self.connect()) as db:
            rows = db.execute(f'SELECT {",".join(self.COLUMNS)} FROM transmit ORDER BY seq DESC LIMIT ?', (int(limit),)).fetchall()
        return [self._public(r) for r in rows]

    def active(self):
        with closing(self.connect()) as db:
            row = db.execute(f'SELECT {",".join(self.COLUMNS)} FROM transmit WHERE status NOT IN ({",".join("?" * len(TERMINAL))}) '
                             'AND status != ? ORDER BY seq DESC LIMIT 1', (*TERMINAL, 'unknown')).fetchone()
        return self._public(row) if row else None

    def _public(self, row):
        record = dict(zip(self.COLUMNS, row))
        record['events'] = json.loads(record['events'] or '[]')
        record['physical_output'] = None if record['physical_output'] is None else bool(record['physical_output'])
        record['receiver_acknowledged'] = False
        return record
