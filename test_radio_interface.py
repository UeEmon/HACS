import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from radio_dry_run import run
from radio_interface import DryRunAudio, DryRunPTT, RadioInterface, Timing
from selcal import make_wav


class RadioInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wav=make_wav('EM-DL')

    def test_sequence_and_duration_budget(self):
        events=[]
        now=[0.0]
        class Audio(DryRunAudio):
            def wait_complete(self, timeout_seconds):
                now[0]+=2.2
                return super().wait_complete(timeout_seconds)
        def wait(seconds):
            now[0]+=seconds
            events.append({'event':'wait'})
        interface=RadioInterface(Audio(events),DryRunPTT(events),clock=lambda:now[0],sleep=wait)
        result=interface.run(self.wav,'EM-DL')
        self.assertFalse(result['receiver_acknowledged'])
        self.assertEqual([e['event'] for e in events],['audio_prepare','ptt_on_simulated','wait','audio_start','audio_complete_simulated','wait','ptt_off_simulated','audio_stop'])
        self.assertAlmostEqual(now[0],2.7)

    def test_invalid_signal_and_budget_never_key_ptt(self):
        for payload,timing in [(make_wav('AB-CD'),Timing()),(self.wav,Timing(max_ptt_seconds=2.7))]:
            events=[]
            interface=RadioInterface(DryRunAudio(events),DryRunPTT(events),timing,sleep=lambda s:None)
            with self.assertRaises(ValueError):interface.run(payload,'EM-DL')
            self.assertEqual(events,[])
        for value in [True,float('nan'),float('inf'),-1,31]:
            with self.assertRaises(ValueError):Timing(max_ptt_seconds=value)

    def test_start_failure_and_stop_failure_still_release(self):
        events=[]
        class Audio(DryRunAudio):
            def start(self):raise RuntimeError('start failed')
            def stop(self):
                super().stop()
                raise RuntimeError('stop failed')
        interface=RadioInterface(Audio(events),DryRunPTT(events),sleep=lambda s:None)
        with self.assertRaises(RuntimeError):interface.run(self.wav,'EM-DL')
        self.assertEqual(events[-2]['event'],'ptt_off_simulated')
        self.assertFalse(interface._lock.locked())

    def test_activation_failure_still_release(self):
        events=[]
        class PTT(DryRunPTT):
            def activate(self):
                super().activate()
                raise RuntimeError('activation partially failed')
        interface=RadioInterface(DryRunAudio(events),PTT(events),sleep=lambda s:None)
        with self.assertRaises(RuntimeError):interface.run(self.wav,'EM-DL')
        self.assertEqual(events[-2]['event'],'ptt_off_simulated')

    def test_timeout_and_reentrant_attempt(self):
        events=[]
        class Audio(DryRunAudio):
            def wait_complete(self, timeout_seconds):return False
        interface=RadioInterface(Audio(events),DryRunPTT(events),sleep=lambda s:None)
        with self.assertRaises(TimeoutError):interface.run(self.wav,'EM-DL')
        self.assertEqual(events[-2]['event'],'ptt_off_simulated')
        interface._lock.acquire()
        try:
            with self.assertRaises(RuntimeError):interface.run(self.wav,'EM-DL')
        finally:interface._lock.release()

    def test_lead_overrun_refuses_playback_and_releases(self):
        events=[];now=[0.0]
        def delayed_wait(seconds):now[0]+=3.0
        interface=RadioInterface(DryRunAudio(events),DryRunPTT(events),clock=lambda:now[0],sleep=delayed_wait)
        with self.assertRaises(TimeoutError):interface.run(self.wav,'EM-DL')
        self.assertNotIn('audio_start',[e['event'] for e in events])
        self.assertEqual(events[-2]['event'],'ptt_off_simulated')

    def test_epoch_guard_failure_before_playback(self):
        events=[];checks=[]
        def guard():
            checks.append(True)
            if len(checks)==2:raise ValueError('period changed during lead delay')
        interface=RadioInterface(DryRunAudio(events),DryRunPTT(events),sleep=lambda s:None)
        with self.assertRaises(ValueError):interface.run(self.wav,'EM-DL',guard=guard)
        self.assertNotIn('audio_start',[e['event'] for e in events])
        self.assertEqual(events[-2]['event'],'ptt_off_simulated')

    def test_profiles_and_dry_run_both_modes(self):
        profile=json.loads(Path('radio_templates/generic.json').read_text())
        with patch.dict(os.environ,{'HACS_ROTATION':'off'},clear=True):
            for mode,code in [('selcal16','EM-DL'),('selcal32','AT-U7')]:
                result=run(profile,'5501',mode)
                self.assertTrue(result['dry_run'])
                self.assertFalse(result['physical_output'])
                self.assertEqual(result['code'],code)
                self.assertEqual(result['events'][-2]['event'],'ptt_off_simulated')
            with self.assertRaises(ValueError):run({**profile,'backend':'live'},'5501')
