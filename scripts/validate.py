"""Validate film project files against schemas/ (plus the rules a schema can't express).

    uv run scripts/validate.py films/kite-day/characters/pip/rig.json films/kite-day/film.json
    uv run scripts/validate.py --as shot some/other/name.json

The schema is picked from the file name (rig.json, shot.json, shotlist.json, film.json) unless
--as is given. Exit code 0 when every file is valid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from studio_core.schema import SCHEMAS, validate_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--as", dest="kind", choices=SCHEMAS)
    args = parser.parse_args()
    failed = 0
    for path in args.files:
        issues = validate_file(path, args.kind)
        print(f"{'OK  ' if not issues else 'FAIL'} {path}")
        for issue in issues:
            print(f"     {issue}")
        failed += bool(issues)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
