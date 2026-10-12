"""Persist a host radio profile. Saving never opens hardware or asserts PTT."""
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
from radio_host import validate_profile
from radio_interface import Timing


def default_profile():
    return {'profile_version':'HACS-RADIO-v1','name':'無線機インターフェース',
            'backend':'dry_run','output_level':0.5,'radio':{'manufacturer':'','model':''},
            'audio_input':{'host_output_device':'','channels':1},
            'ptt':{'method':'serial_control_line','serial_port':'','control_line':'rts','active_high':True},
            'timing':{'lead_seconds':.3,'tail_seconds':.2,'max_ptt_seconds':5.0}}


def validate(profile):
    if not isinstance(profile,dict) or profile.get('profile_version')!='HACS-RADIO-v1':
        raise ValueError('プロファイル形式が不正です。')
    if profile.get('backend') not in ('dry_run','host_audio_serial'):
        raise ValueError('対応方式はdry_runまたはhost_audio_serialです。')
    level=profile.get('output_level',0.5)
    if type(level) not in (int,float) or not math.isfinite(level) or not .01<=level<=.9:
        raise ValueError('出力レベルは1〜90%の有限値で指定してください。')
    name=profile.get('name')
    radio=profile.get('radio')
    if not isinstance(radio,dict):raise ValueError('無線機情報が必要です。')
    for value in (name,radio.get('manufacturer'),radio.get('model')):
        if not isinstance(value,str) or len(value)>120 or any(ord(c)<32 for c in value):
            raise ValueError('名称・メーカー・型式は120文字以内で指定してください。')
    if not name.strip():raise ValueError('設定名を入力してください。')
    timing=profile.get('timing')
    if not isinstance(timing,dict) or set(timing)!={'lead_seconds','tail_seconds','max_ptt_seconds'}:
        raise ValueError('PTT時間設定が不正です。')
    t=Timing(**timing)
    if t.lead_seconds+2.2+t.tail_seconds>=t.max_ptt_seconds:
        raise ValueError('PTT上限は前待ち＋音声2.2秒＋後待ちより大きくしてください。')
    for name in ('audio_input','ptt'):
        if not isinstance(profile.get(name),dict):raise ValueError('音声・PTT設定が不正です。')
    audio,ptt=profile['audio_input'],profile['ptt']
    if type(audio.get('channels')) is not int or audio['channels'] not in (1,2):raise ValueError('チャンネル数が不正です。')
    if ptt.get('method')!='serial_control_line' or ptt.get('control_line') not in ('rts','dtr') or type(ptt.get('active_high')) is not bool:raise ValueError('PTT設定が不正です。')
    device=audio.get('host_output_device')
    if type(device) not in (str,int) or (isinstance(device,int) and device<0):raise ValueError('デバイス指定が不正です。')
    for value in (ptt.get('serial_port'),device if isinstance(device,str) else ''):
        if not isinstance(value,str) or len(value)>200 or any(ord(c)<32 for c in value):raise ValueError('デバイス名・ポート名が不正です。')
    # Enforce the actual host driver's validation without opening devices.
    if profile['backend']=='host_audio_serial':validate_profile(profile)
    return profile


class RadioSettings:
    def __init__(self,filename=None):
        self.filename=Path(filename) if filename else Path(os.environ.get('HACS_DATA_DIR',Path(__file__).parent/'data'))/'radio.sqlite3'

    def connect(self):
        self.filename.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.filename,timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, profile TEXT NOT NULL)')
        return db

    def read(self):
        with closing(self.connect()) as db:
            row=db.execute('SELECT revision,profile FROM configuration WHERE id=1').fetchone()
            return {'revision':row[0], 'profile':json.loads(row[1])} if row else {'revision':0,'profile':default_profile()}

    def save(self,profile,revision):
        validate(profile)
        if type(revision) is not int or revision<0:raise ValueError('設定世代が不正です。')
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM configuration WHERE id=1').fetchone()
            if revision!=(row[0] if row else 0):raise ValueError('設定が変更されています。再読込してから保存してください。')
            db.execute('INSERT OR REPLACE INTO configuration VALUES(1,?,?)',(revision+1,json.dumps(profile,ensure_ascii=False,allow_nan=False)))
        return {'revision':revision+1,'profile':profile,'physical_output':False}
