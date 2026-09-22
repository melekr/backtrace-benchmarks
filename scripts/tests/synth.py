"""Synthetic result rows for the harness tests (no device needed)."""
import json
import random

ENV = {"fingerprint": "f" * 64, "runner": "test", "os": "test", "nproc": 4, "cpuLocked": False, "tier": "tier1"}


def row(metric, unit, samples, version, variant="sdk", rnd=1, pos=0, kind="perLaunch", env=None):
    xs = sorted(samples)
    med = xs[len(xs) // 2]
    return {"schemaVersion": 1, "sdk": "android", "platform": "android", "sdkVersion": version, "source": "maven",
            "variant": variant, "scenario": "default", "metric": metric, "unit": unit, "value": med, "samples": samples,
            "round": rnd, "position": pos, "stats": {"n": len(samples), "median": med, "sampleKind": kind},
            "env": env or ENV, "run": {"id": "t", "ts": "2026-09-22T00:00:00Z"}, "valid": True}


def timing_rows(metric, unit, center, version, variant, rounds=3, n=15, jitter=0.02, seed=1, env=None):
    rng = random.Random(seed)
    out = []
    for r in range(1, rounds + 1):
        samples = [center * (1 + rng.uniform(-jitter, jitter)) for _ in range(n)]
        out.append(row(metric, unit, samples, version, variant, rnd=r, pos=r % 2, env=env))
    return out


def size_row(metric, value, version, variant="sdk", env=None):
    return row(metric, "bytes", [value], version, variant, rnd=0, pos=0, kind="exact", env=env)


def write(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
