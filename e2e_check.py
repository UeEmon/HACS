"""End-to-end check of running HACS services (developer handover section 5).

Runs against already started services; it never controls a radio or PTT.

  python3 e2e_check.py                       # fixed mapping (compose.yaml + emulators)
  python3 e2e_check.py --token-file .secrets/admin.token   # shared-key configuration

The keyed run changes the cadence to weekly, rotates the shared key once and
restores the original cadence. Run it only on a test installation.
Creates one preset named "E2E試験 0001" and deletes it afterwards.

  python3 e2e_check.py --transmit            # also exercise Web → radio host service

--transmit applies the saved radio settings to the host service and sends calls
through it. It refuses to send unless the applied profile is a dry run, so it never
keys a real radio.
"""
import time
import argparse
import io
import json
import sys
import urllib.error
import urllib.request
import wave

results = []


def req(url, data=None, ctype=None, headers=None):
    h = dict(headers or {})
    if ctype:
        h['Content-Type'] = ctype
    r = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def js(url, obj=None, headers=None):
    body = None if obj is None else json.dumps(obj).encode()
    status, raw, _ = req(url, body, None if obj is None else 'application/json', headers)
    try:
        return status, json.loads(raw or b'{}')
    except ValueError:
        return status, {'raw': raw[:200].decode('utf-8', 'replace')}


def check(name, ok, detail=''):
    results.append({'name': name, 'passed': bool(ok), 'detail': str(detail)[:200]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {str(detail)[:160]}' if detail else ''), flush=True)


def silent_wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(bytes(48000 * 2 * 2))
    return out.getvalue()


def status_of(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return (data.get('aircraft') or {}).get('status') or data.get('status')


def common(H, RX, RADIO, AC, keyed):
    for p, url in (('hacs', H), ('receiver', RX), ('radio', RADIO), ('aircraft', AC)):
        s, _, _ = req(url + '/')
        check(f'{p} page responds', s == 200, s)
    s, rot = js(f'{H}/api/rotation')
    check('rotation status', s == 200 and rot.get('rotation_enabled') == keyed, rot)
    for mode in ('selcal16', 'selcal32'):
        s, conv = js(f'{H}/api/convert?tail_number=5501&mode={mode}')
        code = conv.get('selcal_code')
        if not keyed:
            check(f'fixed vector 5501 {mode}', code == {'selcal16': 'EM-DL', 'selcal32': 'AT-U7'}[mode], code)
        s, wav, hdr = req(f'{H}/tone.wav?tail_number=5501&mode={mode}')
        check(f'tone.wav {mode}', s == 200 and hdr.get('X-HACS-SELCAL-Code') == code, hdr.get('X-HACS-SELCAL-Code'))
        s, b, _ = req(f'{H}/api/loopback?tail_number=5501&mode={mode}', wav, 'audio/wav')
        check(f'loopback pass {mode}', s == 200 and json.loads(b).get('passed') is True, b[:120])
        s, b, _ = req(f'{H}/api/loopback?tail_number=0001&mode={mode}', wav, 'audio/wav')
        check(f'loopback mismatch fails {mode}', s == 200 and json.loads(b).get('passed') is False)
    s, _, _ = req(f'{H}/tone.wav?tail_number=5501&level=0.95')
    check('level above 0.9 rejected', s == 400, s)

    s, d = js(f'{H}/api/presets', {'action': 'create', 'name': 'E2E試験 0001', 'tail_number': '0001', 'mode': 'selcal16'})
    pid = (d.get('preset') or {}).get('id')
    existing = s == 400 and '登録済み' in json.dumps(d, ensure_ascii=False)
    check('preset create 0001 (or already registered)', pid is not None or existing, d)
    s, d = js(f'{H}/api/presets/codes')
    check('code list keeps leading zero', s == 200 and '"0001"' in json.dumps(d))
    s, csvb, _ = req(f'{H}/api/presets/export.csv')
    check('CSV keeps leading zero', s == 200 and b',0001,' in csvb)
    s, _ = js(f'{H}/api/presets', {'action': 'delete', 'id': pid}, headers={'Origin': 'http://evil.example'})
    check('cross-origin mutation refused', s == 403, s)
    if pid is not None:
        s, _ = js(f'{H}/api/presets', {'action': 'delete', 'id': pid})
        check('preset cleanup', s == 200, s)

    s, d = js(f'{AC}/api/config', {'tail_number': '5501', 'mode': 'selcal16', 'receive_mode': 'selcal16'})
    check('aircraft own tail 5501', s == 200, d)
    for tail, want in (('5501', 'alert'), ('0001', 'other_station')):
        s, wav, _ = req(f'{RADIO}/api/generate', json.dumps({'tail_number': tail, 'mode': 'selcal16'}).encode(), 'application/json')
        s2, b, _ = req(f'{RADIO}/api/transmit', wav, 'audio/wav')
        check(f'radio→aircraft {tail} → {want}', s == 200 and s2 == 200 and status_of(b) == want, b[:160])
    s, b, _ = req(f'{RADIO}/api/transmit', silent_wav(), 'audio/wav')
    if keyed:
        check('WAV without key context rejected', s == 400, b[:120])
    else:
        check('silent WAV → not_detected', s == 200 and status_of(b) == 'not_detected', b[:160])
    s, wav, _ = req(f'{H}/tone.wav?tail_number=5501')
    s, b, _ = req(f'{AC}/api/input', wav, 'audio/wav')
    check('HACS WAV uploaded to aircraft → alert', s == 200 and status_of(b) == 'alert', b[:160])
    s, b, _ = req(f'{RX}/api/decode?own_tail_number=5501', wav, 'audio/wav')
    check('receiver simulator → alert', s == 200 and status_of(b) == 'alert', b[:160])

    s, d = js(f'{H}/api/radio-settings')
    check('radio settings read', s == 200 and 'revision' in d, d)
    rev, prof = d.get('revision'), d.get('profile')
    s, d2 = js(f'{H}/api/radio-settings', {'profile': prof, 'revision': rev})
    check('radio settings save (no physical output)', s == 200 and d2.get('physical_output') is False, d2)
    s, _ = js(f'{H}/api/radio-settings', {'profile': prof, 'revision': rev})
    check('stale radio settings revision rejected', s == 400, s)
    return rot


def keyed_checks(H, RX, RADIO, AC, token, rot):
    auth = {'Authorization': f'Bearer {token}'}
    for name, url in (('radio', RADIO), ('aircraft', AC)):
        s, st = js(f'{url}/api/status')
        check(f'{name} shares key/period', rot['key_id'] in json.dumps(st) and rot['period_id'] in json.dumps(st))
    s, _ = js(f'{H}/api/keys')
    check('/api/keys without token → 401', s == 401, s)
    s, keys = js(f'{H}/api/keys', headers=auth)
    check('/api/keys with token', s == 200, s)
    check('no secret in key history', token not in json.dumps(keys))

    s, old_wav, _ = req(f'{H}/tone.wav?tail_number=5501')
    original = rot['cadence']
    target = 'weekly' if original != 'weekly' else 'monthly'
    s, d = js(f'{H}/api/security', {'cadence': target, 'expected_revision': rot['security_revision']}, headers=auth)
    check(f'cadence {original} → {target}', s == 200, d)
    s, rot2 = js(f'{H}/api/rotation')
    check('period id changed', rot2.get('period_id') != rot['period_id'], rot2.get('period_id'))
    s, _ = js(f'{H}/api/security', {'cadence': original, 'expected_revision': rot['security_revision']}, headers=auth)
    check('stale security revision rejected', s == 400, s)
    for name, url in (('loopback', f'{H}/api/loopback?tail_number=5501'), ('aircraft', f'{AC}/api/input'),
                      ('receiver', f'{RX}/api/decode?own_tail_number=5501')):
        s, b, _ = req(url, old_wav, 'audio/wav')
        check(f'old-period WAV rejected by {name}', s == 400, b[:120])

    s, pre_wav, _ = req(f'{H}/tone.wav?tail_number=5501')
    s, d = js(f'{H}/api/keys', {'action': 'rotate', 'expected_key_id': rot2['key_id'], 'reason': 'e2e_check'}, headers=auth)
    check('emergency key rotation', s == 200, d)
    s, rot3 = js(f'{H}/api/rotation')
    check('key id changed', rot3.get('key_id') != rot2['key_id'], rot3.get('key_id'))
    s, b, _ = req(f'{AC}/api/input', pre_wav, 'audio/wav')
    check('pre-rotation WAV rejected by aircraft', s == 400, b[:120])
    s, wav, _ = req(f'{RADIO}/api/generate', json.dumps({'tail_number': '5501', 'mode': 'selcal16'}).encode(), 'application/json')
    s, b, _ = req(f'{RADIO}/api/transmit', wav, 'audio/wav')
    check('radio→aircraft alert after rotation', status_of(b) == 'alert', b[:160])
    s, d = js(f'{H}/api/security', {'cadence': original, 'expected_revision': rot3['security_revision']}, headers=auth)
    check(f'cadence restored to {original}', s == 200, d)


def transmit_checks(H, rot):
    def wait(job_id, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            s, j = js(f'{H}/api/transmit/{job_id}')
            if j.get('status') in ('completed', 'failed', 'cancelled', 'rejected', 'submit_failed', 'unknown'):
                return j
            time.sleep(0.2)
        return j
    s, host = js(f'{H}/api/radio-host')
    check('radio host reachable', s == 200 and host.get('reachable'), host.get('state'))
    if not host.get('reachable'):
        return
    s, host = js(f'{H}/api/radio-host/apply', {'action': 'apply'})
    check('apply saved settings to host', s == 200 and host.get('state') == 'idle', host)
    if (host.get('profile') or {}).get('backend') != 'dry_run':
        check('host profile is dry run (refusing to transmit)', False, (host.get('profile') or {}).get('backend'))
        return
    req_body = {'tail_number': '5501', 'mode': 'selcal16', 'period_id': rot.get('period_id') or '',
                'key_id': rot.get('key_id') or '', 'confirm': True}
    s, _ = js(f'{H}/api/transmit', {**req_body, 'confirm': False})
    check('transmit without confirm refused', s == 400, s)
    s, _ = js(f'{H}/api/transmit', req_body, headers={'Origin': 'http://evil.example'})
    check('cross-origin transmit refused', s == 403, s)
    s, job = js(f'{H}/api/transmit', req_body)
    check('transmit accepted', s == 202, job)
    if s != 202:
        return
    s2, _ = js(f'{H}/api/transmit', {**req_body, 'tail_number': '0001'})
    check('second transmit while busy → 409', s2 == 409, s2)
    done = wait(job['job_id'])
    ev = [e['event'] for e in done.get('events', [])]
    check('dry-run transmit completed', done.get('status') == 'completed' and done.get('physical_output') is False, done.get('status'))
    check('event order ptt_on < audio_complete < ptt_off',
          all(x in ev for x in ('ptt_on', 'audio_complete', 'ptt_off')) and
          ev.index('ptt_on') < ev.index('audio_complete') < ev.index('ptt_off'), ev)
    s, job = js(f'{H}/api/transmit', {**req_body, 'mode': 'selcal32'})
    check('selcal32 transmit accepted', s == 202, job)
    if s == 202:
        for _ in range(50):
            if 'ptt_on' in [e['event'] for e in js(f'{H}/api/transmit/{job["job_id"]}')[1].get('events', [])]:
                break
            time.sleep(0.05)
        js(f'{H}/api/transmit/{job["job_id"]}/cancel', {})
        done = wait(job['job_id'])
        check('cancel during transmission', done.get('status') == 'cancelled' and 'ptt_off' in
              [e['event'] for e in done.get('events', [])], done.get('status'))
    s, hist = js(f'{H}/api/transmit/history')
    check('server-side transmit history', s == 200 and len(hist.get('records', [])) >= 2, len(hist.get('records', [])))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--host', default='http://127.0.0.1')
    ap.add_argument('--token-file', help='administrator token for the shared-key configuration')
    ap.add_argument('--json', help='write results to this file')
    ap.add_argument('--transmit', action='store_true', help='also test transmission through a dry-run radio host service')
    args = ap.parse_args()
    H, RX, RADIO, AC = (f'{args.host}:{p}' for p in (8787, 8788, 8789, 8790))
    keyed = bool(args.token_file)
    try:
        rot = common(H, RX, RADIO, AC, keyed)
        if args.transmit:
            transmit_checks(H, js(f'{H}/api/rotation')[1])
        if keyed:
            with open(args.token_file, encoding='ascii') as f:
                keyed_checks(H, RX, RADIO, AC, f.read().strip(), rot)
    except (OSError, urllib.error.URLError) as exc:
        check('services reachable', False, exc)
    failed = [r for r in results if not r['passed']]
    print(f'\n{len(results) - len(failed)}/{len(results)} passed')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=1)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
