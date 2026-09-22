#!/usr/bin/env python3
"""Render unity/project/Packages/manifest.json and ProjectSettings/ProjectVersion.txt for one cell.

  render_manifest.py --version 3.17.0 --editor 6000.3.7f1 [--source openupm|local --local-path DIR]
                     [--perf-version 3.5.0] [--utf-version auto] [--variant sdk|plain|sentinel]

plain: the SDK dependency is omitted and Assets/Benchmarks is hidden (renamed to Benchmarks~) because its
assembly references Backtrace.Unity; sdk/sentinel: the folder is restored. Stdlib only.
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
UNITY_DIR = os.path.dirname(HERE)
PROJECT = os.path.join(UNITY_DIR, "project")
TEMPLATE = os.path.join(UNITY_DIR, "manifest.json.tmpl")


def utf_for_editor(editor):
    major = int(re.match(r"(\d+)", editor).group(1))
    return "1.6.0" if major >= 6000 else "1.4.6"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="io.backtrace.unity version (OpenUPM) or label for local")
    ap.add_argument("--editor", required=True, help="Unity editor version, e.g. 2022.3.56f1")
    ap.add_argument("--source", default="openupm", choices=["openupm", "local"])
    ap.add_argument("--local-path", help="SDK checkout for --source local (package root with package.json)")
    ap.add_argument("--perf-version", default="3.5.0")
    ap.add_argument("--utf-version", default="auto")
    ap.add_argument("--variant", default="sdk", choices=["plain", "sdk", "sentinel"])
    ap.add_argument("--project", default=PROJECT)
    a = ap.parse_args()

    if a.source == "local":
        if not a.local_path:
            sys.exit("--local-path is required with --source local")
        sdk_dep = "file:" + os.path.relpath(os.path.abspath(a.local_path), os.path.join(a.project, "Packages"))
    else:
        sdk_dep = a.version
    utf = utf_for_editor(a.editor) if a.utf_version == "auto" else a.utf_version

    tmpl = open(TEMPLATE, encoding="utf-8").read()
    rendered = tmpl.replace("{{sdk_dependency}}", sdk_dep).replace("{{utf_version}}", utf).replace("{{perf_version}}", a.perf_version)
    manifest = json.loads(rendered)
    if a.variant == "plain":
        manifest["dependencies"].pop("io.backtrace.unity", None)
    os.makedirs(os.path.join(a.project, "Packages"), exist_ok=True)
    with open(os.path.join(a.project, "Packages", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    lock = os.path.join(a.project, "Packages", "packages-lock.json")
    if os.path.exists(lock):
        os.remove(lock)

    os.makedirs(os.path.join(a.project, "ProjectSettings"), exist_ok=True)
    with open(os.path.join(a.project, "ProjectSettings", "ProjectVersion.txt"), "w", encoding="utf-8") as f:
        f.write("m_EditorVersion: %s\n" % a.editor)

    bench = os.path.join(a.project, "Assets", "Benchmarks")
    hidden = os.path.join(a.project, "Assets", "Benchmarks~")
    if a.variant == "plain" and os.path.isdir(bench):
        shutil.move(bench, hidden)
    elif a.variant != "plain" and os.path.isdir(hidden) and not os.path.isdir(bench):
        shutil.move(hidden, bench)

    print("rendered manifest: io.backtrace.unity=%s utf=%s perf=%s editor=%s variant=%s" % (
        sdk_dep if a.variant != "plain" else "(absent)", utf, a.perf_version, a.editor, a.variant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
