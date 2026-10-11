"""HACS-TN16-v1: reversible tail-number mapping, not an ASRI assignment."""
from functools import lru_cache
from itertools import combinations
import re
from selcal import validate, tones_for

VERSION = 'HACS-TN16-v1'
ALPHABET = 'ABCDEFGHJKLMPQRS'
FIRST_PAIRS = tuple(combinations(ALPHABET, 2))
SECOND_COUNT = 91  # C(14, 2); C(16, 2) * 91 = 10920 valid codes.

def validate_tail(tail_number):
    if not isinstance(tail_number, str) or not re.fullmatch(r'[0-9]{4}', tail_number):
        raise ValueError('機番号は半角数字4桁の文字列で指定してください（例: 0001、5501）。')
    return tail_number

@lru_cache(maxsize=120)
def _second_pairs(first_pair):
    remaining = tuple(c for c in ALPHABET if c not in first_pair)
    return tuple(combinations(remaining, 2))

def mapping_version(mode='selcal16'):
    tones_for(mode)
    return VERSION if mode == 'selcal16' else 'HACS-TN32-v1'

@lru_cache(maxsize=1)
def _expanded_mapping():
    alphabet = tuple(tones_for('selcal32'))
    codes = []
    for first in combinations(alphabet, 2):
        for second in combinations([c for c in alphabet if c not in first], 2):
            if all(c in ALPHABET for c in first + second):
                continue
            codes.append(''.join(first) + '-' + ''.join(second))
            if len(codes) == 10000:
                return tuple(codes), {code: f'{n:04d}' for n, code in enumerate(codes)}

def tail_to_selcal(tail_number, mode='selcal16'):
    """Map 0000..9999 to the first 10000 valid ordered tone-pair codes."""
    number = int(validate_tail(tail_number))
    tones_for(mode)
    if mode == 'selcal32':
        return _expanded_mapping()[0][number]
    first_index, second_index = divmod(number, SECOND_COUNT)
    first = FIRST_PAIRS[first_index]
    second = _second_pairs(first)[second_index]
    return ''.join(first) + '-' + ''.join(second)

def selcal_to_tail(code, mode='selcal16'):
    """Reverse a mapped code; reject the 920 valid but unassigned codes."""
    normalized = validate(code, mode)
    if mode == 'selcal32':
        formatted = normalized[:2] + '-' + normalized[2:]
        try:
            return _expanded_mapping()[1][formatted]
        except KeyError:
            raise ValueError('このSELCALコードはHACS-TN32-v1の機番号割当範囲外です。') from None
    first = tuple(normalized[:2])
    second = tuple(normalized[2:])
    number = FIRST_PAIRS.index(first) * SECOND_COUNT + _second_pairs(first).index(second)
    if number >= 10000:
        raise ValueError('このSELCALコードはHACS-TN16-v1の機番号割当範囲外です。')
    return f'{number:04d}'

def describe_tail(tail_number, mode='selcal16'):
    return {'tail_number':validate_tail(tail_number), 'selcal_code':tail_to_selcal(tail_number, mode), 'mapping_version':mapping_version(mode), 'mode':mode}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='HACS 機番号とSELCALコードの相互変換')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--tail', help='4桁の機番号 → SELCALコード')
    group.add_argument('--code', help='SELCALコード → 4桁の機番号')
    parser.add_argument('--mode', choices=['selcal16','selcal32'], default='selcal16')
    args = parser.parse_args()
    try:
        from rotation import configured_mapping
        mapping = configured_mapping().snapshot()
        print(mapping.to_code(args.tail, args.mode) if args.tail is not None else mapping.to_tail(args.code, args.mode))
    except ValueError as exc:
        parser.error(str(exc))
