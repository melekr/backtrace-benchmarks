#!/usr/bin/env python3
"""Plan adjacent version pairs for a release ladder.

Each pair becomes one comparable job (plain + older + newer + sentinel in the same job). The report job chains the
pairs into one ladder normalized to the oldest version. Prints GITHUB_OUTPUT lines: sdk=, versions=, pairs=<json>.
"""
import argparse
import json
import sys


def plan(versions):
    vs = [v.strip() for v in versions.split(",") if v.strip()]
    if not vs:
        raise SystemExit("no versions given")
    if len(vs) == 1:
        return vs, [{"a": vs[0], "b": vs[0], "pair": vs[0]}]
    return vs, [{"a": a, "b": b, "pair": f"{a},{b}"} for a, b in zip(vs, vs[1:])]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", required=True, choices=["android", "apple", "unity"])
    ap.add_argument("--versions", required=True)
    args = ap.parse_args()
    vs, pairs = plan(args.versions)
    print(f"sdk={args.sdk}")
    print(f"versions={','.join(vs)}")
    print(f"pairs={json.dumps(pairs, separators=(',', ':'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
