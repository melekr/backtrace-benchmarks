#!/usr/bin/env python3
"""Validate rows.jsonl against schema/result.schema.json and metric ids against schema/metrics.yml.

Uses the ``jsonschema`` package when importable, otherwise a built-in validator that
covers the subset of JSON Schema used by the harness schemas (type, enum, const,
required, properties, additionalProperties, items, minimum).

  validate_rows.py rows.jsonl [DIR|FILE ...] [--schema F] [--metrics F] [--allow-unknown-metrics]
Exit 0 when every row is valid, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_common as hc  # noqa: E402

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer()),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _mini_validate(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    errs: List[str] = []
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in {schema['enum']}")
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](instance) for x in types):
            errs.append(f"{path}: expected type {t}, got {type(instance).__name__}")
            return errs
    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            errs.append(f"{path}: {instance} < minimum {schema['minimum']}")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs.extend(_mini_validate(v, props[k], f"{path}.{k}"))
            else:
                ap = schema.get("additionalProperties", True)
                if ap is False:
                    errs.append(f"{path}: additional property {k!r} not allowed")
                elif isinstance(ap, dict):
                    errs.extend(_mini_validate(v, ap, f"{path}.{k}"))
    if isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(instance):
            errs.extend(_mini_validate(item, schema["items"], f"{path}[{i}]"))
    return errs


def schema_errors(instance: Any, schema: Dict[str, Any]) -> List[str]:
    try:
        import jsonschema  # type: ignore

        validator = jsonschema.Draft202012Validator(schema)
        out = []
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
            loc = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.path)
            out.append(f"{loc}: {e.message}")
        return out
    except ImportError:
        return _mini_validate(instance, schema)


def load_schema(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_row(row: Dict[str, Any], schema: Dict[str, Any], catalog: Optional[hc.MetricCatalog],
                 allow_unknown: bool = False) -> List[str]:
    errs = schema_errors(hc.strip_private(row), schema)
    if catalog is not None and isinstance(row.get("metric"), str):
        entry = catalog.resolve(row["metric"])
        if entry is None:
            if not allow_unknown:
                errs.append(f"$.metric: {row['metric']!r} is not in metrics.yml")
        else:
            if row.get("unit") != entry.get("unit"):
                errs.append(f"$.unit: {row.get('unit')!r} differs from metrics.yml unit {entry.get('unit')!r} for {entry['id']}")
            if row.get("sdk") != entry.get("sdk"):
                errs.append(f"$.sdk: {row.get('sdk')!r} does not own metric {entry['id']} ({entry.get('sdk')})")
    stats = row.get("stats") or {}
    samples = row.get("samples")
    if isinstance(samples, list) and isinstance(stats.get("n"), int) and stats["n"] != len(samples):
        errs.append(f"$.stats.n: {stats['n']} != len(samples) {len(samples)}")
    return errs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="rows.jsonl files or directories")
    ap.add_argument("--schema", default=hc.RESULT_SCHEMA_PATH)
    ap.add_argument("--metrics", default=hc.METRICS_PATH)
    ap.add_argument("--allow-unknown-metrics", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    schema = load_schema(args.schema)
    catalog = hc.load_metrics(args.metrics)
    try:
        rows = hc.read_rows(args.paths)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    bad = 0
    for i, row in enumerate(rows):
        errs = validate_row(row, schema, catalog, args.allow_unknown_metrics)
        if errs:
            bad += 1
            where = f"{row.get('_file', '<stdin>')} row {i + 1} ({row.get('metric')})"
            print(f"INVALID {where}")
            for e in errs:
                print(f"    {e}")
    if not args.quiet:
        print(f"validate_rows: {len(rows) - bad}/{len(rows)} rows valid in {len(hc.iter_jsonl_files(args.paths))} file(s)")
    return 1 if bad or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
