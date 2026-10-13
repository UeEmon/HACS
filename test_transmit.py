"""Main server ⇄ radio host service integration (dry run, real HTTP on loopback)."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import uuid

from radio_host_service import HostService, create_server, fetch_rotation
from radio_link import RadioHostClient, TransmitLog
from rotation import Mapping
from server import Handler as TxHandler
from http.server import ThreadingHTTPServer

TOKEN = 'cd' * 32


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_address[1]}'


class TransmitIntegration(unittest.TestCase):
    def setUp(self):
        quiet = [patch('radio_host_service.Handler.log_message', lambda *a: None),
                 patch('server.Handler.log_message', lambda *a: None)]
        for q in quiet:
            q.start(); self.addCleanup(q.stop)
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        token_file = Path(self.dir.name) / 'radio-host.token'
        token_file.write_text(TOKEN + '\n')
        env = patch.dict(os.environ, {'HACS_DATA_DIR': self.dir.name}, clear=False)
        env.start(); self.addCleanup(env.stop)
        self.mapping = Mapping()
        # Main server first (host checks rotation against it), then the host service.
        self.host_box = {}
        handler = type('Tx', (TxHandler,), {
            'mapping': None, 'transmit_log': TransmitLog(Path(self.dir.name) / 'transmit.sqlite3')})
        handler.snapshot = lambda h: self.mapping.snapshot()
        handler.host = lambda h: self.host_box['client']
        self.main = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.main_url = serve(self.main)
        self.svc = HostService(TOKEN, self.main_url, rotation=lambda: fetch_rotation(self.main_url))
        self.hostsrv = create_server(self.svc, '127.0.0.1', 0)
        self.host_url = serve(self.hostsrv)
        self.host_box['client'] = RadioHostClient(self.host_url, str(token_file))
        self.addCleanup(lambda: [s.shutdown() or s.server_close() for s in (self.main, self.hostsrv)])

    def call(self, path, body=None, headers=None):
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode(); h['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.main_url + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    def wait(self, job_id, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            s, j = self.call(f'/api/transmit/{job_id}')
            if j['status'] in ('completed', 'failed', 'cancelled', 'rejected', 'submit_failed', 'unknown'):
                return j
            time.sleep(0.1)
        raise AssertionError('no terminal state')

    def request(self, **extra):
        return {'tail_number': '5501', 'mode': 'selcal16', 'period_id': '', 'key_id': '', 'confirm': True, **extra}

    def test_not_configured_and_unreachable(self):
        self.host_box['client'] = RadioHostClient('', '')
        self.assertEqual(self.call('/api/radio-host')[1]['state'], 'not_configured')
        self.host_box['client'] = RadioHostClient('http://127.0.0.1:9', str(Path(self.dir.name) / 'radio-host.token'))
        self.assertEqual(self.call('/api/radio-host')[1]['state'], 'unreachable')
        self.assertEqual(self.call('/api/transmit', self.request())[0], 502)

    def test_full_dry_run_transmit_with_history(self):
        self.assertEqual(self.call('/api/radio-host')[1]['state'], 'unconfigured')
        self.assertEqual(self.call('/api/transmit', self.request())[0], 400)  # nothing applied yet
        s, host = self.call('/api/radio-host/apply', {'action': 'apply'})
        self.assertEqual((s, host['state']), (200, 'idle'))
        self.assertEqual(host['profile']['backend'], 'dry_run')
        for bad in (self.request(confirm=False), self.request(period_id=None), self.request(tail_number='55'),
                    self.request(period_id='D-2099-01-01')):
            self.assertEqual(self.call('/api/transmit', bad)[0], 400, bad)
        self.assertEqual(self.call('/api/transmit', self.request(), {'Origin': 'http://evil.example'})[0], 403)
        s, job = self.call('/api/transmit', self.request())
        self.assertEqual(s, 202)
        self.assertEqual(job['code'], 'EM-DL')
        self.assertFalse(job['physical_output'])
        s, _ = self.call('/api/transmit', self.request(tail_number='0001'))
        self.assertEqual(s, 409)  # one transmission at a time
        done = self.wait(job['job_id'])
        self.assertEqual(done['status'], 'completed', done)
        ev = [e['event'] for e in done['events']]
        self.assertLess(ev.index('ptt_on'), ev.index('audio_complete'))
        self.assertLess(ev.index('audio_complete'), ev.index('ptt_off'))
        hist = self.call('/api/transmit/history')[1]['records']
        self.assertEqual(hist[0]['job_id'], job['job_id'])
        self.assertEqual(hist[0]['status'], 'completed')
        self.assertNotIn('wav', json.dumps(hist).lower().replace('wav_', ''))
        self.assertEqual(self.call('/api/radio-host/apply', {'action': 'release'})[1]['state'], 'unconfigured')

    def test_cancel_and_lost_job(self):
        self.call('/api/radio-host/apply', {'action': 'apply'})
        s, job = self.call('/api/transmit', self.request())
        end = time.time() + 5
        while 'ptt_on' not in [e['event'] for e in self.call(f'/api/transmit/{job["job_id"]}')[1]['events']]:
            self.assertLess(time.time(), end); time.sleep(0.05)
        s, j = self.call(f'/api/transmit/{job["job_id"]}/cancel', {})
        self.assertEqual(s, 200)
        self.assertEqual(self.wait(job['job_id'])['status'], 'cancelled')
        # Host forgets jobs on restart: the main server must not claim success.
        s, job2 = self.call('/api/transmit', self.request())
        self.svc.jobs.clear()
        self.assertEqual(self.wait(job2['job_id'])['status'], 'unknown')
        self.assertEqual(self.call(f'/api/transmit/{uuid.uuid4()}')[0], 404)

    def test_key_rotation_between_request_and_keying_is_refused(self):
        self.mapping = Mapping(bytes(range(32)), 'daily')
        snap = self.mapping.snapshot().metadata()
        self.call('/api/radio-host/apply', {'action': 'apply'})
        gate = threading.Event()
        original = self.svc.rotation
        def slow_rotation():
            gate.wait(5)
            return original()
        self.svc.rotation = slow_rotation
        s, job = self.call('/api/transmit', self.request(period_id=snap['period_id'], key_id=snap['key_id']))
        self.assertEqual(s, 202, job)
        self.mapping = Mapping(bytes(range(1, 33)), 'daily')  # emergency key change
        gate.set()
        done = self.wait(job['job_id'])
        self.assertEqual(done['status'], 'rejected', done)
        self.assertNotIn('ptt_on', [e['event'] for e in done['events']])


class TransmitLogTests(unittest.TestCase):
    def test_terminal_status_is_final_and_retention(self):
        with tempfile.TemporaryDirectory() as d:
            log = TransmitLog(Path(d) / 't.sqlite3')
            jid = str(uuid.uuid4())
            log.create({'job_id': jid, 'status': 'requested', 'tail_number': '0001'})
            log.update(jid, status='completed')
            self.assertEqual(log.update(jid, status='running')['status'], 'completed')
            self.assertEqual(log.get(jid)['tail_number'], '0001')
            with patch('radio_link.KEEP_RECORDS', 3):
                for _ in range(5):
                    log.create({'job_id': str(uuid.uuid4()), 'status': 'completed'})
                self.assertEqual(len(log.list()), 3)


if __name__ == '__main__':
    unittest.main()
