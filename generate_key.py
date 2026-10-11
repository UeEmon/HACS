"""Create a root key without printing it or replacing an existing key."""
import argparse
import os
from pathlib import Path
import secrets


def create_key(filename):
    target = Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Parent directory protects the host copy; container secret is read-only.
    if os.name == 'posix' and target.parent.stat().st_mode & 0o077:
        raise ValueError('鍵の保存先ディレクトリは所有者のみアクセス可能（700）にしてください。')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, 'w', encoding='ascii') as stream:
        stream.write(secrets.token_hex(32)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='自動更新用の共通鍵を生成（既存鍵は上書きしません）')
    parser.add_argument('--output', default='.secrets/mapping.key')
    args = parser.parse_args()
    try:
        create_key(args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print('共通鍵ファイルを作成しました。鍵の内容は表示しません。')
