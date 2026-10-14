"""Persistent calling presets; never stores keys or time-dependent codes."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3

from selcal import tones_for
from tail_mapping import validate_tail


class Presets:
    def __init__(self, filename=None):
        self.filename = Path(filename) if filename else Path(os.environ.get('HACS_DATA_DIR', Path(__file__).parent/'data'))/'presets.sqlite3'

    @contextmanager
    def connection(self):
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.filename, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('CREATE TABLE IF NOT EXISTS presets (id INTEGER PRIMARY KEY, name TEXT NOT NULL, tail_number TEXT NOT NULL, mode TEXT NOT NULL, UNIQUE(tail_number,mode))')
            with db:
                yield db
        finally:
            db.close()

    def list(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,name,tail_number,mode FROM presets ORDER BY name,id')]

    def save(self, data):
        if not isinstance(data, dict):
            raise ValueError('プリセットはJSONオブジェクトで指定してください。')
        name = data.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c)<32 or ord(c)==127 for c in name):
            raise ValueError('名称は改行や制御文字を含まない1〜80文字で入力してください。')
        tail = validate_tail(data.get('tail_number'))
        mode = data.get('mode')
        tones_for(mode)
        identifier = data.get('id')
        if identifier is not None and (type(identifier) is not int or identifier <= 0):
            raise ValueError('プリセットIDが不正です。')
        try:
            with self.connection() as db:
                if identifier is None:
                    identifier = db.execute('INSERT INTO presets(name,tail_number,mode) VALUES(?,?,?)', (name.strip(),tail,mode)).lastrowid
                else:
                    result = db.execute('UPDATE presets SET name=?,tail_number=?,mode=? WHERE id=?', (name.strip(),tail,mode,identifier))
                    if result.rowcount != 1:
                        raise ValueError('対象のプリセットが存在しません。')
                return dict(db.execute('SELECT id,name,tail_number,mode FROM presets WHERE id=?', (identifier,)).fetchone())
        except sqlite3.IntegrityError:
            raise ValueError('同じ呼び出し相手先・方式のプリセットが登録済みです。既存の項目を選択して更新してください。') from None

    def delete(self, identifier):
        if type(identifier) is not int or identifier <= 0:
            raise ValueError('プリセットIDが不正です。')
        with self.connection() as db:
            if db.execute('DELETE FROM presets WHERE id=?', (identifier,)).rowcount != 1:
                raise ValueError('対象のプリセットが存在しません。')
