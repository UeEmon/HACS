import io
import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from tail_mapping import FIRST_PAIRS, _second_pairs, tail_to_selcal, selcal_to_tail, validate_tail
from selcal import validate
from server import Handler as TxHandler
from receiver_server import Handler as RxHandler

class MappingTests(unittest.TestCase):
    def test_all_10000_roundtrip_and_unique(self):
        codes=set()
        for number in range(10000):
            tail=f'{number:04d}'
            code=tail_to_selcal(tail)
            validate(code)
            self.assertEqual(selcal_to_tail(code),tail)
            codes.add(code)
        self.assertEqual(len(codes),10000)

    def test_all_reserved_codes_rejected(self):
        reserved=0
        for first in FIRST_PAIRS:
            for second in _second_pairs(first):
                code=''.join(first)+''.join(second)
                try:
                    selcal_to_tail(code)
                except ValueError:
                    reserved+=1
        self.assertEqual(reserved,920)

    def test_known_vectors_and_strict_input(self):
        for tail,code in [('0000','AB-CD'),('0001','AB-CE'),('5501','EM-DL'),('9999','LS-JR')]:
            self.assertEqual(tail_to_selcal(tail),code)
            self.assertEqual(selcal_to_tail(code),tail)
        for invalid in (1,5501,None,True,'1','12345','-001','５５０１',' 5501','5501\n'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                validate_tail(invalid)
        for invalid in ('AA-BC','BA-CD','AI-CD','AB-AC'):
            with self.assertRaises(ValueError):selcal_to_tail(invalid)

class TailHTTPTests(unittest.TestCase):
    def test_tail_number_to_audio_to_receiver(self):
        servers=[ThreadingHTTPServer(('127.0.0.1',0),cls) for cls in (TxHandler,RxHandler)]
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
        for t in threads:t.start()
        tx,rx=[f'http://127.0.0.1:{s.server_port}' for s in servers]
        try:
            with urllib.request.urlopen(tx+'/api/convert?tail_number=5501') as r:
                self.assertEqual(json.load(r)['selcal_code'],'EM-DL')
            with urllib.request.urlopen(tx+'/api/convert?code=EM-DL') as r:
                self.assertEqual(json.load(r)['tail_number'],'5501')
            with urllib.request.urlopen(tx+'/tone.wav?tail_number=5501') as r:
                audio=r.read()
                self.assertEqual(r.headers['X-HACS-SELCAL-Code'],'EM-DL')
            for tail,status in [('5501','alert'),('0001','other_station')]:
                request=urllib.request.Request(rx+'/api/decode?own_tail_number='+tail,data=audio)
                with urllib.request.urlopen(request) as r:
                    data=json.load(r)
                self.assertEqual(data['status'],status)
                self.assertEqual(data['calls'][0]['tail_number'],'5501')
            for path in ('/api/convert?tail_number=1','/api/convert?code=RS-PQ','/tone.wav?tail_number=5501&code=ABCD'):
                with self.assertRaises(urllib.error.HTTPError) as exc:
                    urllib.request.urlopen(tx+path)
                self.assertEqual(exc.exception.code,400)
        finally:
            for s in servers:s.shutdown();s.server_close()
            for t in threads:t.join()

if __name__=='__main__':unittest.main()
