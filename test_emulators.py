import json
import threading
import unittest
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

from emulator_server import Emulator, create_server
from rotation import Mapping
from selcal import make_wav
from wav_context import attach


class EmulatorsTest(unittest.TestCase):
    def setUp(self):
        self.aircraft = Emulator('aircraft', Mapping())
        self.rx = create_server('127.0.0.1', 0, self.aircraft)
        self.radio = Emulator('radio', Mapping(), 'http://127.0.0.1:'+str(self.rx.server_port), sleep=lambda _:None)
        self.tx = create_server('127.0.0.1', 0, self.radio)
        for server in (self.rx, self.tx):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        for server in (self.tx, self.rx):
            server.shutdown(); server.server_close()

    def request(self, server, path, data=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        request = Request('http://127.0.0.1:'+str(server.server_port)+path, data)
        with self.opener.open(request, timeout=10) as response:
            body = response.read()
            return body if response.headers['Content-Type']=='audio/wav' else json.loads(body)

    def test_http_two_modes_and_other_station(self):
        for mode in ('selcal16', 'selcal32'):
            self.request(self.rx, '/api/config', {'tail_number':'5501','mode':mode,'receive_mode':'selcal32'})
            for tail, expected in [('5501','alert'), ('0000','other_station')]:
                wav = self.request(self.tx, '/api/generate', {'tail_number':tail,'mode':mode})
                result = self.request(self.tx, '/api/transmit', wav)
                self.assertEqual(result['aircraft']['status'], expected)
                self.assertFalse(self.radio.ptt)
                self.assertEqual(self.aircraft.last['status'], expected)
        states = [e['state'] for e in self.radio.events]
        self.assertEqual(states[-6:], ['ptt_lead','transmitting','ptt_tail','idle','delivering','idle'])

    def test_bad_wave_config_and_busy(self):
        for server,path,data in [(self.tx,'/api/transmit',b'bad'),
                (self.rx,'/api/config',{'tail_number':'5501','mode':'selcal32','receive_mode':'selcal16'})]:
            with self.assertRaises(HTTPError) as e:
                self.request(server,path,data)
            self.assertEqual(e.exception.code,400)
        self.radio.lock.acquire()
        try:
            with self.assertRaises(HTTPError) as e:
                self.request(self.tx,'/api/transmit',b'bad')
            self.assertEqual(e.exception.code,409)
        finally:
            self.radio.lock.release()
        self.assertFalse(self.radio.ptt)

    def test_delivery_failure_releases_ptt(self):
        self.radio.aircraft_url='http://127.0.0.1:'+str(self.tx.server_port)
        wave=make_wav('EMDL')
        with self.assertRaises(ValueError):
            self.radio.process(wave)
        self.assertFalse(self.radio.ptt)
        self.assertEqual(self.radio.state,'idle')
        self.assertEqual(self.radio.last['status'],'delivery_failed')

    def test_keys_missing_context_and_stale_result(self):
        mapping=Mapping(bytes(range(32)), 'daily')
        self.radio.mapping=self.aircraft.mapping=mapping
        snap=mapping.snapshot()
        wave=make_wav(snap.to_code('5501','selcal32'),mode='selcal32')
        self.aircraft.configure({'tail_number':'5501','mode':'selcal32','receive_mode':'selcal32'})
        with self.assertRaises(ValueError):
            self.aircraft.process(wave)
        wave=attach(wave,snap.metadata())
        self.assertEqual(self.radio.process(wave)['aircraft']['status'],'alert')
        self.aircraft.mapping=Mapping(b'x'*32,'daily')
        self.assertTrue(self.aircraft.status()['last_stale'])
        with self.assertRaises(ValueError):
            self.aircraft.process(wave)

    def test_silence_and_ptt_exception(self):
        wave=bytearray(make_wav('EMDL'))
        wave[44:]=b'\0'*(len(wave)-44)
        self.assertEqual(self.radio.process(bytes(wave))['aircraft']['status'],'not_detected')
        def fail(_):
            raise OSError('simulated failure')
        self.radio.sleep=fail
        with self.assertRaises(OSError):
            self.radio.process(make_wav('EMDL'))
        self.assertFalse(self.radio.ptt)
        self.assertEqual(self.radio.state,'idle')

if __name__=='__main__':
    unittest.main()
