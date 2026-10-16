#!/usr/bin/env python3
"""Print the rows whose metric id matches any --keep glob (or none of the --drop globs) from rows.jsonl files.

  filter_rows.py --keep 'A2.*' rows-a.jsonl rows-b.jsonl > macro.jsonl
  filter_rows.py --drop 'A1.*' --drop 'A7.*' rows.jsonl
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from typing import List


def wanted(metric: str, keep: List[str], drop: List[str]) -> bool:
    if keep and not any(fnmatch.fnmatchcase(metric, g) for g in keep):
        return False
    return not any(fnmatch.fnmatchcase(metric, g) for g in drop)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--keep", action="append", default=[], help="glob of metric ids to keep (repeatable)")
    ap.add_argument("--drop", action="append", default=[], help="glob of metric ids to drop (repeatable)")
    args = ap.parse_args(argv)
    kept = 0
    for path in args.paths:
        try:
            fh = open(path, "r", encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if wanted(str(row.get("metric", "")), args.keep, args.drop):
                    sys.stdout.write(line + "\n")
                    kept += 1
    print(f"filter_rows: {kept} rows kept", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
