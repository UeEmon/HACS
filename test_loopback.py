import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

from rotation import Mapping
from selcal import make_wav
from server import Handler
from wav_context import attach


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        class TestHandler(Handler):
            def log_message(self, *args): pass
        self.handler=TestHandler
        self.handler.mapping=Mapping()
        self.server=ThreadingHTTPServer(('127.0.0.1',0), TestHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def check(self, payload, mode='selcal16', **extra):
        query=urlencode(dict(tail_number='5501',mode=mode,**extra))
        request=urllib.request.Request(self.base+'/api/loopback?'+query,data=payload,
                                       headers={'Content-Type':'audio/wav'})
        with self.opener.open(request) as response:
            return json.load(response)

    def test_actual_generated_wav_both_modes_and_levels(self):
        for mode in ['selcal16','selcal32']:
            for level in [.01,.5,.9]:
                with self.opener.open(self.base+'/tone.wav?'+urlencode(dict(tail_number='5501',mode=mode,level=level))) as response:
                    wav=response.read()
                result=self.check(wav,mode)
                self.assertTrue(result['passed'])
                self.assertEqual(result['detection']['calls'][0]['code'],result['selcal_code'])
                self.assertEqual(result['detection']['calls'][0]['pulse_seconds'],[1,1])
                self.assertEqual(result['detection']['calls'][0]['gap_seconds'],.2)

    def test_wrong_code_and_silence_fail_not_input_echo(self):
        result=self.check(make_wav('AB-CD'))
        self.assertFalse(result['passed'])
        self.assertEqual(result['detection']['calls'][0]['code'],'AB-CD')
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setparams((1,2,48000,0,'NONE','not compressed'))
            wav.writeframes(b'\0'*(48000*2*2))
        result=self.check(output.getvalue())
        self.assertFalse(result['passed'])
        self.assertEqual(result['detection']['status'],'not_detected')

    def test_keyed_context_and_concurrent_analysis(self):
        self.handler.mapping=Mapping(bytes(range(32)),'daily')
        snapshot=self.handler.mapping.snapshot()
        payload=attach(make_wav(snapshot.to_code('5501','selcal32'),mode='selcal32'), snapshot.metadata())
        self.assertTrue(self.check(payload,'selcal32',period_id=snapshot.period_id,key_id=snapshot.metadata()['key_id'])['passed'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.check(make_wav(snapshot.to_code('5501')))
        self.assertEqual(error.exception.code,400)
        self.handler.mapping=Mapping(b'\xff'*32,'daily')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.check(payload,'selcal32')
        self.assertEqual(error.exception.code,400)
        self.handler.loopback_lock.acquire()
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.check(payload,'selcal32')
            self.assertEqual(error.exception.code,409)
        finally:
            self.handler.loopback_lock.release()
