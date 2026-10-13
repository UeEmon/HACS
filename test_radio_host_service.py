import base64
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

from radio_host_service import (BusyError, HostService, create_server, check_devices, parse_job)
from radio_interface import AudioOutput, PTTOutput
from selcal import make_wav

TOKEN = 'ab' * 32
ROT = {'rotation_enabled': False, 'period_id': None, 'key_id': None, 'seconds_until_update': None}


def profile(backend='dry_run', **timing):
    return {'profile_version': 'HACS-RADIO-v1', 'name': 'test', 'backend': backend, 'output_level': 0.5,
            'radio': {'manufacturer': '', 'model': ''},
            'audio_input': {'host_output_device': 'USB Audio', 'channels': 1},
            'ptt': {'method': 'serial_control_line', 'serial_port': '/dev/ttyUSB0', 'control_line': 'rts', 'active_high': True},
            'timing': {'lead_seconds': 0.05, 'tail_seconds': 0.05, 'max_ptt_seconds': 5.0, **timing}}


FOUND = {'audio': {'available': True, 'devices': [{'id': 3, 'name': 'USB Audio', 'output_channels': 2}]},
         'serial': {'available': True, 'ports': [{'device': '/dev/ttyUSB0'}]}}


def job(code='EM-DL', tail='5501', mode='selcal16', **extra):
    return {'job_id': str(uuid.uuid4()), 'tail_number': tail, 'mode': mode, 'code': code,
            'period_id': '', 'key_id': '', 'expires_at': time.time() + 15,
            'wav_base64': base64.b64encode(make_wav(code, 0.5, mode)).decode(), **extra}


class FakeAudio(AudioOutput):
    def __init__(self, log, block=False):
        self.log, self.block, self.stopped = log, block, threading.Event()
    def prepare(self, wav): self.log.append('prepare')
    def start(self): self.log.append('start')
    def wait_complete(self, timeout):
        if self.block:
            self.stopped.wait(timeout)
            return False
        self.log.append('complete'); return True
    def stop(self): self.log.append('stop'); self.stopped.set()


class FakePTT(PTTOutput):
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail
    def activate(self):
        self.log.append('ptt_on')
        if self.fail: raise OSError('port vanished')
    def release(self): self.log.append('ptt_off')


def wait_done(svc, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = svc.get(job_id)
        if j['status'] in ('completed', 'failed', 'cancelled', 'rejected'):
            return j
        time.sleep(0.02)
    raise AssertionError('job did not finish')


def names(j):
    return [e['event'] for e in j['events']]


class ProfileTests(unittest.TestCase):
    def test_apply_validates_and_checks_devices_without_opening(self):
        svc = HostService(TOKEN, devices=lambda: FOUND, rotation=lambda: ROT)
        self.assertEqual(svc.status()['state'], 'unconfigured')
        svc.apply_profile(profile())
        self.assertEqual(svc.status()['state'], 'idle')
        self.assertFalse(svc.status()['physical_output_ready'])
        svc.apply_profile(profile('host_audio_serial'))
        self.assertFalse(svc.status()['physical_output_ready'])  # not allowed at service level
        bad = profile('host_audio_serial'); bad['ptt']['serial_port'] = '/dev/missing'
        with self.assertRaises(ValueError): svc.apply_profile(bad)
        bad = profile('host_audio_serial'); bad['audio_input']['host_output_device'] = 9
        with self.assertRaises(ValueError): svc.apply_profile(bad)
        with self.assertRaises(ValueError): svc.apply_profile({'profile_version': 'x'})
        svc.release_profile()
        self.assertEqual(svc.status()['state'], 'unconfigured')

    def test_check_devices_reports_missing_libraries(self):
        missing = {'audio': {'available': False, 'reason': 'no portaudio'}, 'serial': {'available': True, 'ports': []}}
        with self.assertRaises(ValueError) as cm: check_devices(profile('host_audio_serial'), missing)
        self.assertIn('no portaudio', str(cm.exception))
        dup = {'audio': {'available': True, 'devices': [{'id': 1, 'name': 'USB Audio', 'output_channels': 2}] * 2},
               'serial': FOUND['serial']}
        with self.assertRaises(ValueError): check_devices(profile('host_audio_serial'), dup)


class JobValidationTests(unittest.TestCase):
    def test_parse_job_rejects_bad_inputs(self):
        parse_job(job())
        for change in ({'job_id': 'x'}, {'mode': 'selcal64'}, {'tail_number': '551'}, {'code': 'AB-CD'},
                       {'expires_at': time.time() + 3600}, {'wav_base64': '!!'}, {'period_id': 1}):
            with self.assertRaises(ValueError, msg=change):
                parse_job({**job(), **change})


class RunTests(unittest.TestCase):
    def service(self, allow=False, drivers=None, rotation=None):
        svc = HostService(TOKEN, allow_physical=allow, devices=lambda: FOUND, rotation=rotation or (lambda: ROT),
                          drivers=drivers)
        svc.apply_profile(profile('host_audio_serial' if allow else 'dry_run'))
        return svc

    def test_dry_run_completes_in_real_time_without_physical_output(self):
        svc = self.service()
        start = time.monotonic()
        j, created = svc.submit(job())
        self.assertTrue(created)
        self.assertEqual(j['status'], 'accepted')
        done = wait_done(svc, j['job_id'])
        self.assertEqual(done['status'], 'completed', done)
        self.assertGreaterEqual(time.monotonic() - start, 2.2)
        self.assertFalse(done['physical_output'])
        ev = names(done)
        for a, b in (('guard_ok', 'ptt_on'), ('ptt_on', 'audio_start'), ('audio_start', 'audio_complete'),
                     ('audio_complete', 'ptt_off'), ('ptt_off', 'finished')):
            self.assertLess(ev.index(a), ev.index(b), ev)
        self.assertEqual(ev.count('guard_ok'), 2)
        self.assertFalse(done['receiver_acknowledged'])

    def test_physical_requires_service_permission(self):
        svc = HostService(TOKEN, devices=lambda: FOUND, rotation=lambda: ROT)
        svc.apply_profile(profile('host_audio_serial'))
        with self.assertRaises(ValueError): svc.submit(job())

    def test_physical_driver_sequence(self):
        log = []
        svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log)))
        done = wait_done(svc, svc.submit(job())[0]['job_id'])
        self.assertEqual(done['status'], 'completed', done)
        self.assertTrue(done['physical_output'])
        self.assertEqual(log[:5], ['prepare', 'ptt_on', 'start', 'complete', 'ptt_off'])
        self.assertEqual(log.count('ptt_off'), 1)  # idempotent wrapper

    def test_idempotent_resubmission_and_exclusive_execution(self):
        log = []
        svc = self.service(True, lambda p: (FakeAudio(log, block=True), FakePTT(log)))
        payload = job()
        first, created = svc.submit(payload)
        again, created2 = svc.submit(dict(payload))
        self.assertTrue(created); self.assertFalse(created2)
        self.assertEqual(first['job_id'], again['job_id'])
        with self.assertRaises(BusyError): svc.submit({**payload, 'tail_number': '0001'})
        with self.assertRaises(BusyError): svc.submit(job())
        with self.assertRaises(BusyError): svc.apply_profile(profile())
        with self.assertRaises(BusyError): svc.release_profile()
        svc.cancel(first['job_id'])
        self.assertEqual(wait_done(svc, first['job_id'])['status'], 'cancelled')
        self.assertEqual(log.count('ptt_on'), 1)

    def test_rotation_mismatch_or_unreachable_main_rejects_before_ptt(self):
        for rotation in (lambda: {**ROT, 'key_id': 'other'},
                         lambda: (_ for _ in ()).throw(OSError('down')),
                         lambda: {**ROT, 'seconds_until_update': 1.0}):
            log = []
            svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log)), rotation)
            done = wait_done(svc, svc.submit(job())[0]['job_id'])
            self.assertEqual(done['status'], 'rejected', done)
            self.assertNotIn('ptt_on', log)

    def test_rotation_change_after_lead_releases_ptt(self):
        calls, log = [], []
        def rotation():
            calls.append(1)
            return ROT if len(calls) == 1 else {**ROT, 'period_id': 'D-2026-10-15'}
        svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log)), rotation)
        done = wait_done(svc, svc.submit(job())[0]['job_id'])
        self.assertEqual(done['status'], 'failed')
        self.assertIn('ptt_off', log)
        self.assertNotIn('start', log)

    def test_expired_job_is_rejected(self):
        log = []
        svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log)))
        done = wait_done(svc, svc.submit(job(expires_at=time.time() - 1))[0]['job_id'])
        self.assertEqual(done['status'], 'rejected')
        self.assertEqual(log, [])

    def test_activation_failure_still_releases(self):
        log = []
        svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log, fail=True)))
        done = wait_done(svc, svc.submit(job())[0]['job_id'])
        self.assertEqual(done['status'], 'failed')
        self.assertIn('port vanished', done['error'])
        self.assertIn('ptt_off', log)
        self.assertIn('stop', log)

    def test_cancel_during_audio_releases_immediately(self):
        svc = self.service()
        j = svc.submit(job())[0]
        end = time.time() + 5
        while 'audio_start' not in names(svc.get(j['job_id'])) and time.time() < end:
            time.sleep(0.01)
        t0 = time.monotonic()
        svc.cancel(j['job_id'])
        done = wait_done(svc, j['job_id'])
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(done['status'], 'cancelled')
        ev = names(done)
        self.assertLess(ev.index('cancel_requested'), ev.index('ptt_off'))
        self.assertNotIn('audio_complete', ev)

    def test_cancel_before_ptt_never_keys(self):
        gate, log = threading.Event(), []
        def rotation():
            gate.wait(5)
            return ROT
        svc = self.service(True, lambda p: (FakeAudio(log), FakePTT(log)), rotation)
        j = svc.submit(job())[0]
        time.sleep(0.1)
        svc.cancel(j['job_id'])
        gate.set()
        done = wait_done(svc, j['job_id'])
        self.assertEqual(done['status'], 'cancelled')
        self.assertNotIn('ptt_on', log)


class HttpTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        quiet = patch('radio_host_service.Handler.log_message', lambda *a: None)
        quiet.start(); self.addCleanup(quiet.stop)
        self.svc = HostService(TOKEN, devices=lambda: FOUND, rotation=lambda: ROT)
        self.server = create_server(self.svc, '127.0.0.1', 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()

    def call(self, path, body=None, token=TOKEN, method=None, headers=None):
        h = {'Authorization': f'Bearer {token}', **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.url + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_auth_origin_and_flow(self):
        self.assertEqual(self.call('/v1/status', token='00' * 32)[0], 401)
        self.assertEqual(self.call('/v1/status', headers={'Origin': 'http://localhost:8787'})[0], 403)
        self.assertEqual(self.call('/v1/status')[1]['state'], 'unconfigured')
        self.assertEqual(self.call('/v1/devices')[1], FOUND)
        self.assertEqual(self.call('/v1/jobs', job())[0], 400)  # no profile yet
        self.assertEqual(self.call('/v1/profile', profile())[0], 200)
        status, j = self.call('/v1/jobs', job())
        self.assertEqual(status, 202)
        self.assertEqual(self.call(f'/v1/jobs/{j["job_id"]}/cancel', {})[1]['job_id'], j['job_id'])
        self.assertEqual(wait_done(self.svc, j['job_id'])['status'], 'cancelled')
        self.assertEqual(self.call(f'/v1/jobs/{uuid.uuid4()}')[0], 404)
        self.assertEqual(self.call('/v1/profile', method='DELETE')[0], 200)
        req = urllib.request.Request(self.url + '/v1/profile', data=b'{}', method='POST',
                                     headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'text/plain'})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 415)


if __name__ == '__main__':
    unittest.main()
