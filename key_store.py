"""Shared active root key plus metadata audit, without archived secret keys."""
from contextlib import closing
from datetime import datetime, timezone
import hmac
import os
from pathlib import Path
import secrets
import sqlite3


def key_id(root):
    return hmac.digest(root, b'HACS-key-id-v1', 'sha256').hex()[:16]


class KeyStore:
    def __init__(self, filename, readonly=False):
        self.filename = Path(filename)
        self.readonly = readonly

    def initialize(self, root):
        if self.readonly:
            raise ValueError('共有鍵ストアがまだ初期化されていません。')
        if not isinstance(root, bytes) or len(root) != 32:
            raise ValueError('共通鍵は32バイトで指定してください。')
        self.filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(self.filename, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with closing(sqlite3.connect(self.filename, timeout=5)) as db, db:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), root BLOB NOT NULL, generation INTEGER NOT NULL, updated TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS events (generation INTEGER PRIMARY KEY, key_id TEXT NOT NULL, updated TEXT NOT NULL, reason TEXT NOT NULL)')
            now = datetime.now(timezone.utc).isoformat()
            result = db.execute('INSERT OR IGNORE INTO active VALUES(1,?,1,?)', (root,now))
            if result.rowcount:
                db.execute('INSERT INTO events VALUES(1,?,?,?)', (key_id(root),now,'初期設定'))
        if os.name == 'posix':
            self.filename.chmod(0o600)

    def read(self):
        try:
            with closing(sqlite3.connect(self.filename.resolve().as_uri()+('?mode=ro' if self.readonly else '?mode=rw'), uri=True, timeout=5)) as db, db:
                db.execute('BEGIN')
                row = db.execute('SELECT root,generation,updated FROM active WHERE id=1').fetchone()
                info = {'security_revision':0}
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='security_policy'").fetchone():
                    policy = db.execute('SELECT cadence,revision FROM security_policy WHERE id=1').fetchone()
                    if policy:
                        if policy[0] not in ('off','daily','weekly','monthly'):
                            raise ValueError
                        info.update(configured_cadence=policy[0], security_revision=policy[1])
                if row is None or not isinstance(row[0], bytes) or len(row[0]) != 32:
                    raise ValueError
                return row[0], {'key_generation':row[1], 'key_updated_utc':row[2], **info}
        except (sqlite3.Error, ValueError):
            raise ValueError('共有鍵ストアを読み込めません。鍵なし変換へは切り替えません。') from None

    def events(self):
        try:
            with closing(sqlite3.connect(self.filename.resolve().as_uri()+('?mode=ro' if self.readonly else '?mode=rw'), uri=True, timeout=5)) as db, db:
                rows = db.execute('SELECT generation,key_id,updated,reason FROM events ORDER BY generation DESC LIMIT 100').fetchall()
                return [dict(zip(('generation','key_id','updated_utc','reason'), row)) for row in rows]
        except sqlite3.Error:
            raise ValueError('鍵の更新履歴を読み込めません。') from None

    def rotate(self, expected_id, reason):
        if self.readonly:
            raise ValueError('このサービスから共通鍵は変更できません。')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 120 or any(ord(c)<32 or ord(c)==127 for c in reason):
            raise ValueError('更新理由は制御文字なしの1〜120文字で指定してください。')
        try:
            with closing(sqlite3.connect(self.filename, timeout=5)) as db, db:
                db.execute('PRAGMA secure_delete=ON')
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT root,generation FROM active WHERE id=1').fetchone()
                if row is None or expected_id != key_id(row[0]):
                    raise ValueError('鍵は既に変更されています。状態を再取得してから操作してください。')
                root = secrets.token_bytes(32)
                now = datetime.now(timezone.utc).isoformat()
                generation = row[1]+1
                db.execute('UPDATE active SET root=?,generation=?,updated=? WHERE id=1', (root,generation,now))
                db.execute('INSERT INTO events VALUES(?,?,?,?)', (generation,key_id(root),now,reason.strip()))
        except sqlite3.Error:
            raise ValueError('共通鍵の更新に失敗しました。') from None
        return {'key_id':key_id(root), 'key_generation':generation, 'key_updated_utc':now}


    def set_policy(self, cadence, expected_revision):
        if self.readonly:
            raise ValueError('このサービスから秘匿設定は変更できません。')
        if cadence not in ('off','daily','weekly','monthly') or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('秘匿設定または設定世代が不正です。')
        try:
            with closing(sqlite3.connect(self.filename.resolve().as_uri()+'?mode=rw', uri=True, timeout=5)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM active WHERE id=1').fetchone():
                    raise ValueError('共通鍵を初期化してください。')
                db.execute('CREATE TABLE IF NOT EXISTS security_policy (id INTEGER PRIMARY KEY CHECK(id=1), cadence TEXT NOT NULL, revision INTEGER NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS policy_events (revision INTEGER PRIMARY KEY, cadence TEXT NOT NULL, updated TEXT NOT NULL)')
                row = db.execute('SELECT revision FROM security_policy WHERE id=1').fetchone()
                revision = row[0] if row else 0
                if revision != expected_revision:
                    raise ValueError('設定は既に変更されています。状態を再取得してください。')
                revision += 1
                db.execute('INSERT OR REPLACE INTO security_policy VALUES(1,?,?)', (cadence,revision))
                db.execute('INSERT INTO policy_events VALUES(?,?,?)', (revision,cadence,datetime.now(timezone.utc).isoformat()))
        except sqlite3.Error:
            raise ValueError('秘匿設定を保存できませんでした。') from None
        return {'cadence':cadence, 'security_revision':revision}

    def policy_events(self):
        try:
            with closing(sqlite3.connect(self.filename.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_events'").fetchone():
                    return []
                rows = db.execute('SELECT revision,cadence,updated FROM policy_events ORDER BY revision DESC LIMIT 100').fetchall()
                return [dict(zip(('revision','cadence','updated_utc'),row)) for row in rows]
        except sqlite3.Error:
            raise ValueError('秘匿設定の更新履歴を読み込めません。') from None
