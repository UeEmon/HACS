import io
import math
import struct
import threading
import unittest
import urllib.request
import urllib.error
import wave
from http.server import ThreadingHTTPServer
from selcal import RATE, TONES, make_wav, validate
from server import Handler

class EncoderTests(unittest.TestCase):
    def test_code_validation(self):
        self.assertEqual(validate(' ac-bd '), 'ACBD')
        for code in ('AA-BC','AB-AC','BA-CD','AB-DC','AI-CD','AB-CDx','AB CD','1234',None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate(code)

    def test_all_16_tones_timing_and_level(self):
        for code in ('ABCD','EFGH','JKLM','PQRS'):
            with wave.open(io.BytesIO(make_wav(code)), 'rb') as w:
                self.assertEqual((w.getframerate(),w.getnchannels(),w.getsampwidth(),w.getnframes()),(48000,1,2,105600))
                raw=w.readframes(w.getnframes())
            samples=struct.unpack('<105600h',raw)
            self.assertTrue(all(s==0 for s in samples[48000:57600]))
            self.assertLessEqual(max(abs(s) for s in samples),16384)
            for pair,start in ((code[:2],0),(code[2:],57600)):
                block=samples[start:start+RATE]
                for char in pair:
                    f=TONES[char]
                    # Independent quadrature projection checks each component's frequency/amplitude.
                    a=2/RATE*sum(s/32767*math.sin(2*math.pi*f*i/RATE) for i,s in enumerate(block))
                    b=2/RATE*sum(s/32767*math.cos(2*math.pi*f*i/RATE) for i,s in enumerate(block))
                    self.assertAlmostEqual(math.hypot(a,b),0.25,delta=0.0075)

    def test_invalid_output_level(self):
        for level in (0,1,float('nan'),float('inf'),True,'0.5'):
            with self.subTest(level=level),self.assertRaises(ValueError):
                make_wav('ABCD',level)

class HTTPTests(unittest.TestCase):
    def test_audio_and_invalid_code(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base+'/tone.wav?code=AC-BD') as r:
                self.assertEqual(r.headers.get_content_type(),'audio/wav')
                self.assertEqual(r.read()[:4],b'RIFF')
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base+'/tone.wav?code=AA-BC')
            self.assertEqual(exc.exception.code,400)
            with urllib.request.urlopen(base+'/') as r:
                self.assertIn(b'HACS',r.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == '__main__':
    unittest.main()
