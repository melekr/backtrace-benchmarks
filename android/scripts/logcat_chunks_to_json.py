#!/usr/bin/env python3
"""Rebuild *-benchmarkData.json echoed into logcat as "BacktraceBenchData: [i/n]<chunk>" lines.

  logcat_chunks_to_json.py LOGFILE [LOGFILE ...] --out DIR
Accepts plain `adb logcat` text and JSON-lines device logs ({"message": ...}). One output file per contiguous
[1/n]..[n/n] sequence. Stdlib only.
"""
import argparse
import json
import os
import re
import sys

CHUNK = re.compile(r"BacktraceBenchData\s*:\s*\[(\d+)/(\d+)\](.*)$")


def messages(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line.lstrip().startswith("{"):
            try:
                yield json.loads(line).get("message", "")
                continue
            except json.JSONDecodeError:
                pass
        yield line


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    written = 0
    for log in a.logs:
        current, total = {}, None
        for msg in messages(log):
            m = CHUNK.search(msg)
            if not m:
                continue
            i, n, chunk = int(m.group(1)), int(m.group(2)), m.group(3)
            if i == 1:
                current, total = {}, n
            current[i] = chunk
            if total and len(current) == total:
                text = "".join(current[k] for k in range(1, total + 1))
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    print("logcat_chunks_to_json: corrupt sequence in %s: %s" % (log, e), file=sys.stderr)
                    current, total = {}, None
                    continue
                written += 1
                name = "%s-benchmarkData-%d.json" % (os.path.splitext(os.path.basename(log))[0], written)
                with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                current, total = {}, None
    print("logcat_chunks_to_json: wrote %d file(s) to %s" % (written, a.out))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
