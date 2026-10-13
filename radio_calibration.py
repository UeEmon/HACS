"""Level calibration for HACS-STD-ANALOG-v1 analog radio interfaces.

SPDX-License-Identifier: Apache-2.0
Never operates PTT. Playback goes only to an explicitly named host device.

Signal relationship (HACS make_wav): each tone has amplitude level/2 of full scale,
so the two-tone RMS is level/2 FS, the peak is level FS and the crest factor is 2
(6.02 dB). Relative to a full-scale sine (0 dBFS) the RMS is 20*log10(level)-3.01 dB.
"""
import argparse
import io
import json
import math
from pathlib import Path
import struct
import wave

from selcal import RATE, tones_for

MAX_SECONDS = 30
PREFERRED_LEVEL = 0.5   # leaves 6 dB of digital adjustment above and below
MIN_RESOLVED_LEVEL = 0.05
CREST_FACTOR = 2.0


def _check_level(level):
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level) or not 0.01 <= level <= 0.9:
        raise ValueError('出力レベルは0.01〜0.9で指定してください。')
    return float(level)


def signal_figures(level):
    """Digital figures of the HACS call signal at a given output level."""
    level = _check_level(level)
    rms = level / 2
    return {'output_level': level, 'rms_fs': rms, 'peak_fs': level, 'crest_factor': CREST_FACTOR,
            # RMS (level/2) divided by full-scale sine RMS (1/sqrt 2) = level/sqrt 2.
            'rms_dbfs_sine_ref': round(20 * math.log10(level / math.sqrt(2)), 2)}


def calibration_wav(level=0.5, seconds=10.0, signal='pair', mode='selcal16', pair='AB', frequency=1000.0):
    """Continuous calibration signal with the same RMS as a HACS call at `level`.

    signal='pair' sustains two tones of the chosen mode (same spectrum/crest factor as a call);
    signal='sine' is one sine of equal RMS for meters that dislike two-tone beating.
    A 10 ms raised-cosine fade avoids clicks at the start and end.
    """
    level = _check_level(level)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 1 <= seconds <= MAX_SECONDS:
        raise ValueError(f'校正信号の長さは1〜{MAX_SECONDS}秒で指定してください。')
    if signal == 'pair':
        tones = tones_for(mode)
        if not isinstance(pair, str) or len(pair) != 2 or pair[0] == pair[1] or any(c not in tones for c in pair.upper()):
            raise ValueError('校正用の音対は選択方式の異なる2文字で指定してください（例: AB）。')
        components = [(tones[c], level / 2) for c in pair.upper()]
    elif signal == 'sine':
        if isinstance(frequency, bool) or not isinstance(frequency, (int, float)) or not 100 <= frequency <= 3000:
            raise ValueError('正弦波の周波数は100〜3000 Hzで指定してください。')
        components = [(float(frequency), level / math.sqrt(2))]  # RMS level/2, same as the two-tone call
    else:
        raise ValueError('校正信号はpairまたはsineです。')
    frames = round(RATE * seconds)
    fade = round(RATE * 0.01)
    pcm = bytearray()
    for i in range(frames):
        gain = 1.0
        edge = min(i, frames - 1 - i)
        if edge < fade:
            gain = 0.5 - 0.5 * math.cos(math.pi * edge / fade)
        sample = gain * sum(a * math.sin(2 * math.pi * f * i / RATE) for f, a in components)
        pcm.extend(struct.pack('<h', round(sample * 32767)))
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(bytes(pcm))
    return out.getvalue()


def plan(measured_vrms, measured_level, target_vrms, maximum_vrms=None):
    """Recommend an output level (or a pad change) from one RMS measurement.

    The measurement must be taken at the radio audio input, with the interface unit
    connected and the radio in receive (PTT off), while a calibration signal plays.
    Analog gain is assumed linear and unchanged (same OS volume, pad and radio gain).
    """
    for name, value in (('measured_vrms', measured_vrms), ('target_vrms', target_vrms)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name}は正の電圧（Vrms）で指定してください。')
    measured_level = _check_level(measured_level)
    result = {'measured_vrms': measured_vrms, 'measured_level': measured_level, 'target_vrms': target_vrms,
              'target_peak_v': round(target_vrms * CREST_FACTOR, 6), 'status': 'ok', 'warnings': []}
    if maximum_vrms is not None:
        if isinstance(maximum_vrms, bool) or not isinstance(maximum_vrms, (int, float)) or not math.isfinite(maximum_vrms) or maximum_vrms <= 0:
            raise ValueError('maximum_vrmsは正の電圧（Vrms）で指定してください。')
        # Two-tone peak (2 x RMS) must stay below the sine peak of the rated maximum.
        allowed_peak = maximum_vrms * math.sqrt(2)
        result['maximum_peak_v'] = round(allowed_peak, 6)
        if target_vrms * CREST_FACTOR > allowed_peak:
            result['status'] = 'target_exceeds_maximum'
            result['warnings'].append('目標電圧の2音ピークが無線機の最大入力を超えます。目標値を見直してください。')
            return result
    ideal = measured_level * target_vrms / measured_vrms
    result['ideal_level'] = round(ideal, 4)
    if 0.01 <= ideal <= 0.9 and ideal >= MIN_RESOLVED_LEVEL:
        result['recommended_level'] = round(ideal, 3)
        if ideal > 0.8:
            result['warnings'].append('推奨レベルが上限0.9に近いため、減衰器を約6 dB減らす余地を確保してください。')
        return result
    # Out of the usable digital range: move the analog gain so the level lands near 0.5.
    change_db = 20 * math.log10(PREFERRED_LEVEL / ideal)
    result['status'] = 'adjust_pad'
    result['pad_change_db'] = round(change_db, 2)
    result['recommended_level_after_pad'] = PREFERRED_LEVEL
    if change_db > 0:
        result['warnings'].append(f'減衰器を{change_db:.1f} dB増やす（またはOS音量を下げる）と、出力レベル0.5で目標電圧になります。')
    else:
        result['warnings'].append(f'減衰器を{-change_db:.1f} dB減らす（またはOS音量を上げる）と、出力レベル0.5で目標電圧になります。')
    return result


def _profile_targets(path):
    profile = json.loads(Path(path).read_text(encoding='utf-8'))
    audio = profile.get('audio_input') if isinstance(profile, dict) else None
    if not isinstance(audio, dict):
        raise ValueError('プロファイルにaudio_inputがありません。')
    return audio.get('nominal_input_vrms'), audio.get('maximum_input_vrms'), profile.get('output_level', 0.5), audio


def main(argv=None):
    p = argparse.ArgumentParser(description='標準アナログ無線機インターフェースのレベル校正（PTTは操作しません）')
    sub = p.add_subparsers(dest='command', required=True)
    sig = argparse.ArgumentParser(add_help=False)
    sig.add_argument('--level', type=float, default=0.5)
    sig.add_argument('--seconds', type=float, default=10.0)
    sig.add_argument('--signal', choices=['pair', 'sine'], default='pair')
    sig.add_argument('--mode', choices=['selcal16', 'selcal32'], default='selcal16')
    sig.add_argument('--pair', default='AB', help='pair信号の2文字（例: AB は312.6 Hz＋346.7 Hz）')
    sig.add_argument('--frequency', type=float, default=1000.0, help='sine信号の周波数')
    w = sub.add_parser('wav', parents=[sig], help='校正信号WAVを書き出す')
    w.add_argument('--output', required=True)
    pl = sub.add_parser('play', parents=[sig], help='校正信号を指定デバイスへ出力する（PTTは操作しない）')
    pl.add_argument('--device', required=True, help='radio_host.py --list-audio のIDまたは完全一致の名前')
    pl.add_argument('--channels', type=int, choices=[1, 2], default=1)
    pn = sub.add_parser('plan', help='測定値から出力レベルまたは減衰量を算出する')
    pn.add_argument('--measured-vrms', type=float, required=True, help='無線機音声入力で測定したRMS電圧')
    pn.add_argument('--at-level', type=float, required=True, help='測定時の出力レベル（0.01〜0.9）')
    pn.add_argument('--target-vrms', type=float, help='目標RMS電圧（省略時はプロファイルのnominal_input_vrms）')
    pn.add_argument('--maximum-vrms', type=float, help='無線機の最大入力Vrms（省略時はプロファイル値）')
    pn.add_argument('--profile', help='標準プロファイルJSON')
    fg = sub.add_parser('figures', help='出力レベルに対するデジタル振幅を表示する')
    fg.add_argument('--level', type=float, default=0.5)
    args = p.parse_args(argv)
    try:
        if args.command == 'wav':
            data = calibration_wav(args.level, args.seconds, args.signal, args.mode, args.pair, args.frequency)
            Path(args.output).write_bytes(data)
            out = {'written': args.output, 'bytes': len(data), **signal_figures(args.level), 'ptt_operated': False}
        elif args.command == 'play':
            from radio_drivers import SoundDeviceAudio
            device = int(args.device) if args.device.isdigit() else args.device
            data = calibration_wav(args.level, args.seconds, args.signal, args.mode, args.pair, args.frequency)
            audio = SoundDeviceAudio(device, args.channels)
            try:
                audio.prepare(data)
                audio.start()
                if not audio.wait_complete(args.seconds + 5):
                    raise TimeoutError('校正信号の出力が完了しませんでした。')
            finally:
                audio.stop()
            out = {'played_on': args.device, 'seconds': args.seconds, **signal_figures(args.level), 'ptt_operated': False}
        elif args.command == 'plan':
            target, maximum, audio = args.target_vrms, args.maximum_vrms, None
            if args.profile:
                p_target, p_max, _, audio = _profile_targets(args.profile)
                target = target if target is not None else p_target
                maximum = maximum if maximum is not None else p_max
            if target is None:
                raise ValueError('--target-vrms またはnominal_input_vrmsを含むプロファイルが必要です。')
            out = plan(args.measured_vrms, args.at_level, target, maximum)
        else:
            out = signal_figures(args.level)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
