"""Legacy 16-tone aviation SELCAL PCM encoder (bench prototype)."""
import io
import math
import re
import struct
import wave

TONES = dict(zip('ABCDEFGHJKLMPQRS', (312.6,346.7,384.6,426.6,473.2,524.8,582.1,645.7,716.1,794.3,881.0,977.2,1083.9,1202.3,1333.5,1479.1)))
RATE = 48000

def validate(code):
    if not isinstance(code, str):
        raise ValueError('コードは文字列で指定してください。')
    code = code.strip().upper()
    if not re.fullmatch(r'[A-HJKLMPQRS]{2}-?[A-HJKLMPQRS]{2}', code):
        raise ValueError('AB-CD形式で指定してください。使用文字: A〜H、J、K、L、M、P、Q、R、S')
    code = code.replace('-', '')
    if len(set(code)) != 4:
        raise ValueError('同じ文字は繰り返せません。')
    if code[0] >= code[1] or code[2] >= code[3]:
        raise ValueError('各組の2文字はアルファベット順にしてください。組の前後は入れ替えません。')
    return code

def make_wav(code, level=0.5):
    code = validate(code)
    if isinstance(level, bool) or not isinstance(level, (float,int)) or not math.isfinite(level) or not 0.01 <= level <= 0.9:
        raise ValueError('出力レベルは0.01〜0.9で指定してください。')
    pcm = bytearray()
    for pair_index in (0, 2):
        f1, f2 = (TONES[c] for c in code[pair_index:pair_index+2])
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
    parser.add_argument('--tail', help='HACS-TN16-v1で変換する4桁の機番号')
    parser.add_argument('--output', default='selcal.wav')
    parser.add_argument('--level', type=float, default=0.5)
    args = parser.parse_args()
    if (args.code is None) == (args.tail is None):
        parser.error('code または --tail のどちらか一方を指定してください。')
    try:
        if args.tail is not None:
            from tail_mapping import tail_to_selcal
            args.code = tail_to_selcal(args.tail)
        Path(args.output).write_bytes(make_wav(args.code, args.level))
    except ValueError as exc:
        parser.error(str(exc))
