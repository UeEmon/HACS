import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

import radio_calibration as cal
from radio_host import run as host_run, validate_profile
from radio_settings import validate as validate_settings
from selcal import make_wav, TONES

TEMPLATES = Path(__file__).with_name('radio_templates')


def samples(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 48000)
        raw = w.readframes(w.getnframes())
    return [v / 32767 for v in struct.unpack(f'<{len(raw) // 2}h', raw)]


def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values))


def tone_amplitude(values, frequency):
    re = sum(v * math.cos(2 * math.pi * frequency * i / 48000) for i, v in enumerate(values))
    im = sum(v * math.sin(2 * math.pi * frequency * i / 48000) for i, v in enumerate(values))
    return 2 * math.hypot(re, im) / len(values)


class SignalFigureTests(unittest.TestCase):
    def test_figures_match_generated_call(self):
        for level in (0.1, 0.5, 0.9):
            fig = cal.signal_figures(level)
            call = samples(make_wav('EM-DL', level))[:48000]  # first tone pair, 1.0 s
            self.assertAlmostEqual(rms(call), fig['rms_fs'], delta=0.002)
            self.assertLessEqual(max(abs(v) for v in call), fig['peak_fs'] + 1e-4)
            self.assertAlmostEqual(fig['rms_dbfs_sine_ref'], 20 * math.log10(level) - 3.01, delta=0.01)
        for bad in (0, 0.95, float('nan'), True, '0.5'):
            with self.assertRaises(ValueError):
                cal.signal_figures(bad)


class CalibrationWavTests(unittest.TestCase):
    def test_pair_and_sine_have_call_rms(self):
        call = rms(samples(make_wav('AB-CD', 0.4))[:48000])
        pair = samples(cal.calibration_wav(0.4, 2, 'pair', pair='AB'))
        sine = samples(cal.calibration_wav(0.4, 2, 'sine', frequency=1000))
        self.assertEqual(len(pair), 96000)
        middle = slice(4800, 91200)  # exclude fades
        self.assertAlmostEqual(rms(pair[middle]), call, delta=0.002)
        self.assertAlmostEqual(rms(sine[middle]), call, delta=0.002)
        self.assertLess(abs(pair[0]), 1e-3)
        self.assertLess(abs(pair[-1]), 1e-3)

    def test_pair_components_are_equal_and_mode_aware(self):
        block = samples(cal.calibration_wav(0.5, 1, 'pair', pair='AS'))[9600:9600 + 4800]
        a, s = tone_amplitude(block, TONES['A']), tone_amplitude(block, TONES['S'])
        self.assertAlmostEqual(a, 0.25, delta=0.01)
        self.assertAlmostEqual(s, 0.25, delta=0.01)
        cal.calibration_wav(0.5, 1, 'pair', mode='selcal32', pair='T9')
        for kwargs in ({'pair': 'T9'}, {'pair': 'AA'}, {'pair': 'A'}, {'signal': 'noise'},
                       {'seconds': 0.5}, {'seconds': 31}, {'signal': 'sine', 'frequency': 50}):
            with self.assertRaises(ValueError, msg=kwargs):
                cal.calibration_wav(**{'level': 0.5, 'seconds': 1, **kwargs})


class PlanTests(unittest.TestCase):
    def test_linear_recommendation(self):
        r = cal.plan(0.5, 0.5, 0.3, 1.0)
        self.assertEqual(r['status'], 'ok')
        self.assertAlmostEqual(r['recommended_level'], 0.3)
        self.assertAlmostEqual(r['target_peak_v'], 0.6)

    def test_pad_change_when_outside_digital_range(self):
        too_quiet = cal.plan(0.2, 0.5, 0.775, 1.55)
        self.assertEqual(too_quiet['status'], 'adjust_pad')
        self.assertLess(too_quiet['pad_change_db'], 0)  # remove attenuation
        self.assertAlmostEqual(0.5 * 0.775 / 0.2 * 10 ** (too_quiet['pad_change_db'] / 20), 0.5, places=2)
        too_loud = cal.plan(0.9, 0.5, 0.03, 0.1)
        self.assertGreater(too_loud['pad_change_db'], 20)
        self.assertNotIn('recommended_level', too_loud)

    def test_target_above_rated_maximum_is_refused(self):
        r = cal.plan(0.5, 0.5, 0.8, 1.0)  # 1.6 V two-tone peak > 1.414 V
        self.assertEqual(r['status'], 'target_exceeds_maximum')
        self.assertNotIn('recommended_level', r)
        for args in ((0, 0.5, 0.3), (0.5, 0.5, -1), (0.5, 1.2, 0.3), (0.5, 0.5, 0.3, 0)):
            with self.assertRaises(ValueError):
                cal.plan(*args)


class StandardTemplateTests(unittest.TestCase):
    def load(self, name):
        return json.loads((TEMPLATES / name).read_text(encoding='utf-8'))

    def test_templates_are_consistent_with_standard(self):
        for name, cls in (('standard-analog-line.json', 'L'), ('standard-analog-mic.json', 'M')):
            profile = self.load(name)
            std, audio, ptt = profile['standard'], profile['audio_input'], profile['ptt']
            self.assertEqual((std['id'], std['class'], std['values_basis']), ('HACS-STD-ANALOG-v1', cls, 'standard_reference'))
            # Two-tone peak at the nominal level stays below the sine peak of the maximum.
            self.assertLess(cal.CREST_FACTOR * audio['nominal_input_vrms'], math.sqrt(2) * audio['maximum_input_vrms'])
            low, high = audio['passband_hz']
            self.assertLessEqual(low, min(TONES.values()))
            self.assertGreaterEqual(high, 1557.8)  # highest SELCAL 32 tone
            self.assertIsNone(audio['host_output_device'])  # never guess the host device
            self.assertIsNone(ptt['serial_port'])
            self.assertEqual(cal.plan(audio['nominal_input_vrms'], 0.5, audio['nominal_input_vrms'],
                                      audio['maximum_input_vrms'])['recommended_level'], 0.5)

    def test_filled_template_passes_host_and_web_validation_without_output(self):
        for name in ('standard-analog-line.json', 'standard-analog-mic.json'):
            profile = self.load(name)
            with self.assertRaises(ValueError):
                validate_profile(profile)  # device and port must be chosen explicitly
            profile['audio_input']['host_output_device'] = 'USB Audio CODEC'
            profile['ptt']['serial_port'] = '/dev/cu.usbserial-TEST'
            validate_profile(profile)
            validate_settings(profile)
            with patch.dict('os.environ', {}, clear=True):
                preview = host_run(profile, '5501')
            self.assertEqual(preview['status'], 'configuration_preview')
            self.assertFalse(preview['physical_output'])
            self.assertEqual(preview['output_level'], 0.5)


class CliTests(unittest.TestCase):
    def test_wav_and_plan_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'cal.wav'
            with patch('builtins.print'):
                self.assertEqual(cal.main(['wav', '--output', str(out), '--seconds', '1']), 0)
                self.assertEqual(cal.main(['plan', '--measured-vrms', '0.5', '--at-level', '0.5',
                                           '--profile', str(TEMPLATES / 'standard-analog-line.json')]), 0)
                self.assertEqual(cal.main(['plan', '--measured-vrms', '0.5', '--at-level', '0.5']), 1)
            self.assertEqual(len(samples(out.read_bytes())), 48000)

    def test_play_uses_explicit_device_and_never_touches_ptt(self):
        from test_radio_drivers import AudioModule
        module = AudioModule()
        import radio_drivers
        original = radio_drivers.sounddevice_module
        radio_drivers.sounddevice_module = lambda: module
        try:
            with patch('radio_drivers.SoundDeviceAudio.wait_complete', return_value=True), \
                 patch('radio_drivers.SerialPTT.activate', side_effect=AssertionError('PTT must not be used')), \
                 patch('builtins.print') as printed:
                self.assertEqual(cal.main(['play', '--device', 'Test USB', '--seconds', '1']), 0)
            self.assertEqual(module.kwargs['samplerate'], 48000)
            self.assertTrue(module.closed)
            self.assertFalse(json.loads(printed.call_args[0][0])['ptt_operated'])
        finally:
            radio_drivers.sounddevice_module = original


if __name__ == '__main__':
    unittest.main()
