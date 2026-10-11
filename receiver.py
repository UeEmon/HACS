"""Bench SELCAL detector: estimates the two tone pairs from PCM, not a filename."""
import array
import io
import math
import sys
import wave
from selcal import TONES, validate, tones_for

MAX_BYTES = 2_000_000

def _classify(block, rate, mode='selcal16'):
    energy = sum(x*x for x in block) / len(block)
    if math.sqrt(energy) < 0.002:
        return 'silence'
    amplitudes = []
    tones = tones_for(mode)
    rank = {char: i for i, char in enumerate(tones)}
    # Hann window for the narrower spacing of the added tones; normalize gain.
    if mode == 'selcal32':
        weights = [0.5 - 0.5 * math.cos(2 * math.pi * i / (len(block)-1)) for i in range(len(block))]
        normalizer = sum(weights)
        block = [sample * weight for sample, weight in zip(block, weights)]
    else:
        normalizer = len(block)
    # Goertzel evaluation at each actual SELCAL frequency, independent of FFT bins.
    for char, frequency in tones.items():
        omega = 2 * math.pi * frequency / rate
        coeff = 2 * math.cos(omega)
        previous = before = 0.0
        for sample in block:
            current = sample + coeff * previous - before
            before, previous = previous, current
        power = max(0, previous*previous + before*before - coeff*previous*before)
        amplitudes.append((2 * math.sqrt(power) / normalizer, char))
    amplitudes.sort(reverse=True)
    a, b, c = (p[0] for p in amplitudes[:3])
    explained = (a*a + b*b) / (2 * energy)
    if b < 0.003 or b / a < 0.6 or c / b > 0.35 or explained < 0.65:
        return 'unknown'
    return ''.join(sorted([amplitudes[0][1], amplitudes[1][1]], key=rank.__getitem__))

def decode_wav(payload, own_code, mode='selcal16'):
    own_code = validate(own_code, mode)
    if len(payload) > MAX_BYTES:
        raise ValueError('WAVは2 MB以下にしてください。')
    try:
        with wave.open(io.BytesIO(payload), 'rb') as wav:
            channels, width, rate, count = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            if channels != 1 or width != 2 or not 8000 <= rate <= 96000 or wav.getcomptype() != 'NONE':
                raise ValueError('8〜96 kHz、16 bit、monoの非圧縮PCM WAVが必要です。')
            if not 0.3 <= count / rate <= 10:
                raise ValueError('音声長は0.3〜10秒にしてください。')
            raw = wav.readframes(count)
            if len(raw) != count * 2:
                raise ValueError('WAVの音声データが途中で切れています。')
    except (wave.Error, EOFError) as exc:
        raise ValueError('有効なPCM WAVを読み込めませんでした。') from exc
    samples = array.array('h', raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    samples = [x / 32768 for x in samples]
    step = round(rate * 0.1)
    segments = []
    for offset in range(0, len(samples), step):
        block = samples[offset:offset+step]
        if len(block) < step * 0.75:
            break
        label = _classify(block, rate, mode)
        duration = len(block) / rate
        if segments and segments[-1]['label'] == label:
            segments[-1]['duration_seconds'] += duration
        else:
            segments.append({'label':label, 'start_seconds':offset/rate, 'duration_seconds':duration})
    calls = []
    for first, gap, second in zip(segments, segments[1:], segments[2:]):
        if len(first['label']) != 2 or gap['label'] != 'silence' or len(second['label']) != 2:
            continue
        if not (0.75 <= first['duration_seconds'] <= 1.250001 and 0.75 <= second['duration_seconds'] <= 1.250001 and 0.099999 <= gap['duration_seconds'] <= 0.300001):
            continue
        try:
            code = validate(first['label'] + second['label'], mode)
        except ValueError:
            continue
        calls.append({'code':code[:2]+'-'+code[2:], 'matched':code==own_code,
                      'extended_tones':any(c not in TONES for c in code),
                      'start_seconds':round(first['start_seconds'],3),
                      'pulse_seconds':[round(first['duration_seconds'],3),round(second['duration_seconds'],3)],
                      'gap_seconds':round(gap['duration_seconds'],3)})
    return {'own_code':own_code[:2]+'-'+own_code[2:], 'status':'alert' if any(c['matched'] for c in calls) else 'other_station' if calls else 'not_detected',
            'calls':calls, 'mode':mode, 'sample_rate':rate, 'duration_seconds':round(count/rate,3),
            'analysis_step_seconds':0.1,
            'segments':[{**s,'duration_seconds':round(s['duration_seconds'],3)} for s in segments]}
