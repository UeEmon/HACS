"""Web transmit requests: build a verified WAV and hand it to the radio host service.

SPDX-License-Identifier: Apache-2.0
The main server stays the authority for codes, keys and history; the host service
only plays what it receives and re-checks the period/key before and after keying.
"""
import base64
import re
import time
import uuid

from radio_link import HostUnavailable, TERMINAL
from receiver import decode_wav
from selcal import make_wav, validate as validate_code
from tail_mapping import validate_tail
from wav_context import attach

SIGNAL_SECONDS = 2.2
JOB_LIFETIME = 15.0
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class Conflict(Exception):
    pass


def host_state(client):
    if not client.configured:
        return {'configured': False, 'reachable': False, 'state': 'not_configured'}
    try:
        status, data = client.request('GET', '/v1/status')
    except HostUnavailable as exc:
        return {'configured': True, 'reachable': False, 'state': 'unreachable', 'error': str(exc)}
    if status != 200:
        return {'configured': True, 'reachable': False, 'state': 'unreachable', 'error': data.get('error')}
    return {'configured': True, 'reachable': True, **data}


def apply_profile(client, profile, action):
    if action == 'apply':
        status, data = client.request('POST', '/v1/profile', profile)
    elif action == 'release':
        status, data = client.request('DELETE', '/v1/profile')
    else:
        raise ValueError('actionはapplyまたはreleaseです。')
    if status == 409:
        raise Conflict(data.get('error', '送信中です。'))
    if status != 200:
        raise ValueError(data.get('error', 'ホストへの設定適用に失敗しました。'))
    return {'configured': True, 'reachable': True, **data}


def create(snapshot, client, log, data):
    """Validate, build the WAV, record the request and submit it to the host."""
    if not isinstance(data, dict) or data.get('confirm') is not True:
        raise ValueError('送信の確認（confirm: true）が必要です。')
    mode = data.get('mode', 'selcal16')
    if mode not in ('selcal16', 'selcal32'):
        raise ValueError('方式はselcal16またはselcal32です。')
    tail = validate_tail(data.get('tail_number'))
    if not isinstance(data.get('period_id'), str) or not isinstance(data.get('key_id'), str):
        raise ValueError('画面に表示中の期間・鍵識別子（鍵なしは空文字）が必要です。')
    snapshot.check_expected(data['period_id'], data['key_id'])
    host = host_state(client)
    if not host['reachable']:
        raise HostUnavailable(host.get('error') or '無線機ホストサービスが設定されていません。')
    stale = log.active()
    if stale:  # e.g. the browser closed while polling; take the host's word for it
        refresh(client, log, stale['job_id'])
    if host['state'] == 'busy' or log.active():
        raise Conflict('送信中です。完了後に再試行してください。')
    if host['state'] != 'idle' or not host.get('profile'):
        raise ValueError('ホストに無線機設定が適用されていません。「ホストへ設定を適用」を実行してください。')
    profile = host['profile']
    if profile['backend'] == 'host_audio_serial' and not host.get('physical_output_ready'):
        raise ValueError('ホストサービスは実出力が許可されていません。')
    timing = profile['timing']
    meta = snapshot.metadata()
    needed = timing['lead_seconds'] + SIGNAL_SECONDS + timing['tail_seconds'] + JOB_LIFETIME + 1
    if meta['seconds_until_update'] is not None and meta['seconds_until_update'] <= needed:
        raise ValueError('期間切替の直前です。更新後に再実行してください。')
    level = profile.get('output_level', 0.5)
    raw_code = validate_code(snapshot.to_code(tail, mode), mode)  # 'EMDL'
    code = raw_code[:2] + '-' + raw_code[2:]
    wav = make_wav(raw_code, level, mode)
    if snapshot.period_id:
        wav = attach(wav, meta)
    detection = decode_wav(wav, raw_code, mode)
    if len(detection['calls']) != 1 or not detection['calls'][0]['matched']:
        raise ValueError('生成音声の内部確認で期待コードを検出できませんでした。')
    job_id = str(uuid.uuid4())
    record = log.create({'job_id': job_id, 'tail_number': tail, 'mode': mode, 'code': code,
                         'period_id': meta['period_id'] or '', 'key_id': meta['key_id'] or '',
                         'output_level': level, 'backend': profile['backend'],
                         'physical_output': profile['backend'] == 'host_audio_serial', 'status': 'requested'})
    payload = {'job_id': job_id, 'tail_number': tail, 'mode': mode, 'code': code,
               'period_id': meta['period_id'] or '', 'key_id': meta['key_id'] or '',
               'expires_at': time.time() + JOB_LIFETIME, 'wav_base64': base64.b64encode(wav).decode()}
    try:
        status, result = client.request('POST', '/v1/jobs', payload)
    except HostUnavailable as exc:
        return log.update(job_id, status='submit_failed', error=str(exc))
    if status not in (200, 202):
        return log.update(job_id, status='submit_failed', error=result.get('error', f'HTTP {status}'))
    return log.update(job_id, status=result['status'], events=result.get('events'),
                      physical_output=result.get('physical_output'), backend=result.get('backend'))


def refresh(client, log, job_id):
    """Fetch the host's view of a job and store it. Unknown if the host cannot answer."""
    if not UUID_RE.fullmatch(job_id):
        raise KeyError('送信記録が見つかりません。')
    record = log.get(job_id)
    if record['status'] in TERMINAL:
        return {**record, 'host_reachable': None}
    try:
        status, result = client.request('GET', f'/v1/jobs/{job_id}')
    except HostUnavailable as exc:
        return {**log.update(job_id, status='unknown', error=str(exc)), 'host_reachable': False}
    if status == 404:
        # The host restarted or dropped the job; the outcome cannot be confirmed.
        return {**log.update(job_id, status='unknown', error='ホストサービスにジョブがありません（再起動の可能性）。'),
                'host_reachable': True}
    if status != 200:
        return {**record, 'host_reachable': False}
    return {**log.update(job_id, status=result['status'], error=result.get('error'), events=result.get('events')),
            'host_reachable': True}


def cancel(client, log, job_id):
    if not UUID_RE.fullmatch(job_id):
        raise KeyError('送信記録が見つかりません。')
    log.get(job_id)
    status, result = client.request('POST', f'/v1/jobs/{job_id}/cancel', {})
    if status == 404:
        raise KeyError('ホストサービスにジョブがありません。')
    return refresh(client, log, job_id)
