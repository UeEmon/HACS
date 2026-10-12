import tempfile
from pathlib import Path
import unittest
from radio_settings import RadioSettings, default_profile, validate
from radio_host import run

class RadioSettingsTests(unittest.TestCase):
    def test_persistent_revision_and_invalid_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RadioSettings(Path(folder)/'radio.sqlite3')
            profile=store.read()['profile'];profile['output_level']=.25
            self.assertEqual(store.save(profile,0)['revision'],1)
            self.assertEqual(RadioSettings(store.filename).read()['profile']['output_level'],.25)
            with self.assertRaises(ValueError):store.save(profile,0)
            for value in (0,.91,float('nan'),True):
                with self.assertRaises(ValueError):validate({**profile,'output_level':value})
            profile['timing']['max_ptt_seconds']=2
            with self.assertRaises(ValueError):store.save(profile,1)

    def test_exported_host_profile_level_and_override(self):
        p=default_profile();p['backend']='host_audio_serial'
        with self.assertRaises(ValueError):validate(p)
        p['audio_input']['host_output_device']=2;p['ptt']['serial_port']='COM3';p['output_level']=.2
        validate(p)
        self.assertEqual(run(p,'5501')['output_level'],.2)
        self.assertEqual(run(p,'5501',level=.4)['output_level'],.4)
        self.assertFalse(run(p,'5501')['physical_output'])

if __name__=='__main__':unittest.main()
