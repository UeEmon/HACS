import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from radio_drivers import SoundDeviceAudio, SerialPTT
from radio_host import run
from selcal import make_wav


class CallbackStop(Exception): pass
class CallbackAbort(Exception): pass


class AudioModule:
    CallbackStop=CallbackStop
    CallbackAbort=CallbackAbort
    def query_devices(self):return [{'name':'Test USB','max_output_channels':2}]
    def check_output_settings(self,**kwargs):self.settings=kwargs
    def RawOutputStream(self,**kwargs):
        self.kwargs=kwargs
        self.closed=False
        return SimpleNamespace(start=lambda:None,abort=lambda:None,close=lambda:setattr(self,'closed',True))


class DriverTests(unittest.TestCase):
    def test_pcm_bytes_stereo_padding_and_completion(self):
        module=AudioModule();audio=SoundDeviceAudio('Test USB',2,module)
        wav=make_wav('EM-DL');audio.prepare(wav);audio.start()
        self.assertFalse(audio.wait_complete(0))
        blocks=[]
        for i in range(200):
            block=bytearray(4096*4)
            try:module.kwargs['callback'](block,4096,None,False)
            except CallbackStop:
                blocks.append(bytes(block));break
            blocks.append(bytes(block))
        else:self.fail('Callback did not complete')
        import io,wave
        with wave.open(io.BytesIO(wav)) as source:pcm=source.readframes(source.getnframes())
        expected=b''.join(pcm[i:i+2]*2 for i in range(0,len(pcm),2))
        actual=b''.join(blocks)
        self.assertEqual(actual[:len(expected)],expected)
        self.assertEqual(set(actual[len(expected):]),{0})
        self.assertFalse(audio.wait_complete(0))
        module.kwargs['finished_callback']()
        self.assertTrue(audio.wait_complete(0))
        audio.stop();audio.stop();self.assertTrue(module.closed)

    def test_audio_error_and_ambiguous_selection(self):
        module=AudioModule();audio=SoundDeviceAudio(0,module=module);audio.prepare(make_wav('EM-DL'))
        with self.assertRaises(CallbackAbort):module.kwargs['callback'](bytearray(256),128,None,True)
        with self.assertRaises(RuntimeError):audio.wait_complete(0)
        audio.stop()
        module.query_devices=lambda:[{'name':'Duplicate','max_output_channels':2}]*2
        with self.assertRaises(ValueError):SoundDeviceAudio('Duplicate',module=module).prepare(make_wav('EM-DL'))
        with self.assertRaises(ValueError):SoundDeviceAudio(None)

    def test_serial_polarity_initial_state_and_partial_failure(self):
        for line in ['rts','dtr']:
            for active_high in [True,False]:
                events=[]
                class Serial:
                    def __init__(self,**kwargs):self.is_open=False
                    def __setattr__(self,name,value):
                        if name in ('rts','dtr'):events.append((name,value))
                        object.__setattr__(self,name,value)
                    def open(self):events.append(('open',getattr(self,line)));self.is_open=True
                    def close(self):events.append(('close',getattr(self,line)));self.is_open=False
                driver=SerialPTT('TESTPORT',line,active_high,SimpleNamespace(Serial=Serial))
                driver.activate();driver.release();driver.release()
                self.assertIn(('open',not active_high),events)
                self.assertEqual(events[-2:],[(line,not active_high),('close',not active_high)])
                class FailingSerial(Serial):
                    def open(self):super().open();raise OSError('USB failure')
                failed=SerialPTT('TESTPORT',line,active_high,SimpleNamespace(Serial=FailingSerial))
                with self.assertRaises(OSError):failed.activate()
                failed.release();self.assertEqual(events[-1],('close',not active_high))
        with self.assertRaises(ValueError):SerialPTT('socket://remote','rts',True)

    def test_preview_opens_no_devices_and_execute_selects_drivers(self):
        profile=json.loads(Path('radio_templates/host-audio-serial.json').read_text())
        profile['audio_input']['host_output_device']=0
        profile['ptt'].update(serial_port='TESTPORT',control_line='rts',active_high=True)
        with patch.dict(os.environ,{'HACS_ROTATION':'off'},clear=True):
            with patch('radio_drivers.sounddevice_module',side_effect=AssertionError('No devices in preview')):
                result=run(profile,'5501')
                self.assertFalse(result['physical_output'])
                self.assertEqual(result['status'],'configuration_preview')
            events=[]
            class Audio(SoundDeviceAudio):
                def prepare(self,payload):events.append('prepare')
                def start(self):events.append('start')
                def wait_complete(self,timeout):return True
                def stop(self):events.append('stop')
            class PTT(SerialPTT):
                def activate(self):events.append('on')
                def release(self):events.append('off')
            with patch('radio_host.SoundDeviceAudio',Audio),patch('radio_host.SerialPTT',PTT):
                result=run(profile,'5501','selcal32',execute=True)
                self.assertTrue(result['physical_output'])
                self.assertEqual(events,['prepare','on','start','off','stop'])
