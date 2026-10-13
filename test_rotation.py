from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import sys
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from generate_key import create_key
from key_store import KeyStore
from presets import Presets
from rotation import Mapping, KeyStoreNotReady, configured_mapping, period_at, parse_period, wait_for_mapping
from server import Handler as TxHandler
from receiver_server import Handler as RxHandler
from tail_mapping import tail_to_selcal
from selcal import validate
from wav_context import read as read_context


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


class RotationTests(unittest.TestCase):
    def test_exact_jst_boundaries_and_calendar(self):
        before=utc('2026-10-11T14:59:59.999999')
        after=utc('2026-10-11T15:00:00')
        for cadence, first, second in [('daily','D-2026-10-11','D-2026-10-12'),
                                      ('weekly','W-2026-10-05','W-2026-10-12')]:
            self.assertEqual(period_at(cadence,before)[0],first)
            self.assertEqual(period_at(cadence,after)[0],second)
            self.assertEqual(period_at(cadence,before)[2],after)
        self.assertEqual(period_at('monthly',utc('2026-12-31T14:59:59'))[0], 'M-2026-12')
        self.assertEqual(period_at('monthly',utc('2026-12-31T15:00:00'))[0], 'M-2027-01')
        self.assertEqual(period_at('monthly',utc('2028-02-01T00:00:00'))[2].day,1)
        self.assertEqual(period_at('monthly',utc('2028-02-01T00:00:00'))[2].month,3)
        with self.assertRaises(ValueError): period_at('daily',datetime(2026,10,11))

    def test_period_validation_and_history(self):
        mapping=Mapping(bytes(range(32)),'weekly')
        now=utc('2026-10-12T00:00:00')
        old=mapping.snapshot(now,'W-2026-10-05')
        self.assertTrue(old.metadata()['historical_test'])
        self.assertEqual(old.period_id,'W-2026-10-05')
        for identifier in ['D-2026-10-12','W-2026-10-11','W-2026-99-01','W-2026-10-19']:
            with self.assertRaises(ValueError): mapping.snapshot(now,identifier)
        with self.assertRaises(ValueError): Mapping().snapshot(now,'D-2026-10-11')
        self.assertEqual(parse_period('monthly','M-2026-11')[0],'M-2026-11')

    def test_all_10000_keyed_roundtrips_both_modes_and_period_change(self):
        root=bytes(range(32)); start=utc('2026-10-11T14:59:59'); end=utc('2026-10-11T15:00:00')
        mapping=Mapping(root,'daily'); old=mapping.snapshot(start); new=mapping.snapshot(end)
        replica=Mapping(root,'daily').snapshot(start)
        for mode in ['selcal16','selcal32']:
            codes=set()
            changed=0
            for n in range(10000):
                tail=f'{n:04d}'; code=old.to_code(tail,mode)
                validate(code,mode)
                self.assertEqual(old.to_tail(code,mode),tail)
                self.assertEqual(replica.to_code(tail,mode),code)
                codes.add(code); changed += code != new.to_code(tail,mode)
            self.assertEqual(len(codes),10000)
            self.assertGreater(changed,9900)
        for mode, vectors in [('selcal16',['BS-HQ','KR-FJ','CG-JL']), ('selcal32',['AP-Z5','AK-UV','A3-B7'])]:
            self.assertEqual([old.to_code(tail,mode) for tail in ['0000','5501','9999']],vectors)
        with self.assertRaises(ValueError): new.check_expected(old.period_id)
        with self.assertRaises(ValueError): new.check_expected(new.period_id,'wrong-key')

    def test_configuration_fail_closed_and_no_key_in_metadata(self):
        with patch.dict(os.environ,{'HACS_ROTATION':'daily'},clear=True):
            with self.assertRaises(ValueError): configured_mapping()
        with tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'root.key'; key.write_text('ab'*32)
            env={'HACS_ROTATION':'daily','HACS_KEY_FILE':str(key)}
            with patch.dict(os.environ,env,clear=True):
                metadata=json.dumps(configured_mapping().snapshot().metadata())
                self.assertNotIn('ab'*32,metadata)
                key.write_text('bad key')
                with self.assertRaises(ValueError): configured_mapping()
        self.assertEqual(Mapping().snapshot().to_code('5501'),tail_to_selcal('5501'))

    def test_create_key_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'private'/'root.key'
            create_key(key); original=key.read_text()
            self.assertEqual(len(bytes.fromhex(original.strip())),32)
            with self.assertRaises(FileExistsError):create_key(key)
            self.assertEqual(key.read_text(),original)

    def test_shared_store_initializes_once_and_readonly_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keys.sqlite3'
            env={'HACS_ROTATION':'daily','HACS_KEY_STORE':str(path),'HACS_KEY_CREATE':'1'}
            with patch.dict(os.environ,env,clear=True):
                first=configured_mapping().snapshot().metadata()['key_id']
                self.assertEqual(configured_mapping().snapshot().metadata()['key_id'],first)
            with patch.dict(os.environ,{'HACS_ROTATION':'daily','HACS_KEY_STORE':str(path),'HACS_KEY_READONLY':'1'},clear=True):
                self.assertEqual(configured_mapping().snapshot().metadata()['key_id'],first)
            path.write_bytes(b'corrupted database')
            with patch.dict(os.environ,env,clear=True):
                with self.assertRaises(ValueError):configured_mapping()

    def test_readonly_service_waits_for_writer_but_not_for_bad_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keys.sqlite3'
            readonly={'HACS_ROTATION':'daily','HACS_KEY_STORE':str(path),'HACS_KEY_READONLY':'1'}
            now=[0.0]; sleeps=[]
            def sleep(seconds):
                sleeps.append(seconds); now[0]+=seconds
                if len(sleeps)==3:
                    with patch.dict(os.environ,{'HACS_ROTATION':'daily','HACS_KEY_STORE':str(path),'HACS_KEY_CREATE':'1'},clear=True):
                        configured_mapping()
            with patch.dict(os.environ,readonly,clear=True):
                self.assertTrue(wait_for_mapping(timeout=10,sleep=sleep,clock=lambda:now[0]).snapshot().metadata()['rotation_enabled'])
            self.assertEqual(len(sleeps),3)
        with tempfile.TemporaryDirectory() as directory:
            env={'HACS_ROTATION':'daily','HACS_KEY_STORE':str(Path(directory)/'none.sqlite3'),'HACS_KEY_READONLY':'1'}
            now=[0.0]
            with patch.dict(os.environ,env,clear=True):
                with self.assertRaises(KeyStoreNotReady):
                    wait_for_mapping(timeout=2,sleep=lambda s:now.__setitem__(0,now[0]+s),clock=lambda:now[0])
            with patch.dict(os.environ,{**env,'HACS_ROTATION':'hourly'},clear=True):
                calls=[]
                with self.assertRaises(ValueError):
                    wait_for_mapping(timeout=10,sleep=calls.append,clock=lambda:0.0)
                self.assertEqual(calls,[])

    def test_cli_keyed_wav_includes_period_and_key_context(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); secret=folder/'root.key'; output=folder/'call.wav'
            secret.write_text('01'*32)
            environment={'HACS_ROTATION':'daily','HACS_KEY_FILE':str(secret)}
            subprocess.run([sys.executable,str(Path(__file__).with_name('selcal.py')),
                            '--tail','5501','--mode','selcal32','--output',str(output)],
                           env=environment,check=True,capture_output=True)
            context=read_context(output.read_bytes())
            with patch.dict(os.environ,environment,clear=True):
                mapping=configured_mapping().snapshot()
                self.assertEqual(context['key_id'],mapping.metadata()['key_id'])
                self.assertEqual(context['period_id'],mapping.period_id)

    def test_shared_key_rotation_is_persistent_and_revokes_old_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keys.sqlite3'; store=KeyStore(path)
            store.initialize(bytes(range(32)))
            env={'HACS_ROTATION':'daily','HACS_KEY_STORE':str(path)}
            with patch.dict(os.environ,env,clear=True):
                old=configured_mapping().snapshot()
                result=store.rotate(old.metadata()['key_id'],'漏えい対応')
                new=configured_mapping().snapshot()
                self.assertNotEqual(old.metadata()['key_id'],new.metadata()['key_id'])
                self.assertEqual(result['key_generation'],2)
                self.assertEqual(KeyStore(path,True).read()[0],store.read()[0])
                self.assertNotEqual(old.to_code('5501'),new.to_code('5501'))
                with self.assertRaises(ValueError):new.check_expected(old.period_id,old.metadata()['key_id'])
                with self.assertRaises(ValueError):store.rotate(old.metadata()['key_id'],'再実行')
                with self.assertRaises(ValueError):KeyStore(path,True).rotate(result['key_id'],'不正更新')
                self.assertEqual(store.events()[0]['reason'],'漏えい対応')
                self.assertNotIn('root',json.dumps(store.events()))


class PresetTests(unittest.TestCase):
    def test_crud_duplicate_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'presets.sqlite3'; store=Presets(path)
            item=store.save({'name':'航空機0001','tail_number':'0001','mode':'selcal32'})
            self.assertEqual(Presets(path).list()[0]['tail_number'],'0001')
            with self.assertRaises(ValueError):store.save({'name':'別名','tail_number':'0001','mode':'selcal32'})
            store.save({**item,'name':'名称更新','tail_number':'5501','mode':'selcal16'})
            self.assertEqual(Presets(path).list()[0]['name'],'名称更新')
            store.delete(item['id']);self.assertEqual(store.list(),[])
            with self.assertRaises(ValueError):store.delete(item['id'])
            for change in [{'tail_number':'1'}, {'mode':'unknown'}, {'name':''}, {'name':'改\n行'}, {'id':True}]:
                with self.assertRaises(ValueError):store.save({'name':'試験','tail_number':'0000','mode':'selcal16',**change})


class ManagementHTTPTests(unittest.TestCase):
    def test_keyed_audio_preset_and_emergency_rekey(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); secret=folder/'root.key'; token=folder/'admin.token'
            secret.write_text('01'*32);token.write_text('ab'*32)
            env={'HACS_ROTATION':'daily','HACS_KEY_FILE':str(secret),
                 'HACS_KEY_STORE':str(folder/'keys.sqlite3'),'HACS_ADMIN_TOKEN_FILE':str(token)}
            store=Presets(folder/'presets.sqlite3')
            tx_handler=type('TestTx',(TxHandler,),{'presets':store})
            with patch.dict(os.environ,env,clear=True):
                configured_mapping()
                servers=[ThreadingHTTPServer(('127.0.0.1',0),cls) for cls in (tx_handler,RxHandler)]
                threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
                for thread in threads:thread.start()
                tx,rx=[f'http://127.0.0.1:{s.server_port}' for s in servers]
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def get(base,path):
                    with opener.open(base+path) as response:return json.load(response)
                def post(base,path,data,admin=False,origin=None):
                    headers={'Content-Type':'application/json'}
                    if admin:headers['Authorization']='Bearer '+'ab'*32
                    if origin:headers['Origin']=origin
                    with opener.open(urllib.request.Request(base+path,json.dumps(data).encode(),headers)) as response:return json.load(response)
                try:
                    old=get(tx,'/api/rotation')
                    self.assertEqual(get(rx,'/api/rotation')['key_id'],old['key_id'])
                    preset=post(tx,'/api/presets',{'action':'create','name':'試験機','tail_number':'5501','mode':'selcal32'})['preset']
                    self.assertEqual(get(tx,'/api/presets')['presets'][0],preset)
                    with opener.open(tx+'/tone.wav?tail_number=5501&mode=selcal32') as response:
                        audio=response.read()
                        self.assertEqual(response.headers['X-HACS-Period'],old['period_id'])
                    request=urllib.request.Request(rx+'/api/decode?own_tail_number=5501&mode=selcal32',audio)
                    with opener.open(request) as response:self.assertEqual(json.load(response)['status'],'alert')
                    action={'action':'rotate','expected_key_id':old['key_id'],'reason':'漏えい対応'}
                    with self.assertRaises(urllib.error.HTTPError) as exc:post(tx,'/api/keys',action)
                    self.assertEqual(exc.exception.code,401)
                    with self.assertRaises(urllib.error.HTTPError) as exc:post(tx,'/api/keys',action,True,'https://unrelated.invalid')
                    self.assertEqual(exc.exception.code,403)
                    new=post(tx,'/api/keys',action,True)
                    self.assertNotEqual(old['key_id'],new['key_id'])
                    self.assertEqual(get(rx,'/api/rotation')['key_id'],new['key_id'])
                    with self.assertRaises(urllib.error.HTTPError) as exc:opener.open(request)
                    self.assertEqual(exc.exception.code,400)  # old root WAV is revoked.
                    with opener.open(urllib.request.Request(tx+'/api/keys',headers={'Authorization':'Bearer '+'ab'*32})) as response:
                        events=json.load(response)['events']
                    self.assertEqual(events[0]['reason'],'漏えい対応')
                    with self.assertRaises(urllib.error.HTTPError):post(tx,'/api/keys',action,True)
                finally:
                    for server in servers:server.shutdown();server.server_close()
                    for thread in threads:thread.join()
