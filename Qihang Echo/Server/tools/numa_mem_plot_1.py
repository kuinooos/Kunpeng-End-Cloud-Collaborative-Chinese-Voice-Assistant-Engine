#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Plot NUMA memory defense comparison figures.

Input: two JSON files produced by tools/numa_mem_bench.py
Output: PNG figures + summary.md

Requires: matplotlib, numpy
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _load(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _style():
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 220,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "legend.fontsize": 10,
            "axes.grid": True,
            "grid.alpha": 0.25,
        }
    )


def _get(r: dict[str, Any], k: str) -> float:
    v = r.get("summary", {}).get(k)
    return float(v) if v is not None else float("nan")


def plot_latency_box(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    b_lat = np.asarray(b.get("latency_ms", []), dtype=float)
    a_lat = np.asarray(a.get("latency_ms", []), dtype=float)

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.boxplot([b_lat, a_lat], labels=["Remote mem (node2)", "Local mem (node0)"], showmeans=True)
    ax.set_ylabel("Scan latency (ms)")
    ax.set_title("NUMA memory defense: remote vs local (lower is better)")
    ax.grid(True, axis="y")

    fig.tight_layout()
    fig.savefig(out_dir / "mem_latency_box.png")
    plt.close(fig)


def plot_bw_bar(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    labels = ["P50", "P05 (tail)", "P95"]
    b_vals = [_get(b, "bw_p50_gbps"), _get(b, "bw_p05_gbps"), _get(b, "bw_p95_gbps")]
    a_vals = [_get(a, "bw_p50_gbps"), _get(a, "bw_p05_gbps"), _get(a, "bw_p95_gbps")]

    x = np.arange(len(labels))
    w = 0.36

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.bar(x - w / 2, b_vals, width=w, label="Remote mem (node2)")
    ax.bar(x + w / 2, a_vals, width=w, label="Local mem (node0)")

    for i, v in enumerate(b_vals):
        ax.text(x[i] - w / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)
    for i, v in enumerate(a_vals):
        ax.text(x[i] + w / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Scan throughput (GB/s)")
    ax.set_title("Memory bandwidth stability (higher is better)")
    ax.legend(loc="upper right")
    ax.grid(True, axis="y")

    fig.tight_layout()
    fig.savefig(out_dir / "mem_throughput.png")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate NUMA memory defense figures")
    ap.add_argument("--remote", required=True, help="JSON for remote memory case (membind=2)")
    ap.add_argument("--local", required=True, help="JSON for local memory case (membind=0)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    _style()

    b = _load(Path(args.remote))
    a = _load(Path(args.local))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_latency_box(b, a, out_dir)
    plot_bw_bar(b, a, out_dir)

    lat_p95_gain = _get(b, "lat_p95_ms") / _get(a, "lat_p95_ms") if np.isfinite(_get(a, "lat_p95_ms")) else float("nan")
    lat_p99_gain = _get(b, "lat_p99_ms") / _get(a, "lat_p99_ms") if np.isfinite(_get(a, "lat_p99_ms")) else float("nan")
    bw_p50_gain = _get(a, "bw_p50_gbps") / _get(b, "bw_p50_gbps") if np.isfinite(_get(b, "bw_p50_gbps")) else float("nan")
    bw_p05_gain = _get(a, "bw_p05_gbps") / _get(b, "bw_p05_gbps") if np.isfinite(_get(b, "bw_p05_gbps")) else float("nan")

    md = (
        "# NUMA 内存防御对比结论\n\n"
        "对比：CPU 固定在 node0（0-3），仅改变内存节点：\n"
        "- Remote：`--membind=2`（node2，无 CPU，且距离 100）\n"
        "- Local：`--membind=0`（node0，本地内存，距离 10）\n\n"
        f"- Remote P50/P95/P99 延迟: {_get(b,'lat_p50_ms'):.2f} / {_get(b,'lat_p95_ms'):.2f} / {_get(b,'lat_p99_ms'):.2f} ms\n"
        f"- Local  P50/P95/P99 延迟: {_get(a,'lat_p50_ms'):.2f} / {_get(a,'lat_p95_ms'):.2f} / {_get(a,'lat_p99_ms'):.2f} ms\n\n"
        f"- **尾延迟收敛**：P95 延迟约改善 {lat_p95_gain:.2f}x；P99 延迟约改善 {lat_p99_gain:.2f}x（越大越好）\n"
        f"- **带宽变化**：P50 带宽约提升 {bw_p50_gain:.2f}x；P05(尾部)带宽约提升 {bw_p05_gain:.2f}x（越大越好）\n\n"
        "生成的图：\n"
        "- mem_latency_box.png\n"
        "- mem_throughput.png\n"
    )
    (out_dir / "summary.md").write_text(md, encoding="utf-8")

    print(f"[OK] written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

