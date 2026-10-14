import csv
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from preset_exports import build_list, csv_bytes
from presets import Presets
from rotation import Mapping
from server import Handler


class PresetExportTests(unittest.TestCase):
    def test_snapshot_modes_metadata_and_formula_escaping(self):
        now = datetime(2026, 10, 11, 14, 59, 59, tzinfo=timezone.utc)
        snapshot = Mapping(bytes(range(32)), 'daily').snapshot(now)
        presets = [dict(id=1, name='航空機,一号', tail_number='0000', mode='selcal16'),
                   dict(id=2, name=' =HYPERLINK("x")', tail_number='5501', mode='selcal32')]
        result = build_list(presets, snapshot)
        self.assertEqual([r['selcal_code'] for r in result['presets']], ['BS-HQ', 'AK-UV'])
        for row in result['presets']:
            self.assertEqual(row['period_id'], 'D-2026-10-11')
            self.assertEqual(row['key_id'], result['key_id'])
            self.assertEqual(row['server_time_jst'], result['server_time_jst'])
        payload = csv_bytes(result)
        self.assertTrue(payload.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(payload.decode('utf-8-sig'))))
        self.assertEqual(rows[1][0:4], ['航空機,一号', '0000', 'selcal16', 'BS-HQ'])
        self.assertEqual(rows[2][0], '\' =HYPERLINK("x")')
        self.assertNotIn(bytes(range(32)).hex(), payload.decode('utf-8-sig'))
        other = build_list(presets, Mapping(b'\xff'*32, 'daily').snapshot(now))
        self.assertNotEqual(result['key_id'], other['key_id'])
        self.assertNotEqual(result['presets'][0]['selcal_code'], other['presets'][0]['selcal_code'])
        self.assertEqual(len(list(csv.reader(io.StringIO(csv_bytes(build_list([],snapshot)).decode('utf-8-sig'))))), 1)

    def test_http_export_and_expected_key_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            presets=Presets(directory+'/presets.sqlite3')
            presets.save(dict(name='先頭ゼロ', tail_number='0000', mode='selcal16'))
            presets.save(dict(name='32音', tail_number='9999', mode='selcal32'))
            class TestHandler(Handler):
                def log_message(self, *args): pass
            TestHandler.presets=presets
            TestHandler.mapping=Mapping(bytes(range(32)), 'daily')
            server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
            thread=threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with opener.open(base+'/api/presets/codes') as response:
                    data=json.load(response)
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertEqual(len(data['presets']),2)
                with opener.open(base+'/api/presets/export.csv') as response:
                    rows=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
                    self.assertIn('attachment;', response.headers['Content-Disposition'])
                    self.assertEqual(response.headers['X-HACS-Key-ID'],data['key_id'])
                self.assertEqual({r['呼び出し相手先']:r['呼び出しコード'] for r in rows},
                                 {r['tail_number']:r['selcal_code'] for r in data['presets']})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(base+'/api/presets/export.csv?key_id=revoked')
                self.assertEqual(error.exception.code,400)
            finally:
                server.shutdown();server.server_close();thread.join()
