import io
import json
import math
import random
import struct
import threading
import unittest
import urllib.request
import urllib.error
import wave
from http.server import ThreadingHTTPServer
from receiver import decode_wav
from receiver_server import Handler
from selcal import make_wav

def pcm_wav(samples,rate=48000):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setparams((1,2,rate,0,'NONE','not compressed'))
        w.writeframes(b''.join(struct.pack('<h',max(-32768,min(32767,round(x*32767)))) for x in samples))
    return out.getvalue()

class ReceiverTests(unittest.TestCase):
    def test_all_tones_and_own_station(self):
        for code in ('ABCD','EFGH','JKLM','PQRS'):
            with self.subTest(code=code):
                result=decode_wav(make_wav(code),code)
                self.assertEqual(result['status'],'alert')
                self.assertEqual(result['calls'][0]['code'],code[:2]+'-'+code[2:])
                self.assertEqual(result['calls'][0]['pulse_seconds'],[1.0,1.0])
                self.assertEqual(result['calls'][0]['gap_seconds'],.2)

    def test_other_station(self):
        result=decode_wav(make_wav('ACBD'),'ABCD')
        self.assertEqual(result['status'],'other_station')
        self.assertFalse(result['calls'][0]['matched'])

    def test_silence_and_noise_are_not_calls(self):
        rng=random.Random(42)
        for samples in ([0]*105600,[rng.uniform(-.1,.1) for _ in range(105600)]):
            self.assertEqual(decode_wav(pcm_wav(samples),'ABCD')['status'],'not_detected')

    def test_independent_44100_signal_with_frequency_error(self):
        rate=44100
        def pair(f,g):
            return [.15*(math.sin(2*math.pi*f*1.001*i/rate)+math.sin(2*math.pi*g*1.001*i/rate)) for i in range(rate)]
        samples=pair(312.6,384.6)+[0]*8820+pair(346.7,426.6)
        self.assertEqual(decode_wav(pcm_wav(samples,rate),'ACBD')['status'],'alert')

    def test_bad_gap_and_single_tone(self):
        with wave.open(io.BytesIO(make_wav('ABCD')),'rb') as w:
            raw=w.readframes(w.getnframes())
        samples=[s/32768 for s in struct.unpack('<105600h',raw)]
        bad_gap=samples[:48000]+[0]*24000+samples[57600:]
        single=[.25*math.sin(2*math.pi*312.6*i/48000) for i in range(105600)]
        for data in (pcm_wav(bad_gap),pcm_wav(single)):
            self.assertEqual(decode_wav(data,'ABCD')['status'],'not_detected')

    def test_bad_wav_and_code(self):
        for payload,code in ((b'not wav','ABCD'),(make_wav('ABCD'),'AABC'),(make_wav('ABCD')[:-100],'ABCD')):
            with self.assertRaises(ValueError):
                decode_wav(payload,code)

class ReceiverHTTPTests(unittest.TestCase):
    def test_file_upload_and_result(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            request=urllib.request.Request(base+'/api/decode?own_code=AC-BD',data=make_wav('ACBD'),headers={'Content-Type':'audio/wav'})
            with urllib.request.urlopen(request) as r:
                self.assertEqual(json.load(r)['status'],'alert')
            with urllib.request.urlopen(base+'/') as r:
                self.assertIn(b'HACS',r.read())
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(urllib.request.Request(base+'/api/decode?own_code=ABCD',data=b'bad'))
            self.assertEqual(exc.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':
    unittest.main()
