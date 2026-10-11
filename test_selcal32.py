import json
import math
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from itertools import combinations

from selcal import TONES, TONES32, validate, make_wav
from tail_mapping import tail_to_selcal, selcal_to_tail
from receiver import _classify, decode_wav
from server import Handler as TxHandler
from receiver_server import Handler as RxHandler


class ExpandedTests(unittest.TestCase):
    def test_frequency_table_and_code_order(self):
        expected = dict(zip('TUVWXYZ123456789',
            [329.2,365.2,405.0,449.3,498.3,552.7,613.1,680.0,754.2,
             836.6,927.9,1029.2,1141.6,1266.2,1404.4,1557.8]))
        self.assertEqual({c: f for c, f in TONES32.items() if c not in TONES}, expected)
        self.assertEqual(validate('d3-a5', 'selcal32'), 'D3A5')
        for code in ['3D-A5', 'DD-A5', 'D0-A5', 'DI-A5', 'DN-A5', 'DO-A5']:
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate(code, 'selcal32')
        with self.assertRaises(ValueError): validate('D3-A5')
        with self.assertRaises(ValueError): make_wav('AC-BD', mode='invalid')

    def test_all_10000_expanded_mappings(self):
        legacy = {tail_to_selcal(f'{n:04d}') for n in range(10000)}
        expanded = set()
        for n in range(10000):
            tail = f'{n:04d}'
            code = tail_to_selcal(tail, 'selcal32')
            validate(code, 'selcal32')
            self.assertTrue(any(c not in TONES for c in code.replace('-', '')))
            self.assertEqual(selcal_to_tail(code, 'selcal32'), tail)
            expanded.add(code)
        self.assertEqual(len(expanded), 10000)
        self.assertFalse(expanded & legacy)
        for tail, code in [('0000','AB-CT'), ('0001','AB-CU'), ('5501','AT-U7'), ('9999','A5-C7')]:
            self.assertEqual(tail_to_selcal(tail, 'selcal32'), code)
        with self.assertRaises(ValueError): selcal_to_tail('Z1-89', 'selcal32')
        with self.assertRaises(ValueError): selcal_to_tail('AB-CD', 'selcal32')

    def test_all_496_pairs_with_independent_phase_and_clock_error(self):
        # Independent waveform: 44.1 kHz, arbitrary phases, +0.15% frequency.
        rate = 44100
        for first, second in combinations(TONES32, 2):
            block = [.25*(math.sin(2*math.pi*TONES32[first]*1.0015*i/rate+.7)
                          + math.sin(2*math.pi*TONES32[second]*1.0015*i/rate+1.2))
                     for i in range(4410)]
            with self.subTest(pair=first+second):
                self.assertEqual(_classify(block, rate, 'selcal32'), first+second)

    def test_audio_and_backward_compatibility(self):
        for code in ['AB-CT', 'AT-U7', 'A5-C7', 'D3-A5', 'AC-BD']:
            with self.subTest(code=code):
                result = decode_wav(make_wav(code, mode='selcal32'), code, 'selcal32')
                self.assertEqual(result['status'], 'alert')
                self.assertEqual(result['calls'][0]['code'], code)
                self.assertEqual(result['calls'][0]['pulse_seconds'], [1.0,1.0])
                self.assertEqual(result['calls'][0]['gap_seconds'], .2)
        self.assertEqual(decode_wav(make_wav('AC-BD'), 'AC-BD', 'selcal32')['status'], 'alert')
        self.assertEqual(decode_wav(make_wav('AT-U7', mode='selcal32'), 'AC-BD')['status'], 'not_detected')

    def test_expanded_http_and_mixed_receiver(self):
        servers = [ThreadingHTTPServer(('127.0.0.1',0), cls) for cls in (TxHandler,RxHandler)]
        threads = [threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
        for t in threads: t.start()
        tx, rx = [f'http://127.0.0.1:{s.server_port}' for s in servers]
        try:
            for base in (tx, rx):
                with urllib.request.urlopen(base+'/api/convert?tail_number=5501&mode=selcal32') as r:
                    self.assertEqual(json.load(r)['selcal_code'], 'AT-U7')
                with urllib.request.urlopen(base+'/api/convert?code=AT-U7&mode=selcal32') as r:
                    self.assertEqual(json.load(r)['tail_number'], '5501')
            for mode, own_mode, expected in [('selcal32','selcal32','AT-U7'),('selcal16','selcal16','EM-DL')]:
                with urllib.request.urlopen(tx+'/tone.wav?tail_number=5501&mode='+mode) as r:
                    audio = r.read()
                    self.assertEqual(r.headers['X-HACS-Mode'], mode)
                request = urllib.request.Request(rx+'/api/decode?own_tail_number=5501&mode=selcal32&own_mode='+own_mode, data=audio)
                with urllib.request.urlopen(request) as r: data=json.load(r)
                self.assertEqual(data['status'], 'alert')
                self.assertEqual(data['calls'][0]['code'], expected)
                self.assertEqual(data['calls'][0]['tail_number'], '5501')
            for base, path in [(tx,'/tone.wav?code=D3-A5'),(tx,'/api/convert?tail_number=5501&mode=invalid')]:
                with self.assertRaises(urllib.error.HTTPError) as exc: urllib.request.urlopen(base+path)
                self.assertEqual(exc.exception.code, 400)
            request=urllib.request.Request(rx+'/api/decode?own_tail_number=5501&mode=selcal16&own_mode=selcal32',data=audio)
            with self.assertRaises(urllib.error.HTTPError) as exc: urllib.request.urlopen(request)
            self.assertEqual(exc.exception.code, 400)
        finally:
            for s in servers: s.shutdown(); s.server_close()
            for t in threads: t.join()
