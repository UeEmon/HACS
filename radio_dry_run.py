"""Exercise the generic audio/PTT template without audio or electrical output."""
import argparse
import json
from pathlib import Path

from radio_interface import DryRunAudio, DryRunPTT, RadioInterface, Timing
from rotation import configured_mapping
from selcal import make_wav


def run(profile, tail, mode='selcal16', level=None):
    if not isinstance(profile, dict) or profile.get('profile_version') != 'HACS-RADIO-v1':
        raise ValueError('プロファイル形式が不正です。')
    if profile.get('backend') != 'dry_run':
        raise ValueError('このテンプレートの実行機能はdry_run専用です。')
    timing = profile.get('timing')
    if not isinstance(timing, dict) or set(timing) != {'lead_seconds','tail_seconds','max_ptt_seconds'}:
        raise ValueError('前後待ち時間とPTT上限を指定してください。')
    snapshot = configured_mapping().snapshot()
    code = snapshot.to_code(tail, mode)
    level = profile.get('output_level',0.5) if level is None else level
    payload = make_wav(code, level, mode)
    events = []
    def guard():
        configured_mapping().snapshot().check_expected(snapshot.period_id or '',snapshot.metadata()['key_id'] or '')
    def simulated_wait(seconds):
        events.append({'event':'wait_simulated', 'seconds':seconds})
    interface = RadioInterface(DryRunAudio(events), DryRunPTT(events), Timing(**timing), sleep=simulated_wait)
    result = interface.run(payload, code, mode, guard)
    return {**result, **snapshot.describe(tail, mode), 'dry_run':True,
            'physical_output':False, 'events':events}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='音声入力・PTT汎用テンプレートのドライラン（実出力なし）')
    parser.add_argument('--profile',default=str(Path(__file__).parent/'radio_templates/generic.json'))
    parser.add_argument('--tail',required=True)
    parser.add_argument('--mode',choices=['selcal16','selcal32'],default='selcal16')
    parser.add_argument('--level',type=float,default=None,help='出力レベル（省略時はプロファイル値、未設定なら0.5）')
    args = parser.parse_args()
    try:
        profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
        print(json.dumps(run(profile,args.tail,args.mode,args.level),ensure_ascii=False,indent=2))
    except (OSError,ValueError,TypeError,RuntimeError) as exc:
        parser.exit(1,str(exc)+'\n')
