# Oil Supply Chain Stress Network Analysis

A network-based stress model of the global oil supply chain, comparing a pre-conflict baseline (Feb 15, 2026) against a post-Hormuz-closure scenario (Mar 6, 2026).

## Overview

The script builds a directed weighted graph of 32 supply-chain nodes spanning upstream producers, transit chokepoints, refiners, end consumers, financial actors, alternative supplies, and strategic reserves. Each node carries a calibrated **stress index** (0–100) derived from disruption probability, impact severity, and network contagion. Three publication-quality figures are generated.

## Physics / Model

```
node_stress(i, t) = Σ_k [ disruption_prob_k × impact_k × contagion_k(i) ]
edge_weight(i→j)  = trade_flow_mb_d × dependency_ratio × (1 / substitutability)
stress_index       ∈ [0, 100]   (calibrated to IEA/EIA/Kpler Feb–Mar 2026 data)
network topology   = directed weighted graph G(V, E, w)
layout             = spring_layout with sector cluster constraints
```

Stress levels:

| Range | Label |
|-------|-------|
| 0–29  | LOW   |
| 30–59 | MOD   |
| 60–79 | HIGH  |
| 80–100| CRIT  |

## Output Figures

| File | Description |
|------|-------------|
| `fig1_network_comparison.png` | Side-by-side network graphs: Feb 15 vs Mar 6 |
| `fig2_analytics_dashboard.png` | 5-panel dashboard: stress bars, delta lollipop, sector means, Brent price, dependency heatmap |
| `fig3_network_metrics.png` | Top-20 nodes ranked by betweenness centrality, PageRank, and clustering coefficient |

Figures are saved to `/mnt/user-data/outputs/` if that directory exists, otherwise to the script's own directory.

## Requirements

```
numpy
pandas
matplotlib
networkx
seaborn
scipy
```

Install with:

```bash
pip install numpy pandas matplotlib networkx seaborn scipy
```

## Usage

```bash
python oil_stress_analysis.py
```

## Key Findings (Mar 6, 2026 scenario)

- **Mean network stress** rose from 32.7 → 63.7 (+95%) after Hormuz closure
- **Critical nodes (stress ≥ 80)**: 0 → 9 (Hormuz, Qatar LNG, Ship Insurance, Iran, Iraq, Oil Futures, Power Gen, India Refining, Japan/S.Korea)
- **Brent crude** surged from $67 → $83/bbl (+24%)
- **Finance sector** experienced the sharpest mean stress increase (+46.3 points)
- **Top collapsed flows**: Iran→Hormuz, Iraq→Hormuz, Qatar→Hormuz all dropped by ~0.85 in dependency weight
- **Surging mitigation flows**: IEA reserves, China SPR, and US LNG exports all activated

## Data Sources

Calibrated to IEA, EIA STEO, Kpler, and Wikipedia data for the Feb–Mar 2026 period.
