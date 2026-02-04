#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Generate professional comparison figures for baseline vs affinity runs.

Input: two JSON files produced by tools/affinity_benchmark.py
Output: multiple PNG figures in an output directory.

Figures:
- latency_box.png            latency distribution (box)
- latency_percentiles.png    p50/p95/p99 bar comparison
- cpu_rss_timeseries.png     CPU% + RSS time-series
- cpu_core_migration.png     CPU core index over time (migration/isolation)

Requires: matplotlib (optional: numpy)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _p(report: dict[str, Any], key: str) -> float:
    v = report.get("summary", {}).get(key)
    return float(v) if v is not None else float("nan")


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


def _title(b: dict[str, Any], a: dict[str, Any]) -> str:
    bm = b.get("meta", {})
    am = a.get("meta", {})
    return (
        f"Affinity Comparison | engine={bm.get('engine')} | loops={bm.get('loops')} | "
        f"audio={bm.get('audio_seconds')}s@{bm.get('sample_rate')}Hz\n"
        f"baseline: {bm.get('host')} | affinity: {am.get('host')}"
    )


def plot_latency_box(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    b_lat = np.asarray(b.get("latency_ms", []), dtype=float)
    a_lat = np.asarray(a.get("latency_ms", []), dtype=float)

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.boxplot([b_lat, a_lat], labels=["Baseline (no pin)", "Affinity pinned"], showmeans=True)
    ax.set_ylabel("Inference latency (ms)")
    ax.set_title(_title(b, a))
    ax.grid(True, axis="y")

    fig.tight_layout()
    fig.savefig(out_dir / "latency_box.png")
    plt.close(fig)


def plot_percentiles(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    labels = ["P50", "P95", "P99"]
    b_vals = [_p(b, "p50_ms"), _p(b, "p95_ms"), _p(b, "p99_ms")]
    a_vals = [_p(a, "p50_ms"), _p(a, "p95_ms"), _p(a, "p99_ms")]

    x = np.arange(len(labels))
    w = 0.36

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.bar(x - w / 2, b_vals, width=w, label="Baseline (no pin)")
    ax.bar(x + w / 2, a_vals, width=w, label="Affinity pinned")

    for i, v in enumerate(b_vals):
        ax.text(x[i] - w / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    for i, v in enumerate(a_vals):
        ax.text(x[i] + w / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Tail latency stabilization (lower is better)")
    ax.legend(loc="upper right")
    ax.grid(True, axis="y")

    fig.tight_layout()
    fig.savefig(out_dir / "latency_percentiles.png")
    plt.close(fig)


def _extract_series(r: dict[str, Any]):
    s = r.get("samples", [])
    t = np.asarray([x.get("t") for x in s], dtype=float)
    if t.size:
        t = t - t[0]
    cpu = np.asarray([x.get("cpu_percent") for x in s], dtype=float)
    rss = np.asarray([x.get("rss_mb") for x in s], dtype=float)
    core = np.asarray([x.get("cpu_num") for x in s], dtype=float)
    return t, cpu, rss, core


def plot_cpu_rss(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    bt, bcpu, brss, _ = _extract_series(b)
    at, acpu, arss, _ = _extract_series(a)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.2, 5.6), sharex=True)

    ax1.plot(bt, bcpu, label="Baseline", linewidth=1.4)
    ax1.plot(at, acpu, label="Affinity", linewidth=1.4)
    ax1.set_ylabel("Process CPU%")
    ax1.legend(loc="upper right")

    ax2.plot(bt, brss, label="Baseline", linewidth=1.4)
    ax2.plot(at, arss, label="Affinity", linewidth=1.4)
    ax2.set_ylabel("RSS (MB)")
    ax2.set_xlabel("Time (s)")

    fig.suptitle("Compute isolation & memory stability")
    fig.tight_layout()
    fig.savefig(out_dir / "cpu_rss_timeseries.png")
    plt.close(fig)


def plot_core_migration(b: dict[str, Any], a: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    bt, _, _, bcore = _extract_series(b)
    at, _, _, acore = _extract_series(a)

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.scatter(bt, bcore, s=9, alpha=0.6, label="Baseline")
    ax.scatter(at, acore, s=9, alpha=0.6, label="Affinity")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("CPU core (sampled)")
    ax.set_title("CPU core migration (lower dispersion = better isolation)")
    ax.legend(loc="upper right")
    ax.grid(True)

    fig.tight_layout()
    fig.savefig(out_dir / "cpu_core_migration.png")
    plt.close(fig)


def _describe_change(affinity_val: float, baseline_val: float, unit: str = "ms") -> str:
    """Describe change from baseline -> affinity for a lower-is-better metric.

    ratio = affinity / baseline
      - ratio < 1: improved
      - ratio > 1: regressed
    """

    if not (np.isfinite(affinity_val) and np.isfinite(baseline_val) and baseline_val != 0):
        return "N/A"

    ratio = affinity_val / baseline_val
    pct = (ratio - 1.0) * 100.0

    if ratio < 1.0:
        improve_x = 1.0 / ratio
        return f"改善 {improve_x:.2f}x（{abs(pct):.1f}%↓, {unit}）"
    if ratio > 1.0:
        return f"退化 {ratio:.2f}x（{abs(pct):.1f}%↑, {unit}）"
    return f"持平 1.00x（0.0%, {unit}）"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate affinity comparison figures")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--affinity", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    _style()

    b = _load(Path(args.baseline))
    a = _load(Path(args.affinity))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_latency_box(b, a, out_dir)
    plot_percentiles(b, a, out_dir)
    plot_cpu_rss(b, a, out_dir)
    plot_core_migration(b, a, out_dir)

    # Also write a small summary markdown
    summary_md = out_dir / "summary.md"

    b_p50, b_p95, b_p99 = _p(b, "p50_ms"), _p(b, "p95_ms"), _p(b, "p99_ms")
    a_p50, a_p95, a_p99 = _p(a, "p50_ms"), _p(a, "p95_ms"), _p(a, "p99_ms")

    p50_desc = _describe_change(a_p50, b_p50, unit="ms")
    p95_desc = _describe_change(a_p95, b_p95, unit="ms")
    p99_desc = _describe_change(a_p99, b_p99, unit="ms")

    text = (
        "# Affinity 对比结论\n\n"
        "## 指标（越低越好）\n\n"
        f"- Baseline P50/P95/P99: {b_p50:.2f} / {b_p95:.2f} / {b_p99:.2f} ms\n"
        f"- Affinity P50/P95/P99: {a_p50:.2f} / {a_p95:.2f} / {a_p99:.2f} ms\n\n"
        "## 亮点解读\n\n"
        f"- **延迟变化（baseline→affinity）**：P50 {p50_desc}；P95 {p95_desc}；P99 {p99_desc}（受负载/核划分影响）。\n"
        f"- **算力隔离**：采样到的 CPU 核数量（baseline vs affinity）= {b.get('summary',{}).get('cpu_unique_cores')} vs {a.get('summary',{}).get('cpu_unique_cores')}。\n"
        f"- **内存占用稳定性（侧证）**：RSS 峰值 baseline vs affinity = {b.get('summary',{}).get('rss_peak_mb')} MB vs {a.get('summary',{}).get('rss_peak_mb')} MB。\n"
        "\n"
        "生成的图：\n"
        "- latency_box.png\n"
        "- latency_percentiles.png\n"
        "- cpu_rss_timeseries.png\n"
        "- cpu_core_migration.png\n"
    )
    summary_md.write_text(text, encoding="utf-8")

    print(f"[OK] figures written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

