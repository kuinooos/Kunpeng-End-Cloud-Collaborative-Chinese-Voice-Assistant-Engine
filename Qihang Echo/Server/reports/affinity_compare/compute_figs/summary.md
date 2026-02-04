# Affinity 对比结论

## 指标（越低越好）

- Baseline P50/P95/P99: 1692.71 / 1951.06 / 1990.00 ms
- Affinity P50/P95/P99: 1581.40 / 2267.67 / 2423.72 ms

## 亮点解读

- **延迟变化（baseline→affinity）**：P50 改善 1.07x（6.6%↓, ms）；P95 退化 1.16x（16.2%↑, ms）；P99 退化 1.22x（21.8%↑, ms）（受负载/核划分影响）。
- **算力隔离**：采样到的 CPU 核数量（baseline vs affinity）= 3 vs 1。
- **内存占用稳定性（侧证）**：RSS 峰值 baseline vs affinity = 769.98828125 MB vs 779.40234375 MB。

生成的图：
- latency_box.png
- latency_percentiles.png
- cpu_rss_timeseries.png
- cpu_core_migration.png
