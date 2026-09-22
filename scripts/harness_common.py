"""Shared helpers for the benchmark harness scripts (stdlib only).

Everything cross-platform lives here: repository paths, YAML loading (PyYAML
when importable, ``_yamlmini`` otherwise), the metric catalogue with wildcard
segments, row I/O, environment fingerprinting and Markdown formatting.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
SCHEMA_DIR = os.path.join(REPO_ROOT, "schema")
METRICS_PATH = os.path.join(SCHEMA_DIR, "metrics.yml")
RESULT_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "result.schema.json")
BENCH_RESULT_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "bench-result.schema.json")
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.yml")
ENV_FINGERPRINT_SH = os.path.join(SCRIPTS_DIR, "env_fingerprint.sh")

SDKS = ("android", "apple", "unity")
SDK_PREFIX = {"android": "A", "apple": "C", "unity": "U"}
VARIANTS = ("plain", "sdk", "sentinel")
SOURCES = ("maven", "spm", "xcframework", "cocoapods", "openupm", "local")
SAMPLE_KINDS = ("perLaunch", "perIteration", "measurementAverage", "exact")

# Comparability fields hashed into env.fingerprint (docs/CONVENTIONS.md section 9).
FINGERPRINT_FIELDS = (
    "runner", "os", "nproc", "xcode", "agp", "gradle", "jdk", "unity",
    "emulator", "simulator", "device", "cpuLocked", "tier",
)

# Ladders from docs/CONVENTIONS.md section 3 (oldest -> newest).
LADDERS = {
    "android": ["3.8.4", "3.9.0", "3.10.6", "3.11.0", "3.13.0", "3.14.0"],
    "apple": ["2.0.6", "2.0.9", "2.1.0", "2.2.0"],
    "unity": ["3.13.0", "3.14.1", "3.15.1", "3.16.2", "3.17.0"],
}


# ----------------------------------------------------------------------------- YAML

def load_yaml(path: str) -> Any:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except ImportError:
        sys.path.insert(0, SCRIPTS_DIR)
        import _yamlmini

        return _yamlmini.load(path)


# -------------------------------------------------------------------------- metrics

_WILDCARD_RE = re.compile(r"<(abi|slice|stage|N|platform|variant)>")


def metric_regex(catalog_id: str) -> "re.Pattern[str]":
    """Regex for a catalogue id; ``<N>`` matches digits, other wildcards one segment."""
    out = []
    pos = 0
    for m in _WILDCARD_RE.finditer(catalog_id):
        out.append(re.escape(catalog_id[pos : m.start()]))
        out.append(r"\d+" if m.group(1) == "N" else r"[^.]+")
        pos = m.end()
    out.append(re.escape(catalog_id[pos:]))
    return re.compile("^" + "".join(out) + "$")


class MetricCatalog:
    def __init__(self, data: Dict[str, Any]):
        self.version = data.get("version")
        self.entries: Dict[str, Dict[str, Any]] = {}
        for sdk, metrics in (data.get("sdks") or {}).items():
            for mid, meta in (metrics or {}).items():
                meta = dict(meta or {})
                meta["sdk"] = sdk
                meta["id"] = mid
                self.entries[mid] = meta
        self._patterns = [(mid, metric_regex(mid)) for mid in self.entries if "<" in mid]

    def resolve(self, metric_id: str) -> Optional[Dict[str, Any]]:
        """Catalogue entry for a concrete row metric id (wildcard-aware) or None."""
        if metric_id in self.entries:
            return self.entries[metric_id]
        for mid, rx in self._patterns:
            if rx.match(metric_id):
                return self.entries[mid]
        return None

    def ids(self) -> List[str]:
        return list(self.entries)

    def glob_matches(self, glob: str) -> List[str]:
        """Catalogue ids a thresholds glob covers (``*`` glob or a concrete id)."""
        hits = [mid for mid in self.entries if fnmatch.fnmatchcase(mid, glob)]
        if not hits and "*" not in glob:
            e = self.resolve(glob)
            if e:
                hits = [e["id"]]
        return hits

    def sdk_for_prefix(self, metric_id: str) -> Optional[str]:
        e = self.resolve(metric_id)
        return e["sdk"] if e else None


def load_metrics(path: str = METRICS_PATH) -> MetricCatalog:
    return MetricCatalog(load_yaml(path))


def glob_match_metric(glob: str, metric_id: str, catalog: Optional[MetricCatalog] = None) -> bool:
    """Does a thresholds glob apply to a concrete row metric id?"""
    if fnmatch.fnmatchcase(metric_id, glob):
        return True
    if catalog is not None and "*" in glob:
        e = catalog.resolve(metric_id)
        if e and fnmatch.fnmatchcase(e["id"], glob):
            return True
    if catalog is None and "<" in glob:
        return bool(metric_regex(glob).match(metric_id))
    return False


# ----------------------------------------------------------------------------- rows

def iter_jsonl_files(paths: Iterable[str]) -> List[str]:
    files: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for n in sorted(names):
                    if n.endswith(".jsonl"):
                        files.append(os.path.join(root, n))
        elif p:
            files.append(p)
    return files


def read_rows(paths: Iterable[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for f in iter_jsonl_files(paths):
        with open(f, "r", encoding="utf-8") as fh:
            for ln, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{f}:{ln}: invalid JSON: {exc}") from exc
                row.setdefault("_file", f)
                rows.append(row)
    return rows


def write_rows(rows: Iterable[Dict[str, Any]], path: Optional[str], append: bool = False) -> None:
    out = sys.stdout if path in (None, "-") else open(path, "a" if append else "w", encoding="utf-8")
    try:
        for r in rows:
            out.write(json.dumps(strip_private(r), sort_keys=True) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()


def strip_private(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def row_is_valid(row: Dict[str, Any]) -> bool:
    return bool(row.get("valid", True))


# ------------------------------------------------------------------------------ env

def _fp_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def compute_fingerprint(env: Dict[str, Any]) -> str:
    """sha256 over the sorted ``key=value`` lines of the comparability fields.

    Must stay byte-identical with scripts/env_fingerprint.sh.
    """
    lines = sorted(f"{k}={_fp_value(env.get(k))}" for k in FINGERPRINT_FIELDS)
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def python_env(tier: str = "tier0", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fallback env when the shell script cannot run (same field set)."""
    import platform as _pl

    runner = os.environ.get("RUNNER_OS") or os.environ.get("ImageOS") or _pl.system()
    env: Dict[str, Any] = {
        "runner": runner,
        "os": f"{_pl.system()} {_pl.release()}",
        "nproc": os.cpu_count() or 0,
        "xcode": "", "agp": "", "gradle": "", "jdk": "", "unity": "",
        "emulator": "", "simulator": "", "device": "",
        "cpuLocked": False,
        "tier": tier,
    }
    for k, v in (overrides or {}).items():
        env[k] = v
    env["fingerprint"] = compute_fingerprint(env)
    return env


def load_env(path: Optional[str], tier: str = "tier0", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load env.json, or run env_fingerprint.sh, or fall back to python_env()."""
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            env = json.load(fh)
        if "fingerprint" not in env:
            env["fingerprint"] = compute_fingerprint(env)
        return env
    cmd = ["bash", ENV_FINGERPRINT_SH, "--tier", tier]
    for k, v in (overrides or {}).items():
        cmd += ["--set", f"{k}={_fp_value(v)}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return python_env(tier, overrides)


# ------------------------------------------------------------------------------ misc

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_run_id() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run(run_id: Optional[str], workflow: Optional[str] = None, sha: Optional[str] = None, url: Optional[str] = None) -> Dict[str, Any]:
    run: Dict[str, Any] = {"id": run_id or default_run_id(), "ts": now_iso()}
    if workflow:
        run["workflow"] = workflow
    if sha:
        run["sha"] = sha
    if url:
        run["url"] = url
    return run


def version_key(v: str) -> Tuple:
    """Sort key for dotted versions; non-numeric parts sort after numeric ones."""
    parts: List[Tuple[int, Any]] = []
    for p in re.split(r"[.\-]", v):
        parts.append((0, int(p)) if p.isdigit() else (1, p))
    return tuple(parts)


def fmt_int(n: Any) -> str:
    try:
        return f"{int(round(float(n))):,}"
    except (TypeError, ValueError):
        return str(n)


def fmt_num(x: Any, unit: str = "") -> str:
    if x is None:
        return "n/a"
    if unit in ("bytes", "count"):
        return fmt_int(x)
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if abs(xf) >= 1000:
        return f"{xf:,.1f}"
    if abs(xf) >= 10:
        return f"{xf:.2f}"
    return f"{xf:.3f}"


def fmt_pct(ratio_delta: Optional[float]) -> str:
    if ratio_delta is None:
        return "n/a"
    pct = ratio_delta * 100
    if abs(pct) < 0.005:
        pct = 0.0
    return f"{pct:+.2f}%"


def md_table(headers: List[str], rows: List[List[Any]]) -> str:
    def cell(x: Any) -> str:
        return str(x).replace("|", "\\|")

    out = ["| " + " | ".join(cell(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(cell(c) for c in r) + " |")
    return "\n".join(out)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
