# NUMA 内存防御对比结论

对比：CPU 固定在 node0（0-3），仅改变内存节点：
- Remote：`--membind=2`（node2，无 CPU，且距离 100）
- Local：`--membind=0`（node0，本地内存，距离 10）

- Remote P50/P95/P99 延迟: 91.27 / 110.63 / 147.45 ms
- Local  P50/P95/P99 延迟: 93.51 / 108.87 / 109.73 ms

- **尾延迟收敛**：P95 延迟约改善 1.02x（越大越好）
- **带宽提升**：P50 带宽约提升 0.98x（越大越好）

生成的图：
- mem_latency_box.png
- mem_throughput.png
