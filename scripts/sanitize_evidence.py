"""Remove local user directories from text evidence before publication."""

import argparse
import re
import sys
from pathlib import Path


def sanitize(text: str, repository: Path | None = None) -> str:
    root = (repository or Path(__file__).resolve().parents[1]).resolve()
    roots = {str(root), root.as_posix()}
    if root.drive:
        roots.add('/mnt/' + root.drive[0].lower() + root.as_posix()[2:])
    for value in sorted(roots, key=len, reverse=True):
        for variant in (value.replace('\\', '\\\\'), value):
            text = re.sub(re.escape(variant), '/workspace/mini-dbms', text, flags=re.I)
    text = re.sub(r'(?i)/local-user/\s"\x27]+', '/local-user', text)
    text = re.sub(r'(?i)/mnt/[a-z]/users/[^/\s"\x27]+', '/local-user', text)
    text = re.sub(r'(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s"\x27]+', '/local-user', text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='*')
    args = parser.parse_args()
    if not args.files:
        sys.stdout.write(sanitize(sys.stdin.read()))
    for path in args.files:
        data = path.read_bytes()
        clean = sanitize(data.decode('utf-8')).encode('utf-8')
        if clean != data:
            path.write_bytes(clean)


if __name__ == '__main__':
    main()
