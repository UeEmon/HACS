import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from key_store import KeyStore
from rotation import configured_mapping
from server import Handler


class SecurityModeTests(unittest.TestCase):
    def test_shared_policy_persistence_and_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'keys.sqlite3'
            env={'HACS_ROTATION':'off','HACS_KEY_STORE':str(path),'HACS_KEY_CREATE':'1'}
            with patch.dict(os.environ,env,clear=True):
                self.assertEqual(configured_mapping().cadence,'off')
                store=KeyStore(path)
                for revision,cadence in enumerate(('daily','weekly','monthly','off')):
                    store.set_policy(cadence,revision)
                    self.assertEqual(configured_mapping().cadence,cadence)
                with self.assertRaises(ValueError):store.set_policy('daily',0)
                with self.assertRaises(ValueError):KeyStore(path,True).set_policy('daily',4)
                self.assertEqual(len(store.policy_events()),4)
            with patch.dict(os.environ,{'HACS_KEY_STORE':str(path),'HACS_KEY_READONLY':'1','HACS_ROTATION':'daily'},clear=True):
                self.assertEqual(configured_mapping().cadence,'off')
                self.assertEqual(configured_mapping().snapshot().metadata()['security_revision'],4)

    def test_authenticated_http_switch_and_old_audio_context(self):
        with tempfile.TemporaryDirectory() as folder:
            token=Path(folder)/'token';token.write_text('ab'*32)
            env={'HACS_ROTATION':'off','HACS_KEY_STORE':str(Path(folder)/'keys.sqlite3'),
                 'HACS_KEY_CREATE':'1','HACS_ADMIN_TOKEN_FILE':str(token)}
            with patch.dict(os.environ,env,clear=True):
                configured_mapping()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                threading.Thread(target=server.serve_forever,daemon=True).start()
                opener=build_opener(ProxyHandler({}))
                def post(cadence,revision,auth=True,origin=None):
                    headers={'Content-Type':'application/json'}
                    if auth:headers['Authorization']='Bearer '+'ab'*32
                    if origin:headers['Origin']=origin
                    req=Request(f'http://127.0.0.1:{server.server_port}/api/security',json.dumps({'cadence':cadence,'expected_revision':revision}).encode(),headers)
                    with opener.open(req) as r:return json.load(r)
                try:
                    with self.assertRaises(HTTPError) as e:post('daily',0,False)
                    self.assertEqual(e.exception.code,401)
                    with self.assertRaises(HTTPError) as e:post('daily',0,origin='https://elsewhere.invalid')
                    self.assertEqual(e.exception.code,403)
                    post('daily',0)
                    previous=configured_mapping().snapshot()
                    post('weekly',1)
                    current=configured_mapping().snapshot()
                    with self.assertRaises(ValueError):current.check_expected(previous.period_id,previous.metadata()['key_id'])
                    with self.assertRaises(HTTPError):post('off',0)
                    self.assertEqual(configured_mapping().cadence,'weekly')
                    post('off',2)
                    self.assertFalse(configured_mapping().snapshot().metadata()['rotation_enabled'])
                finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
