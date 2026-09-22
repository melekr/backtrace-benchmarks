#!/usr/bin/env python3
"""Render apple/project.yml from apple/project.yml.tmpl for one SDK source/version.

Usage:
  render_project.py --source spm|xcframework|local --version 2.2.0 [--local-path DIR]
                    [--variants plain,sdk,sentinel] [--api-version 2.2.0]
                    [--template PATH] [--output PATH] [--vendor-dir PATH]

Compile conditions written into SWIFT_ACTIVE_COMPILATION_CONDITIONS of the sdk/sentinel
targets: BT_SDK always, BT_GE_2_1 when version >= 2.1.0, BT_GE_2_2 when version >= 2.2.0.
The plain target gets none. Python 3 stdlib only.
"""
import argparse
import os
import re
import sys

APPLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK_GIT_URL = "https://github.com/backtrace-labs/backtrace-cocoa.git"
VARIANTS = ("plain", "sdk", "sentinel")


def version_id(version):
    """2.2.0 -> 2_2_0, local-SNAPSHOT -> local_SNAPSHOT (bundle-id safe)."""
    return re.sub(r"[^A-Za-z0-9]", "_", version)


def parse_semver(version):
    match = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def compile_conditions(api_version):
    semver = parse_semver(api_version)
    conditions = ["BT_SDK"]
    # Unparseable versions (local checkouts, git shas) are assumed to be newest.
    if semver is None or semver >= (2, 1, 0):
        conditions.append("BT_GE_2_1")
    if semver is None or semver >= (2, 2, 0):
        conditions.append("BT_GE_2_2")
    return conditions


def indent_block(lines, spaces):
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in lines)


def sdk_dependencies(source, version, vendor_rel, embed_backtrace):
    """YAML list items (unindented) describing the SDK dependency for a target."""
    if source in ("spm", "local"):
        return ["- package: Backtrace", "  product: Backtrace"]
    vendor = "%s/%s" % (vendor_rel, version)
    lines = [
        "- framework: %s/Backtrace.xcframework" % vendor,
        "  embed: %s" % ("true" if embed_backtrace else "false"),
        "  codeSign: false",
        "- framework: %s/CrashReporter.xcframework" % vendor,
        "  embed: false",
    ]
    return lines


def packages_block(source, version, local_path):
    if source == "spm":
        return "\n".join([
            "packages:",
            "  Backtrace:",
            "    url: %s" % SDK_GIT_URL,
            "    exactVersion: %s" % version,
        ])
    if source == "local":
        return "\n".join([
            "packages:",
            "  Backtrace:",
            "    path: %s" % local_path,
        ])
    return "# xcframework source: no Swift packages"


def render_blocks(template, block_name, items):
    """Replace {{#NAME}}...{{/NAME}} with the body rendered once per item dict."""
    pattern = re.compile(r"\{\{#%s\}\}\n(.*?)\{\{/%s\}\}\n" % (block_name, block_name), re.S)

    def repl(match):
        body = match.group(1)
        return "".join(substitute(body, item) for item in items)

    return pattern.sub(repl, template)


def substitute(text, mapping):
    def repl(match):
        key = match.group(1)
        if key not in mapping:
            raise KeyError("template placeholder without value: {{%s}}" % key)
        return str(mapping[key])

    return re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", repl, text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, choices=("spm", "xcframework", "local"))
    parser.add_argument("--version", required=True, help="SDK version tag (2.2.0) or label for local (local-SNAPSHOT)")
    parser.add_argument("--local-path", help="SDK checkout path for --source local")
    parser.add_argument("--variants", default="plain,sdk,sentinel", help="comma list of plain,sdk,sentinel")
    parser.add_argument("--api-version", help="version used for BT_GE_* gates (default: --version, local => newest)")
    parser.add_argument("--template", default=os.path.join(APPLE_DIR, "project.yml.tmpl"))
    parser.add_argument("--output", default=os.path.join(APPLE_DIR, "project.yml"))
    parser.add_argument("--vendor-dir", default=os.path.join(APPLE_DIR, "Vendor"),
                        help="where <version>/Backtrace.xcframework lives for --source xcframework")
    args = parser.parse_args(argv)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    for variant in variants:
        if variant not in VARIANTS:
            parser.error("unknown variant %r (expected %s)" % (variant, ", ".join(VARIANTS)))
    if not variants:
        parser.error("--variants must name at least one variant")
    if args.source == "local":
        if not args.local_path:
            parser.error("--source local requires --local-path")
        local_path = os.path.abspath(args.local_path)
        if not os.path.isfile(os.path.join(local_path, "Package.swift")):
            parser.error("no Package.swift under --local-path %s" % local_path)
    else:
        local_path = None

    api_version = args.api_version or args.version
    conditions = compile_conditions(api_version)
    vid = version_id(args.version)

    vendor_rel = os.path.relpath(os.path.abspath(args.vendor_dir), APPLE_DIR)
    if args.source == "xcframework":
        for name in ("Backtrace.xcframework", "CrashReporter.xcframework"):
            path = os.path.join(os.path.abspath(args.vendor_dir), args.version, name)
            if not os.path.isdir(path):
                sys.stderr.write("warning: %s missing; run scripts/fetch_xcframework.py --version %s first\n"
                                 % (path, args.version))

    sdk_variants = [v for v in variants if v != "plain"]
    unit_host = next((v for v in ("sdk", "sentinel") if v in variants), None)

    app_items = []
    for variant in variants:
        is_sdk = variant != "plain"
        deps = sdk_dependencies(args.source, args.version, vendor_rel, embed_backtrace=True) if is_sdk else []
        test_targets = ["- BenchAppUITests-%s" % variant]
        if variant == unit_host:
            test_targets.append("- BenchUnitTests")
        app_items.append({
            "variant": variant,
            "version": args.version,
            "version_id": vid,
            "source": args.source,
            "variant_conditions": " ".join(conditions) if is_sdk else "BT_PLAIN",
            "app_dependencies": indent_block(["dependencies:"] + (["  " + d for d in deps] if deps else ["  []"]), 4)
            if deps else "    dependencies: []",
            "scheme_test_targets": indent_block(test_targets, 8),
        })

    unit_items = []
    if unit_host:
        unit_deps = sdk_dependencies(args.source, args.version, vendor_rel, embed_backtrace=False)
        unit_items.append({
            "host": unit_host,
            "version_id": vid,
            "conditions": " ".join(conditions),
            "unit_dependencies": indent_block(unit_deps, 6),
        })

    with open(args.template, "r", encoding="utf-8") as handle:
        template = handle.read()
    rendered = render_blocks(template, "APP_TARGETS", app_items)
    rendered = render_blocks(rendered, "UNIT_TARGET", unit_items)
    rendered = substitute(rendered, {
        "source": args.source,
        "version": args.version,
        "variants_csv": ",".join(variants),
        "conditions": " ".join(conditions),
        "packages_block": packages_block(args.source, args.version, local_path),
    })
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(rendered)

    print("rendered %s" % args.output)
    print("  source=%s version=%s api=%s variants=%s" % (args.source, args.version, api_version, ",".join(variants)))
    print("  conditions(sdk targets)=%s" % " ".join(conditions))
    for variant in variants:
        print("  BenchApp-%s bundle id io.backtrace.bench.%s.v%s" % (variant, variant, vid))
    if unit_host:
        print("  BenchUnitTests hosted by BenchApp-%s" % unit_host)
    if not sdk_variants:
        print("  note: no sdk/sentinel variant requested; project has no SDK dependency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
