"""16/32-tone aviation SELCAL PCM encoder (bench prototype)."""
import io
import math
import re
import struct
import wave

TONES = dict(zip('ABCDEFGHJKLMPQRS', (312.6,346.7,384.6,426.6,473.2,524.8,582.1,645.7,716.1,794.3,881.0,977.2,1083.9,1202.3,1333.5,1479.1)))
TONES32 = {**TONES, **dict(zip('TUVWXYZ123456789', (329.2,365.2,405.0,449.3,498.3,552.7,613.1,680.0,754.2,836.6,927.9,1029.2,1141.6,1266.2,1404.4,1557.8)))}
RATE = 48000

def tones_for(mode='selcal16'):
    if mode not in ('selcal16', 'selcal32'):
        raise ValueError('方式はselcal16またはselcal32で指定してください。')
    return TONES if mode == 'selcal16' else TONES32

def validate(code, mode='selcal16'):
    tones = tones_for(mode)
    if not isinstance(code, str):
        raise ValueError('コードは文字列で指定してください。')
    code = code.strip().upper()
    alphabet = ''.join(tones)
    if not re.fullmatch(f'[{alphabet}]{{2}}-?[{alphabet}]{{2}}', code):
        raise ValueError('AB-CD形式で指定してください。使用文字: '+alphabet)
    code = code.replace('-', '')
    if len(set(code)) != 4:
        raise ValueError('同じ文字は繰り返せません。')
    rank = {char: i for i, char in enumerate(alphabet)}
    if rank[code[0]] >= rank[code[1]] or rank[code[2]] >= rank[code[3]]:
        raise ValueError('各組は英字→数字の文字順位順にしてください。組の前後は入れ替えません。')
    return code

def make_wav(code, level=0.5, mode='selcal16'):
    code = validate(code, mode)
    tones = tones_for(mode)
    if isinstance(level, bool) or not isinstance(level, (float,int)) or not math.isfinite(level) or not 0.01 <= level <= 0.9:
        raise ValueError('出力レベルは0.01〜0.9で指定してください。')
    pcm = bytearray()
    for pair_index in (0, 2):
        f1, f2 = (tones[c] for c in code[pair_index:pair_index+2])
        for i in range(RATE):
            # Equal-amplitude components; combined peak never exceeds level.
            sample = level * 0.5 * (math.sin(2*math.pi*f1*i/RATE) + math.sin(2*math.pi*f2*i/RATE))
            pcm.extend(struct.pack('<h', round(sample * 32767)))
        if pair_index == 0:
            pcm.extend(bytes(round(RATE * 0.2) * 2))
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)
    return out.getvalue()

if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='航空SELCAL WAV生成')
    parser.add_argument('code', nargs='?', help='SELCALコード（従来の直接指定）')
    parser.add_argument('--tail', help='選択方式で変換する4桁の呼び出し相手先')
    parser.add_argument('--mode', choices=['selcal16','selcal32'], default='selcal16')
    parser.add_argument('--output', default='selcal.wav')
    parser.add_argument('--level', type=float, default=0.5)
    args = parser.parse_args()
    if (args.code is None) == (args.tail is None):
        parser.error('code または --tail のどちらか一方を指定してください。')
    try:
        mapping = None
        if args.tail is not None:
            from rotation import configured_mapping
            mapping = configured_mapping().snapshot()
            args.code = mapping.to_code(args.tail, args.mode)
        body = make_wav(args.code, args.level, args.mode)
        if mapping is not None and mapping.period_id:
            from wav_context import attach
            body = attach(body, mapping.metadata())
        Path(args.output).write_bytes(body)
    except ValueError as exc:
        parser.error(str(exc))
