"""HACS-TN16-v1: reversible tail-number mapping, not an ASRI assignment."""
from functools import lru_cache
from itertools import combinations
import re
from selcal import validate

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

def tail_to_selcal(tail_number):
    """Map 0000..9999 to the first 10000 valid ordered tone-pair codes."""
    number = int(validate_tail(tail_number))
    first_index, second_index = divmod(number, SECOND_COUNT)
    first = FIRST_PAIRS[first_index]
    second = _second_pairs(first)[second_index]
    return ''.join(first) + '-' + ''.join(second)

def selcal_to_tail(code):
    """Reverse a mapped code; reject the 920 valid but unassigned codes."""
    normalized = validate(code)
    first = tuple(normalized[:2])
    second = tuple(normalized[2:])
    number = FIRST_PAIRS.index(first) * SECOND_COUNT + _second_pairs(first).index(second)
    if number >= 10000:
        raise ValueError('このSELCALコードはHACS-TN16-v1の機番号割当範囲外です。')
    return f'{number:04d}'

def describe_tail(tail_number):
    return {'tail_number':validate_tail(tail_number), 'selcal_code':tail_to_selcal(tail_number), 'mapping_version':VERSION}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='HACS 機番号とSELCALコードの相互変換')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--tail', help='4桁の機番号 → SELCALコード')
    group.add_argument('--code', help='SELCALコード → 4桁の機番号')
    args = parser.parse_args()
    try:
        print(tail_to_selcal(args.tail) if args.tail is not None else selcal_to_tail(args.code))
    except ValueError as exc:
        parser.error(str(exc))
