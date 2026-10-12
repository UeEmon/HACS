"""Host driver CLI: preview by default; --execute performs audio and PTT output."""
import argparse
import json
from pathlib import Path

from radio_drivers import SoundDeviceAudio, SerialPTT, sounddevice_module
from radio_interface import RadioInterface, Timing
from rotation import configured_mapping
from selcal import make_wav


def validate_profile(profile):
    if not isinstance(profile,dict) or profile.get('profile_version')!='HACS-RADIO-v1' or profile.get('backend')!='host_audio_serial':
        raise ValueError('host_audio_serialプロファイルが必要です。')
    audio=profile.get('audio_input',{})
    ptt=profile.get('ptt',{})
    if not isinstance(audio,dict) or not isinstance(ptt,dict):
        raise ValueError('音声とPTTの設定が必要です。')
    if ptt.get('method')!='serial_control_line':
        raise ValueError('PTT方式はserial_control_lineです。')
    output=SoundDeviceAudio(audio.get('host_output_device'),audio.get('channels',1))
    switch=SerialPTT(ptt.get('serial_port'),ptt.get('control_line'),ptt.get('active_high'))
    timing=profile.get('timing')
    if not isinstance(timing,dict) or set(timing)!={'lead_seconds','tail_seconds','max_ptt_seconds'}:
        raise ValueError('前後待ち時間とPTT上限が必要です。')
    return output,switch,Timing(**timing)


def run(profile, tail, mode='selcal16', level=None, execute=False):
    audio,ptt,timing=validate_profile(profile)
    snapshot=configured_mapping().snapshot()
    code=snapshot.to_code(tail,mode)
    level=profile.get('output_level',0.5) if level is None else level
    payload=make_wav(code,level,mode)
    if timing.lead_seconds+2.2+timing.tail_seconds>=timing.max_ptt_seconds:
        raise ValueError('PTT上限が信号長と前後待ち時間より短すぎます。')
    summary={**snapshot.describe(tail,mode),'audio_device':audio.device,'audio_channels':audio.channels,'output_level':level,
             'serial_port':ptt.port,'ptt_line':ptt.line,'ptt_active_high':ptt.active_high,
             'receiver_acknowledged':False}
    if not execute:
        return {**summary,'status':'configuration_preview','physical_output':False}
    def guard():
        current=configured_mapping().snapshot()
        current.check_expected(snapshot.period_id or '',snapshot.metadata()['key_id'] or '')
        remaining=current.metadata()['seconds_until_update']
        if remaining is not None and remaining<=timing.lead_seconds+2.2+timing.tail_seconds+0.5:
            raise ValueError('期間切替直前です。更新後に再実行してください。')
    result=RadioInterface(audio,ptt,timing).run(payload,code,mode,guard)
    return {**summary,**result,'physical_output':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='ホスト音声・シリアルPTT（既定は設定確認のみ）')
    parser.add_argument('--list-audio',action='store_true')
    parser.add_argument('--profile')
    parser.add_argument('--tail')
    parser.add_argument('--mode',choices=['selcal16','selcal32'],default='selcal16')
    parser.add_argument('--level',type=float,default=None,help='出力レベル（省略時はプロファイル値、未設定なら0.5）')
    parser.add_argument('--execute',action='store_true',help='実音声出力とPTT操作を実行')
    args=parser.parse_args()
    try:
        if args.list_audio:
            if args.execute:parser.error('--list-audioと--executeは同時指定できません。')
            sd=sounddevice_module()
            print(json.dumps([{'id':i,'name':item['name'],'output_channels':item['max_output_channels']}
                              for i,item in enumerate(sd.query_devices()) if item['max_output_channels']>0],ensure_ascii=False,indent=2))
        else:
            if not args.profile or not args.tail:parser.error('--profileと--tailが必要です。')
            profile=json.loads(Path(args.profile).read_text(encoding='utf-8'))
            print(json.dumps(run(profile,args.tail,args.mode,args.level,args.execute),ensure_ascii=False,indent=2))
    except KeyboardInterrupt:
        parser.exit(130,'操作を中断しました。\n')
    except Exception as exc:
        parser.exit(1,str(exc)+'\n')
