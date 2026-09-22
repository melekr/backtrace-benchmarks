#!/usr/bin/env python3
"""Download the published Archive_XCFrameworks_<version>.tar.gz and extract the two xcframeworks.

Usage: fetch_xcframework.py --version 2.2.0 [--artifacts-dir apple/artifacts] [--vendor-dir apple/Vendor] [--force]

Idempotent: the tarball is cached under artifacts/, extraction is skipped when
Vendor/<version>/Backtrace.xcframework and CrashReporter.xcframework already exist.
Observed archive layout (2.2.0): frameworks/Backtrace.xcframework and
frameworks/PLCrashReporter/CrashReporter.xcframework; other layouts are found by name.
Exit codes: 0 ok, 4 when the release asset does not exist (unsupported cell), 1 other failure.
Python 3 stdlib only; only contacts github.com release downloads.
"""
import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

APPLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_URL = "https://github.com/backtrace-labs/backtrace-cocoa/releases/download/{version}/Archive_XCFrameworks_{version}.tar.gz"
FRAMEWORKS = ("Backtrace.xcframework", "CrashReporter.xcframework")


def download(url, dest):
    tmp = dest + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": "backtrace-benchmarks/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as handle:
        shutil.copyfileobj(response, handle)
    os.replace(tmp, dest)


def find_member_roots(tar, names):
    roots = {}
    for member in tar.getmembers():
        parts = member.name.split("/")
        for index, part in enumerate(parts):
            if part in names and part not in roots:
                roots[part] = "/".join(parts[:index + 1])
    return roots


def extract(tarball, vendor_version_dir):
    with tarfile.open(tarball, "r:gz") as tar:
        roots = find_member_roots(tar, FRAMEWORKS)
        missing = [name for name in FRAMEWORKS if name not in roots]
        if missing:
            raise RuntimeError("archive %s lacks %s" % (tarball, ", ".join(missing)))
        with tempfile.TemporaryDirectory(dir=os.path.dirname(vendor_version_dir)) as tmp:
            members = [m for m in tar.getmembers() if any(m.name == r or m.name.startswith(r + "/") for r in roots.values())]
            # Python 3.12+ supports the 'filter' argument; older versions fall back to the default behaviour.
            try:
                tar.extractall(tmp, members=members, filter="fully_trusted")
            except TypeError:
                tar.extractall(tmp, members=members)
            os.makedirs(vendor_version_dir, exist_ok=True)
            for name, root in roots.items():
                target = os.path.join(vendor_version_dir, name)
                if os.path.isdir(target):
                    shutil.rmtree(target)
                shutil.move(os.path.join(tmp, root), target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifacts-dir", default=os.path.join(APPLE_DIR, "artifacts"))
    parser.add_argument("--vendor-dir", default=os.path.join(APPLE_DIR, "Vendor"))
    parser.add_argument("--force", action="store_true", help="re-download and re-extract")
    args = parser.parse_args(argv)

    os.makedirs(args.artifacts_dir, exist_ok=True)
    os.makedirs(args.vendor_dir, exist_ok=True)
    tarball = os.path.join(args.artifacts_dir, "Archive_XCFrameworks_%s.tar.gz" % args.version)
    vendor_version_dir = os.path.join(args.vendor_dir, args.version)

    if args.force or not os.path.isfile(tarball):
        url = RELEASE_URL.format(version=args.version)
        print("downloading %s" % url)
        try:
            download(url, tarball)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                sys.stderr.write("release asset not found (HTTP 404): %s\n" % url)
                return 4
            sys.stderr.write("download failed: HTTP %s\n" % error.code)
            return 1
        except (urllib.error.URLError, OSError) as error:
            sys.stderr.write("download failed: %s\n" % error)
            return 1
    else:
        print("cached %s" % tarball)

    if not args.force and all(os.path.isdir(os.path.join(vendor_version_dir, name)) for name in FRAMEWORKS):
        print("extracted %s" % vendor_version_dir)
        return 0
    try:
        extract(tarball, vendor_version_dir)
    except (RuntimeError, tarfile.TarError, OSError) as error:
        sys.stderr.write("extract failed: %s\n" % error)
        return 1
    print("extracted %s" % vendor_version_dir)
    print("  archive bytes: %d" % os.path.getsize(tarball))
    return 0


if __name__ == "__main__":
    sys.exit(main())
