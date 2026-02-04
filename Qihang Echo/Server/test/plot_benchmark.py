"""Generate professional benchmark comparison plots from `test/benchmark_results.json`.

Outputs:
 - test/benchmark_plots.png (combined figure)
 - test/benchmark_bar.png (avg with error bars)
 - test/benchmark_box.png (boxplot)
 - test/benchmark_lines.png (per-iteration lines)

Usage:
    python test/plot_benchmark.py [path/to/benchmark_results.json]
"""
import json
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime


def load_results(path: str):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    with open(p, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def plot(results, outdir='test'):
    Path(outdir).mkdir(parents=True, exist_ok=True)

    names = []
    times_list = []
    means = []
    stds = []

    for name, r in results.items():
        names.append(name)
        times = np.array(r.get('times', []), dtype=float)
        times_list.append(times)
        means.append(times.mean() if times.size else np.nan)
        stds.append(times.std() if times.size else 0.0)

    # Bar chart with error bars (mean +/- std)
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(names))
    ax.bar(x, np.array(means) * 1000, yerr=np.array(stds) * 1000, capsize=8, color=['#4c72b0', '#55a868'])
    ax.set_xticks(x)
    ax.set_xticklabels([n.replace('cpu-', '').upper() for n in names])
    ax.set_ylabel('Inference Latency (ms)')
    ax.set_title('Average Inference Latency (mean ± std)')
    for i, v in enumerate(means):
        ax.text(i, v * 1000 + max(stds) * 50, f"{v*1000:.0f} ms", ha='center', va='bottom', fontsize=10)
    fig.tight_layout()
    fig.savefig(Path(outdir) / 'benchmark_bar.png', dpi=300)

    # Boxplot
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.boxplot([t * 1000 for t in times_list], labels=[n.replace('cpu-', '').upper() for n in names], notch=True)
    ax.set_ylabel('Inference Latency (ms)')
    ax.set_title('Latency Distribution (per-iteration)')
    fig.tight_layout()
    fig.savefig(Path(outdir) / 'benchmark_box.png', dpi=300)

    # Line plots per iteration
    fig, ax = plt.subplots(figsize=(10, 4))
    maxlen = max((len(t) for t in times_list))
    xs = np.arange(1, maxlen + 1)
    for name, times in zip(names, times_list):
        y = np.array(times) * 1000
        ax.plot(np.arange(1, len(y) + 1), y, marker='o', label=name.replace('cpu-', '').upper())
    ax.set_xlabel('Iteration')
    ax.set_ylabel('Latency (ms)')
    ax.set_title('Per-iteration Latency')
    ax.legend()
    fig.tight_layout()
    fig.savefig(Path(outdir) / 'benchmark_lines.png', dpi=300)

    # Combined figure
    fig, axs = plt.subplots(1, 3, figsize=(15, 4))
    axs[0].bar(x, np.array(means) * 1000, yerr=np.array(stds) * 1000, capsize=8, color=['#4c72b0', '#55a868'])
    axs[0].set_xticks(x)
    axs[0].set_xticklabels([n.replace('cpu-', '').upper() for n in names])
    axs[0].set_ylabel('Latency (ms)')
    axs[0].set_title('Mean ± Std')

    axs[1].boxplot([t * 1000 for t in times_list], labels=[n.replace('cpu-', '').upper() for n in names], notch=True)
    axs[1].set_title('Distribution')

    for name, times in zip(names, times_list):
        y = np.array(times) * 1000
        axs[2].plot(np.arange(1, len(y) + 1), y, marker='o', label=name.replace('cpu-', '').upper())
    axs[2].set_title('Per-iteration')
    axs[2].set_xlabel('Iteration')
    axs[2].legend()

    fig.suptitle(f"ASR Benchmark ({datetime.now().strftime('%Y-%m-%d %H:%M')})", fontsize=14)
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig(Path(outdir) / 'benchmark_plots.png', dpi=300)

    print(f"Saved plots to {outdir}/")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'test/benchmark_asr_results.json'
    data = load_results(path)
    results = data.get('results', {})
    plot(results)

