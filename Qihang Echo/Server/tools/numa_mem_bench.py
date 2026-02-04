#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""NUMA memory defense micro-benchmark.

Why:
- On your board, only node0 has CPUs; node2 has 512MB memory but no CPUs.
- To demonstrate "NUMA 内存防御", the clearest experiment is:
    CPU pinned to node0, but memory forced to node2 (remote)  -> worse
    CPU pinned to node0, memory forced to node0 (local)       -> better

This script measures memory scan throughput by repeatedly summing a large
uint8 NumPy array (C-optimized) and records latency distribution.

Run it under numactl/taskset externally; the script will record
Cpus_allowed_list/Mems_allowed_list for evidence.

Example:
  numactl --physcpubind=0-3 --membind=2 python3 tools/numa_mem_bench.py --mem-mb 256 --loops 30 --out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np


def _read_status_fields() -> dict[str, Optional[str]]:
    fields = {
        "Cpus_allowed_list": None,
        "Mems_allowed_list": None,
    }
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                for k in list(fields.keys()):
                    if line.startswith(k + ":"):
                        fields[k] = line.split(":", 1)[1].strip()
        return fields
    except Exception:
        return fields


def _read_numa_maps_node_pages() -> Optional[dict[str, int]]:
    """Parse /proc/self/numa_maps and aggregate pages per NUMA node.

    Returns a mapping like {"N0": 12345, "N2": 6789} or None if unavailable.
    """
    try:
        pages: dict[str, int] = {}
        with open("/proc/self/numa_maps", "r", encoding="utf-8") as f:
            for line in f:
                # Tokens include entries like: N0=123 N1=0 N2=45
                for tok in line.split():
                    if len(tok) >= 4 and tok[0] == "N" and "=" in tok:
                        k, v = tok.split("=", 1)
                        if k.startswith("N"):
                            try:
                                pages[k] = pages.get(k, 0) + int(v)
                            except Exception:
                                pass
        return pages if pages else None
    except Exception:
        return None


def _safe_import_psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except Exception:
        return None


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1


def main() -> int:
    ap = argparse.ArgumentParser(description="NUMA memory scan micro-benchmark (JSON output)")
    ap.add_argument("--mode", choices=["baseline", "defense"], default="baseline")
    ap.add_argument("--mem-mb", type=int, default=256, help="Array size in MB (keep <= node2 free if membind=2)")
    ap.add_argument(
        "--dtype",
        choices=["uint8", "uint64", "float64"],
        default="float64",
        help="Array dtype (default: float64; more memory-bound than uint8)",
    )
    ap.add_argument(
        "--pattern",
        choices=["scan", "random_page"],
        default="scan",
        help=(
            "Access pattern. 'scan' streams through the whole array (bandwidth-oriented). "
            "'random_page' touches multiple elements per 4KB page in random page order (latency/TLB-oriented; often amplifies remote-NUMA penalty)."
        ),
    )
    ap.add_argument(
        "--touch-per-page",
        type=int,
        default=16,
        help="For pattern=random_page: how many elements to touch per 4KB page (default: 16).",
    )
    ap.add_argument("--loops", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    mem_mb = int(args.mem_mb)
    if mem_mb <= 0:
        raise SystemExit("--mem-mb must be > 0")

    nbytes = mem_mb * 1024 * 1024
    dtype = np.dtype(args.dtype)
    elem_size = int(dtype.itemsize)
    n_elems = max(1, nbytes // elem_size)
    arr = np.zeros(n_elems, dtype=dtype)

    # Touch pages to materialize RSS
    # Touch approximately one element per 4KB page.
    step = max(1, 4096 // elem_size)
    arr[::step] = 1

    numa_pages_before = _read_numa_maps_node_pages()

    # Prepare benchmark kernel
    pattern = str(args.pattern)

    bytes_per_iter: int
    if pattern == "scan":
        bytes_per_iter = n_elems * elem_size

        def bench_once() -> float:
            return float(arr.sum())

    elif pattern == "random_page":
        # Randomize page order, touch multiple elements per page.
        step = max(1, 4096 // elem_size)  # elems per 4KB page
        pages = max(1, n_elems // step)
        touches = max(1, int(args.touch_per_page))
        touches = min(touches, step)

        rng = np.random.default_rng(42)
        page_order = rng.permutation(pages).astype(np.int64, copy=False)

        # Choose offsets within a page (deterministic).
        if touches == 1:
            offsets = np.array([0], dtype=np.int64)
        else:
            offsets = np.linspace(0, step - 1, num=touches, dtype=np.int64)

        positions = (page_order[:, None] * step + offsets[None, :]).reshape(-1)
        positions = positions[positions < n_elems]
        bytes_per_iter = int(positions.size) * elem_size

        def bench_once() -> float:
            return float(arr[positions].sum())

    else:
        raise SystemExit(f"Unknown pattern: {pattern}")

    # Warmup
    for _ in range(max(0, int(args.warmup))):
        _ = bench_once()

    psutil = _safe_import_psutil()
    proc = psutil.Process(os.getpid()) if psutil else None

    lat_ms: list[float] = []
    gbps: list[float] = []

    for _ in range(max(1, int(args.loops))):
        s = time.perf_counter()
        _ = bench_once()
        e = time.perf_counter()
        dt = e - s
        lat_ms.append(dt * 1000.0)
        gbps.append((bytes_per_iter / dt) / (1024**3))

    lat_sorted = sorted(lat_ms)
    gbps_sorted = sorted(gbps)

    status = _read_status_fields()
    numa_pages_after = _read_numa_maps_node_pages()

    rss_mb = None
    if proc:
        try:
            rss_mb = float(proc.memory_info().rss) / (1024 * 1024)
        except Exception:
            rss_mb = None

    report: dict[str, Any] = {
        "meta": {
            "mode": args.mode,
            "mem_mb": mem_mb,
            "dtype": str(dtype),
            "pattern": pattern,
            "touch_per_page": int(args.touch_per_page),
            "bytes_per_iter": int(bytes_per_iter),
            "loops": int(args.loops),
            "warmup": int(args.warmup),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "host": platform.node(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "pid": os.getpid(),
            "proc_status": status,
            "numa_maps_node_pages_before": numa_pages_before,
            "numa_maps_node_pages_after": numa_pages_after,
        },
        "latency_ms": lat_ms,
        "throughput_gbps": gbps,
        "summary": {
            "lat_p50_ms": _percentile(lat_sorted, 50),
            "lat_p95_ms": _percentile(lat_sorted, 95),
            "lat_p99_ms": _percentile(lat_sorted, 99),
            "bw_p50_gbps": _percentile(gbps_sorted, 50),
            "bw_p05_gbps": _percentile(gbps_sorted, 5),
            "bw_p95_gbps": _percentile(gbps_sorted, 95),
            "rss_mb": rss_mb,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] wrote: {out_path}")
    print("[Summary]", report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

