"""Independent reference checks against the cited ASRI/SLCAA publications.

These tests inspect digital PCM only; they are not RF or hardware certification.
"""
import io
import math
import struct
import unittest
import wave
from selcal import TONES, make_wav
from tail_mapping import tail_to_selcal

# ASRI How SELCAL Works; SLCAA Part 10C (Feb 2024), Table 3-1.
REFERENCE = {'A':312.6,'B':346.7,'C':384.6,'D':426.6,
             'E':473.2,'F':524.8,'G':582.1,'H':645.7,
             'J':716.1,'K':794.3,'L':881.0,'M':977.2,
             'P':1083.9,'Q':1202.3,'R':1333.5,'S':1479.1}

class SELCALReferenceTests(unittest.TestCase):
    def test_reference_frequency_table(self):
        self.assertEqual(TONES,REFERENCE)

    def test_all_tail_codes_against_independent_asri_rules(self):
        for number in range(10000):
            raw=tail_to_selcal(f'{number:04d}')
            self.assertEqual(len(raw),5)
            self.assertEqual(raw[2],'-')
            chars=raw.replace('-','')
            self.assertTrue(all(c in REFERENCE for c in chars))
            self.assertEqual(len(set(chars)),4)
            self.assertLess(chars[0],chars[1])
            self.assertLess(chars[2],chars[3])

    def test_pcm_reference_timing_and_two_tone_sequence(self):
        # Reference frequencies are independent of the application's TONES table.
        for code in ('ABCD','EFGH','JKLM','PQRS'):
            for level in (0.01,0.5,0.9):
                with self.subTest(code=code,level=level):
                    with wave.open(io.BytesIO(make_wav(code,level)),'rb') as wav:
                        self.assertEqual((wav.getframerate(),wav.getnchannels(),wav.getsampwidth()),(48000,1,2))
                        self.assertEqual(wav.getnframes(),105600)
                        samples=struct.unpack('<105600h',wav.readframes(105600))
                    self.assertTrue(all(s==0 for s in samples[48000:57600]))
                    for pair,start in ((code[:2],0),(code[2:],57600)):
                        a,b=[REFERENCE[c] for c in pair]
                        max_error=0.0
                        for i,s in enumerate(samples[start:start+48000]):
                            expected=32767*level/2*(math.sin(2*math.pi*a*i/48000)+math.sin(2*math.pi*b*i/48000))
                            max_error=max(max_error,abs(s-expected))
                        # Each component is equal-level and nominal-frequency;
                        # the saved waveform differs only by rounding to PCM16.
                        self.assertLessEqual(max_error,0.500001)
                    self.assertLessEqual(max(abs(s) for s in samples),math.ceil(32767*level))

if __name__=='__main__':unittest.main()
