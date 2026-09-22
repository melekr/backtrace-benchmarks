#!/usr/bin/env python3
"""Generate a disposable asset fixture with many tiny files so the APK ZIP central directory has N extra entries.

  gen_fixture.py --entries 10000 --out android/build/fixture
The directory is passed to Gradle with -PbtFixtureAssets=<dir> for scenario largeapk. Never commit the output.
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entries", type=int, default=10000)
    ap.add_argument("--bytes-per-entry", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.entries < 1:
        sys.exit("--entries must be >= 1")
    target = os.path.join(os.path.abspath(a.out), "bench-fixture")
    os.makedirs(target, exist_ok=True)
    existing = len([n for n in os.listdir(target) if n.endswith(".txt")])
    if existing == a.entries:
        print("fixture already has %d entries at %s" % (a.entries, target))
        return 0
    for name in os.listdir(target):
        os.remove(os.path.join(target, name))
    payload = b"x" * a.bytes_per_entry
    for i in range(a.entries):
        with open(os.path.join(target, "%06d.txt" % i), "wb") as f:
            f.write(payload)
    print("wrote %d entries to %s" % (a.entries, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
