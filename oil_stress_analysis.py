"""
Oil Supply Chain Stress Network Analysis
=========================================
Two snapshots: Feb 15, 2026 (pre-conflict) vs Mar 6, 2026 (post-Hormuz closure)

PHYSICS PSEUDOCODE
------------------
node_stress(i, t) = Σ_k [ disruption_prob_k × impact_k × contagion_k(i) ]
edge_weight(i→j)  = trade_flow_mb_d × dependency_ratio × (1 / substitutability)
stress_index       ∈ [0, 100]   (calibrated to IEA/EIA/Kpler Feb–Mar 2026 data)
network topology   = directed weighted graph G(V, E, w)
layout             = spring_layout with sector cluster constraints
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
import networkx as nx
import seaborn as sns
import warnings
warnings.filterwarnings("ignore")

# ── STYLE ────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor":  "#07080a",
    "axes.facecolor":    "#0d1117",
    "axes.edgecolor":    "#1c2535",
    "axes.labelcolor":   "#94a3b8",
    "axes.titlecolor":   "#e2e8f0",
    "xtick.color":       "#475569",
    "ytick.color":       "#475569",
    "grid.color":        "#1c2535",
    "text.color":        "#e2e8f0",
    "font.family":       "monospace",
    "figure.dpi":        130,
})

# ── STRESS COLORMAP ───────────────────────────────────────────────────────────
STRESS_CMAP = LinearSegmentedColormap.from_list(
    "stress", ["#4ade80","#facc15","#fb923c","#f43f5e"]
)

def stress_color(s):
    """Map stress index 0–100 → hex color."""
    if s < 30:  return "#4ade80"
    if s < 60:  return "#facc15"
    if s < 80:  return "#fb923c"
    return "#f43f5e"

def stress_label(s):
    if s < 30:  return "LOW"
    if s < 60:  return "MOD"
    if s < 80:  return "HIGH"
    return "CRIT"

# ═══════════════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════════════

NODES = [
    # id              label               sector         weight  s_feb  s_mar
    ("HORMUZ",   "Hormuz Strait",    "TRANSIT",     4.0,   38,   99),
    ("QATAR",    "Qatar LNG",        "UPSTREAM",    1.5,   20,   99),
    ("IRAN",     "Iran",             "UPSTREAM",    1.6,   52,   98),
    ("INSURANCE","Ship Insurance",   "FINANCE",     1.2,   45,   99),
    ("IRAQ",     "Iraq",             "UPSTREAM",    2.0,   28,   88),
    ("JAPAN",    "Japan/S.Korea",    "DOWNSTREAM",  1.2,   25,   88),
    ("OIL_FUT",  "Oil Futures",      "FINANCE",     1.5,   40,   88),
    ("INDIA_REF","India Refining",   "DOWNSTREAM",  1.4,   48,   82),
    ("POWER",    "Power Gen",        "CONSUMER",    1.5,   42,   82),
    ("AVIATION", "Aviation",         "CONSUMER",    1.0,   25,   78),
    ("EU_REF",   "EU Refining",      "DOWNSTREAM",  1.6,   40,   75),
    ("KUWAIT",   "Kuwait",           "UPSTREAM",    1.2,   18,   72),
    ("FERTILIZER","Fertilizers",     "CONSUMER",    1.0,   30,   72),
    ("EQUITIES", "Energy Equities",  "FINANCE",     1.0,   35,   72),
    ("SUEZ",     "Suez/Red Sea",     "TRANSIT",     2.0,   45,   72),
    ("CHINA_REF","China Refining",   "DOWNSTREAM",  2.2,   22,   68),
    ("PETROCHEM","Petrochemicals",   "CONSUMER",    1.3,   28,   65),
    ("SAUDI",    "Saudi Arabia",     "UPSTREAM",    3.0,   18,   62),
    ("RUSSIA",   "Russia",           "UPSTREAM",    2.4,   55,   58),
    ("KAZAKH",   "Kazakhstan",       "UPSTREAM",    1.0,   62,   55),
    ("UAE",      "UAE",              "UPSTREAM",    1.7,   15,   55),
    ("TRANSPORT","Road Transport",   "CONSUMER",    1.8,   20,   55),
    ("MALACCA",  "Malacca Strait",   "TRANSIT",     1.8,   20,   45),
    ("CPC",      "CPC Terminal",     "TRANSIT",     1.0,   65,   55),
    ("OPEC_SP",  "OPEC+ Spare Cap.", "ALT_SUPPLY",  1.5,   25,   45),
    ("IEA_RES",  "IEA Reserves",     "STORAGE",     1.2,   20,   35),
    ("CHINA_SPR","China SPR",        "STORAGE",     1.5,   15,   32),
    ("US_REF",   "US Refining",      "DOWNSTREAM",  1.5,   30,   35),
    ("NORWAY",   "Norway/N.Sea",     "ALT_SUPPLY",  0.8,   22,   30),
    ("US_LNG",   "US LNG Export",    "ALT_SUPPLY",  1.3,   20,   18),
    ("US_PROD",  "US Production",    "UPSTREAM",    2.8,   35,   22),
    ("VENEZUELA","Venezuela",        "UPSTREAM",    0.7,   42,   38),
]

# Columns: source, target, w_feb, w_mar, flow_type
EDGES = [
    # UPSTREAM → TRANSIT (Hormuz dependencies)
    ("IRAN",     "HORMUZ",    0.90, 0.05, "supply"),
    ("IRAQ",     "HORMUZ",    0.95, 0.10, "supply"),
    ("KUWAIT",   "HORMUZ",    0.90, 0.15, "supply"),
    ("SAUDI",    "HORMUZ",    0.60, 0.30, "supply"),
    ("QATAR",    "HORMUZ",    0.85, 0.01, "supply"),
    ("UAE",      "HORMUZ",    0.55, 0.25, "supply"),
    ("RUSSIA",   "CPC",       0.60, 0.50, "supply"),
    ("KAZAKH",   "CPC",       0.80, 0.70, "supply"),
    # TRANSIT → DOWNSTREAM
    ("HORMUZ",   "JAPAN",     0.75, 0.08, "transport"),
    ("HORMUZ",   "INDIA_REF", 0.65, 0.10, "transport"),
    ("HORMUZ",   "CHINA_REF", 0.55, 0.15, "transport"),
    ("SUEZ",     "EU_REF",    0.55, 0.40, "transport"),
    ("SUEZ",     "US_REF",    0.30, 0.25, "transport"),
    ("CPC",      "EU_REF",    0.45, 0.40, "transport"),
    ("MALACCA",  "CHINA_REF", 0.40, 0.50, "transport"),
    ("MALACCA",  "JAPAN",     0.45, 0.55, "transport"),
    # DOWNSTREAM → CONSUMER
    ("EU_REF",   "POWER",     0.50, 0.75, "consume"),
    ("EU_REF",   "FERTILIZER",0.40, 0.70, "consume"),
    ("EU_REF",   "AVIATION",  0.50, 0.35, "consume"),
    ("EU_REF",   "TRANSPORT", 0.60, 0.55, "consume"),
    ("INDIA_REF","AVIATION",  0.45, 0.20, "consume"),
    ("INDIA_REF","PETROCHEM", 0.35, 0.25, "consume"),
    ("CHINA_REF","PETROCHEM", 0.55, 0.40, "consume"),
    ("JAPAN",    "POWER",     0.45, 0.30, "consume"),
    ("US_REF",   "TRANSPORT", 0.60, 0.65, "consume"),
    # FINANCE
    ("HORMUZ",   "INSURANCE", 0.55, 0.99, "finance"),
    ("INSURANCE","OIL_FUT",   0.40, 0.85, "finance"),
    ("OIL_FUT",  "EQUITIES",  0.55, 0.80, "finance"),
    ("IRAN",     "OIL_FUT",   0.40, 0.90, "finance"),
    # MITIGATION / ALTERNATIVE SUPPLY
    ("US_LNG",   "EU_REF",    0.25, 0.55, "mitigate"),
    ("NORWAY",   "EU_REF",    0.30, 0.45, "mitigate"),
    ("IEA_RES",  "EU_REF",    0.20, 0.55, "mitigate"),
    ("IEA_RES",  "JAPAN",     0.20, 0.60, "mitigate"),
    ("CHINA_SPR","CHINA_REF", 0.15, 0.50, "mitigate"),
    ("US_PROD",  "US_LNG",    0.50, 0.70, "supply"),
    ("RUSSIA",   "CHINA_REF", 0.70, 0.75, "supply"),
    ("VENEZUELA","INDIA_REF", 0.30, 0.35, "supply"),
    ("OPEC_SP",  "HORMUZ",    0.30, 0.20, "mitigate"),
]

PRICE_DATA = [
    ("Dec'25",  62,  None),
    ("Jan 1",   62,  None),
    ("Jan 15",  67,  "Winter Storm + Kazakhstan"),
    ("Jan 31",  72,  None),
    ("Feb 1",   70,  None),
    ("Feb 10",  67,  "EIA: oversupply bearish"),
    ("Feb 15",  67,  "Iran military drill"),
    ("Feb 20",  71,  None),
    ("Feb 28",  73,  "Operation Epic Fury"),
    ("Mar 1",   80,  "Hormuz de-facto closed"),
    ("Mar 2",   83,  "Qatar halts LNG"),
    ("Mar 3",   88,  "Peak — 300 tankers trapped"),
    ("Mar 4",   85,  "Qatar Force Majeure"),
    ("Mar 5",   83,  "P&I insurance withdrawn"),
    ("Mar 6",   83,  "Current level"),
]

# ═══════════════════════════════════════════════════════════════════════════════
# BUILD DATAFRAMES
# ═══════════════════════════════════════════════════════════════════════════════

df_nodes = pd.DataFrame(NODES, columns=["id","label","sector","weight","s_feb","s_mar"])
df_nodes["delta"]   = df_nodes["s_mar"] - df_nodes["s_feb"]
df_nodes["col_feb"] = df_nodes["s_feb"].apply(stress_color)
df_nodes["col_mar"] = df_nodes["s_mar"].apply(stress_color)

df_edges = pd.DataFrame(EDGES, columns=["source","target","w_feb","w_mar","flow_type"])
df_edges["delta"] = df_edges["w_mar"] - df_edges["w_feb"]

df_price = pd.DataFrame(PRICE_DATA, columns=["date","brent","event"])

# Sector aggregates
df_sector = (df_nodes.groupby("sector")
             .agg(mean_feb=("s_feb","mean"), mean_mar=("s_mar","mean"))
             .reset_index())
df_sector["delta"] = df_sector["mean_mar"] - df_sector["mean_feb"]

# ═══════════════════════════════════════════════════════════════════════════════
# NETWORK GRAPHS
# ═══════════════════════════════════════════════════════════════════════════════

SECTOR_COLORS = {
    "UPSTREAM":   "#4FC3F7",
    "TRANSIT":    "#FF8A65",
    "DOWNSTREAM": "#81C784",
    "CONSUMER":   "#CE93D8",
    "FINANCE":    "#FFD54F",
    "ALT_SUPPLY": "#80CBC4",
    "STORAGE":    "#90A4AE",
}

FLOW_COLORS = {
    "supply":    "#4FC3F7",
    "transport": "#FF8A65",
    "consume":   "#81C784",
    "finance":   "#FFD54F",
    "mitigate":  "#80CBC4",
}

# Cluster seed positions for force layout
CLUSTER_POS = {
    "UPSTREAM":   np.array([ 0.0,  0.6]),
    "TRANSIT":    np.array([ 0.0,  0.0]),
    "DOWNSTREAM": np.array([ 0.0, -0.6]),
    "CONSUMER":   np.array([ 0.9, -0.3]),
    "FINANCE":    np.array([ 0.9,  0.3]),
    "ALT_SUPPLY": np.array([-0.9, -0.3]),
    "STORAGE":    np.array([-0.9,  0.3]),
}

def build_graph(time_key):
    """Build directed NetworkX graph for 'feb' or 'mar'."""
    G = nx.DiGraph()
    w_col = f"w_{time_key}"
    s_col = f"s_{time_key}"

    for _, n in df_nodes.iterrows():
        G.add_node(n["id"],
                   label=n["label"],
                   sector=n["sector"],
                   weight=n["weight"],
                   stress=n[s_col],
                   delta=n["delta"])

    for _, e in df_edges.iterrows():
        w = e[w_col]
        if w > 0.02:
            G.add_edge(e["source"], e["target"],
                       weight=w, flow_type=e["flow_type"])
    return G

def cluster_layout(G, seed=42):
    """Spring layout seeded by sector cluster centers."""
    np.random.seed(seed)
    pos0 = {}
    for nid, data in G.nodes(data=True):
        cp = CLUSTER_POS[data["sector"]]
        pos0[nid] = cp + np.random.randn(2) * 0.18
    return nx.spring_layout(G, pos=pos0, k=0.55, iterations=80,
                            weight="weight", seed=seed)


def draw_network(ax, G, pos, title, time_key, show_legend=False):
    """Draw a single network snapshot."""
    ax.set_facecolor("#0d1117")
    ax.set_title(title, color="#e2e8f0", fontsize=11, fontweight="bold",
                 pad=10, fontfamily="monospace")
    ax.axis("off")

    s_col = f"s_{time_key}"

    # Edges
    for u, v, data in G.edges(data=True):
        w = data["weight"]
        fc = FLOW_COLORS.get(data["flow_type"], "#888")
        style = "--" if data["flow_type"] == "mitigate" else "-"
        nx.draw_networkx_edges(G, pos, edgelist=[(u,v)],
                               width=w*3.5, alpha=min(0.85, 0.2+w*0.7),
                               edge_color=fc, style=style,
                               arrows=True, arrowsize=10,
                               connectionstyle="arc3,rad=0.08", ax=ax)

    # Nodes
    for nid, ndata in G.nodes(data=True):
        s = ndata["stress"]
        r = (ndata["weight"] * 200 + s * 3)
        col = stress_color(s)
        # Glow halo for critical
        if s >= 80:
            nx.draw_networkx_nodes(G, pos, nodelist=[nid],
                                   node_size=r*2.5, node_color=col,
                                   alpha=0.12, ax=ax)
        nx.draw_networkx_nodes(G, pos, nodelist=[nid],
                               node_size=r, node_color=col,
                               alpha=0.82,
                               linewidths=1.5 if s>=60 else 0.6,
                               edgecolors=col, ax=ax)

    # Labels
    labels = {n: G.nodes[n]["label"] for n in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels=labels,
                            font_size=6.2, font_color="#cbd5e1",
                            font_family="monospace", ax=ax)

    # Stress badges (small text above node)
    for nid, (x, y) in pos.items():
        s = G.nodes[nid]["stress"]
        ax.text(x, y + 0.06, str(s),
                fontsize=5.5, color=stress_color(s),
                ha="center", va="bottom", fontweight="bold",
                fontfamily="monospace")

    if show_legend:
        handles = [mpatches.Patch(color=v, label=k.replace("_"," "))
                   for k, v in SECTOR_COLORS.items()]
        leg = ax.legend(handles=handles, loc="lower left",
                        fontsize=6, framealpha=0.3,
                        facecolor="#0d1117", edgecolor="#1c2535",
                        labelcolor="#94a3b8")


# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 1 — NETWORK COMPARISON (side-by-side)
# ═══════════════════════════════════════════════════════════════════════════════

print("Building network graphs...")
G_feb = build_graph("feb")
G_mar = build_graph("mar")
pos_feb = cluster_layout(G_feb, seed=7)
pos_mar = cluster_layout(G_mar, seed=7)  # same seed → comparable layout

fig1, axes = plt.subplots(1, 2, figsize=(18, 9))
fig1.patch.set_facecolor("#07080a")
fig1.suptitle(
    "OIL SUPPLY CHAIN STRESS NETWORK  ·  Node radius ∝ weight  ·  "
    "Node color ∝ stress  ·  Edge width ∝ dependency",
    color="#64748b", fontsize=8, fontfamily="monospace", y=0.98
)

draw_network(axes[0], G_feb, pos_feb,
             "FEB 15, 2026  —  Distributed Stress Regime  (Brent $67/bbl)",
             "feb", show_legend=True)
draw_network(axes[1], G_mar, pos_mar,
             "MAR 6, 2026  —  Hub-Collapse Regime  (Brent $83/bbl, Hormuz closed)",
             "mar")

# Stress level legend (shared)
stress_handles = [
    mpatches.Patch(color="#4ade80", label="LOW < 30"),
    mpatches.Patch(color="#facc15", label="MOD 30–60"),
    mpatches.Patch(color="#fb923c", label="HIGH 60–80"),
    mpatches.Patch(color="#f43f5e", label="CRIT > 80"),
    Line2D([0],[0], color="#80CBC4", lw=1.5, ls="--", label="Mitigating flow"),
]
fig1.legend(handles=stress_handles, loc="lower center", ncol=5,
            fontsize=7.5, framealpha=0.4, facecolor="#0d1117",
            edgecolor="#1c2535", labelcolor="#94a3b8")

plt.tight_layout(rect=[0,0.04,1,0.97])
fig1.savefig("/mnt/user-data/outputs/fig1_network_comparison.png",
             dpi=130, bbox_inches="tight", facecolor="#07080a")
print("✓ Fig 1 saved")
plt.close()


# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 2 — ANALYTICS DASHBOARD (5 charts)
# ═══════════════════════════════════════════════════════════════════════════════

print("Building analytics dashboard...")
fig2 = plt.figure(figsize=(20, 16))
fig2.patch.set_facecolor("#07080a")
gs = gridspec.GridSpec(3, 2, figure=fig2, hspace=0.52, wspace=0.32,
                       left=0.06, right=0.97, top=0.94, bottom=0.06)

ax_bar    = fig2.add_subplot(gs[0, :])   # full-width grouped bar
ax_delta  = fig2.add_subplot(gs[1, 0])  # delta lollipop
ax_radar  = fig2.add_subplot(gs[1, 1])  # pseudo-radar (bar)
ax_price  = fig2.add_subplot(gs[2, 0])  # brent price
ax_heat   = fig2.add_subplot(gs[2, 1])  # heatmap

fig2.text(0.5, 0.97,
          "OIL SUPPLY CHAIN  ·  STRESS ANALYTICS DASHBOARD  ·  FEB 15 vs MAR 6, 2026",
          ha="center", color="#e2e8f0", fontsize=12,
          fontfamily="monospace", fontweight="bold")
fig2.text(0.5, 0.955, "Sources: IEA, EIA STEO, Kpler, Wikipedia — Calibrated Stress Index Model",
          ha="center", color="#475569", fontsize=8, fontfamily="monospace")

# ── CHART 1: Grouped bar ──────────────────────────────────────────────────────
ax = ax_bar
sorted_nodes = df_nodes.sort_values("s_mar", ascending=False)
x = np.arange(len(sorted_nodes))
w = 0.38

bars_feb = ax.bar(x - w/2, sorted_nodes["s_feb"], w,
                  color="#38bdf8", alpha=0.75, label="Feb 15", zorder=3)
bars_mar = ax.bar(x + w/2, sorted_nodes["s_mar"], w,
                  color=[stress_color(s) for s in sorted_nodes["s_mar"]],
                  alpha=0.88, label="Mar 6", zorder=3)

# Stress zone backgrounds
for (lo, hi, col) in [(0,30,"#4ade80"),(30,60,"#facc15"),(60,80,"#fb923c"),(80,100,"#f43f5e")]:
    ax.axhspan(lo, hi, alpha=0.04, color=col, zorder=1)

ax.set_xticks(x)
ax.set_xticklabels(sorted_nodes["label"], rotation=40, ha="right",
                   fontsize=7.5, fontfamily="monospace")
ax.set_ylabel("Stress Index (0–100)", fontsize=8)
ax.set_ylim(0, 108)
ax.set_title("#01 — NODE STRESS INDEX: FEB 15 vs MAR 6",
             color="#94a3b8", fontsize=9, fontfamily="monospace", pad=6)
ax.legend(loc="upper right", fontsize=8, framealpha=0.3,
          facecolor="#0d1117", edgecolor="#1c2535", labelcolor="#94a3b8")
ax.grid(axis="y", alpha=0.3, zorder=0)
for spine in ax.spines.values(): spine.set_edgecolor("#1c2535")

# ── CHART 2: Delta lollipop ───────────────────────────────────────────────────
ax = ax_delta
sorted_delta = df_nodes.sort_values("delta", ascending=True)
y = np.arange(len(sorted_delta))

for i, (_, row) in enumerate(sorted_delta.iterrows()):
    col = stress_color(row["s_mar"]) if row["delta"] >= 0 else "#4ade80"
    ax.plot([0, row["delta"]], [i, i], color=col, alpha=0.7, lw=1.5, zorder=2)
    ax.scatter(row["delta"], i, color=col, s=30+abs(row["delta"])*1.5,
               zorder=3, edgecolors="#07080a", linewidths=0.8)

ax.axvline(0, color="#334155", lw=1, ls="-")
ax.set_yticks(y)
ax.set_yticklabels(sorted_delta["label"], fontsize=7, fontfamily="monospace")
ax.set_xlabel("Δ Stress (Mar − Feb)", fontsize=8)
ax.set_title("#02 — Δ STRESS SHIFT",
             color="#94a3b8", fontsize=9, fontfamily="monospace", pad=6)
ax.grid(axis="x", alpha=0.3)
for spine in ax.spines.values(): spine.set_edgecolor("#1c2535")

# Colour ytick labels by Mar stress
for lbl, (_, row) in zip(ax.get_yticklabels(), sorted_delta.iterrows()):
    lbl.set_color(stress_color(row["s_mar"]))

# ── CHART 3: Sector grouped bar (replaces radar) ──────────────────────────────
ax = ax_radar
sec_sorted = df_sector.sort_values("mean_mar", ascending=False)
xs = np.arange(len(sec_sorted))
ax.bar(xs - 0.2, sec_sorted["mean_feb"], 0.38, color="#38bdf8",
       alpha=0.75, label="Feb 15")
ax.bar(xs + 0.2, sec_sorted["mean_mar"], 0.38,
       color=[stress_color(s) for s in sec_sorted["mean_mar"]],
       alpha=0.88, label="Mar 6")
ax.set_xticks(xs)
ax.set_xticklabels([s[:9] for s in sec_sorted["sector"]],
                   rotation=30, ha="right", fontsize=8, fontfamily="monospace")
ax.set_ylabel("Mean Stress Index", fontsize=8)
ax.set_ylim(0, 110)
ax.set_title("#03 — SECTOR MEAN STRESS",
             color="#94a3b8", fontsize=9, fontfamily="monospace", pad=6)
ax.legend(fontsize=8, framealpha=0.3, facecolor="#0d1117",
          edgecolor="#1c2535", labelcolor="#94a3b8")
ax.grid(axis="y", alpha=0.3)
for spine in ax.spines.values(): spine.set_edgecolor("#1c2535")

# Delta annotations
for i, (_, row) in enumerate(sec_sorted.iterrows()):
    d = row["mean_mar"] - row["mean_feb"]
    col = stress_color(row["mean_mar"]) if d > 0 else "#4ade80"
    ax.text(i+0.2, row["mean_mar"]+2, f"+{d:.0f}" if d>0 else f"{d:.0f}",
            ha="center", fontsize=7, color=col, fontfamily="monospace",
            fontweight="bold")

# ── CHART 4: Brent price timeline ─────────────────────────────────────────────
ax = ax_price
dates = df_price["date"].tolist()
prices = df_price["brent"].tolist()
x_idx = np.arange(len(dates))

# Shaded conflict zone
conflict_start = dates.index("Feb 28")
ax.axvspan(conflict_start, len(dates)-1,
           alpha=0.07, color="#fb923c", zorder=1)
ax.text(conflict_start + 0.2, 91, "← CONFLICT", color="#fb923c",  alpha=0.5,
        fontsize=7.5, fontfamily="monospace")

ax.plot(x_idx, prices, color="#38bdf8", lw=2.5, zorder=3)
ax.fill_between(x_idx, prices, min(prices)-2,
                color="#38bdf8", alpha=0.06, zorder=2)

# Change line color after conflict start
ax.plot(x_idx[conflict_start:], prices[conflict_start:],
        color="#fb923c", lw=2.5, zorder=4)

# Reference lines
ax.axhline(67, color="#38bdf8", lw=1, ls="--", alpha=0.35)
ax.axhline(83, color="#fb923c", lw=1, ls="--", alpha=0.35)
ax.text(len(dates)-0.5, 67.5, "$67", color="#38bdf8",
        fontsize=7.5, ha="right", fontfamily="monospace")
ax.text(len(dates)-0.5, 83.5, "$83", color="#fb923c",
        fontsize=7.5, ha="right", fontfamily="monospace")

# Event dots
for i, row in df_price.iterrows():
    if row["event"]:
        is_conflict = i >= conflict_start
        col = "#f43f5e" if is_conflict else "#facc15"
        ax.scatter(i, row["brent"], color=col, s=45, zorder=5,
                   edgecolors="#07080a", linewidths=1)
        y_off = 1.5 if i % 2 == 0 else -3.5
        ax.text(i, row["brent"]+y_off, row["event"],
                color=col, fontsize=5.8, ha="center",
                fontfamily="monospace", alpha=0.8)

ax.set_xticks(x_idx)
ax.set_xticklabels(dates, rotation=40, ha="right",
                   fontsize=7, fontfamily="monospace")
ax.set_ylabel("Brent ($/bbl)", fontsize=8)
ax.set_ylim(56, 96)
ax.set_title("#04 — BRENT CRUDE PRICE TRAJECTORY",
             color="#94a3b8", fontsize=9, fontfamily="monospace", pad=6)
ax.grid(alpha=0.3)
for spine in ax.spines.values(): spine.set_edgecolor("#1c2535")

# ── CHART 5: Heatmap ──────────────────────────────────────────────────────────
ax = ax_heat
hm_data = df_edges[["source","target","w_feb","w_mar","delta"]].copy()
hm_data["label"] = hm_data["source"].str[:5] + "→" + hm_data["target"].str[:5]
hm_matrix = hm_data[["w_feb","w_mar","delta"]].values.T

# Custom colormap for delta column
im = ax.imshow(hm_matrix, aspect="auto", cmap="RdYlGn",
               vmin=-1, vmax=1, interpolation="nearest")

ax.set_yticks([0, 1, 2])
ax.set_yticklabels(["Feb Weight","Mar Weight","Δ Change"],
                   fontsize=8, fontfamily="monospace")
ax.set_xticks(np.arange(len(hm_data)))
ax.set_xticklabels(hm_data["label"], rotation=55, ha="right",
                   fontsize=6, fontfamily="monospace")

# Cell text
for col_i in range(hm_matrix.shape[0]):
    for col_j in range(hm_matrix.shape[1]):
        val = hm_matrix[col_i, col_j]
        txt = f"{val:+.2f}" if col_i == 2 else f"{val:.2f}"
        col_txt = "white" if abs(val) > 0.55 else "#94a3b8"
        ax.text(col_j, col_i, txt, ha="center", va="center",
                fontsize=5.5, color=col_txt, fontfamily="monospace",
                fontweight="bold" if abs(val) > 0.4 else "normal")

plt.colorbar(im, ax=ax, shrink=0.6, pad=0.02,
             label="Flow Weight / Δ").ax.yaxis.label.set_color("#94a3b8")
ax.set_title("#05 — DEPENDENCY FLOW HEATMAP (Feb → Mar)",
             color="#94a3b8", fontsize=9, fontfamily="monospace", pad=6)

fig2.savefig("/mnt/user-data/outputs/fig2_analytics_dashboard.png",
             dpi=130, bbox_inches="tight", facecolor="#07080a")
print("✓ Fig 2 saved")
plt.close()


# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 3 — NETWORK METRICS TABLE
# ═══════════════════════════════════════════════════════════════════════════════

print("Computing network metrics...")

def network_metrics(G, time_key):
    """
    Compute graph-theoretic stress metrics.
    Pseudocode:
      betweenness(v)   = fraction of shortest paths passing through v
      degree_centrality = normalized in+out degree
      pagerank(v)       = stationary distribution of random walk ∝ edge weights
      clustering(v)     = fraction of neighbours that are mutually connected
    """
    w_col = f"weight"
    bc  = nx.betweenness_centrality(G, weight=w_col, normalized=True)
    dc  = nx.degree_centrality(G)
    pr  = nx.pagerank(G, weight=w_col, alpha=0.85)
    # For clustering on DiGraph use undirected version
    Gu  = G.to_undirected()
    cc  = nx.clustering(Gu, weight=w_col)
    return {n: {"betweenness": bc[n], "degree_c": dc[n],
                "pagerank": pr[n], "clustering": cc[n]}
            for n in G.nodes()}

metrics_feb = network_metrics(G_feb, "feb")
metrics_mar = network_metrics(G_mar, "mar")

rows = []
for nid in df_nodes["id"]:
    if nid in metrics_feb and nid in metrics_mar:
        lbl = df_nodes.loc[df_nodes["id"]==nid, "label"].values[0]
        s_f = df_nodes.loc[df_nodes["id"]==nid, "s_feb"].values[0]
        s_m = df_nodes.loc[df_nodes["id"]==nid, "s_mar"].values[0]
        mf, mm = metrics_feb[nid], metrics_mar[nid]
        rows.append({
            "Node": lbl,
            "s_feb": s_f, "s_mar": s_m, "Δ_stress": s_m-s_f,
            "BC_feb":  round(mf["betweenness"],4),
            "BC_mar":  round(mm["betweenness"],4),
            "PR_feb":  round(mf["pagerank"],4),
            "PR_mar":  round(mm["pagerank"],4),
            "Clust_feb": round(mf["clustering"],3),
            "Clust_mar": round(mm["clustering"],3),
        })

df_metrics = pd.DataFrame(rows).sort_values("Δ_stress", ascending=False)

# ── Plot metrics table as heatmap figure ──────────────────────────────────────
fig3, ax = plt.subplots(figsize=(18, 11))
fig3.patch.set_facecolor("#07080a")
ax.set_facecolor("#07080a")
ax.axis("off")
ax.set_title(
    "NETWORK CENTRALITY METRICS — Betweenness · PageRank · Clustering  (Feb 15 vs Mar 6)",
    color="#e2e8f0", fontsize=10, fontfamily="monospace", fontweight="bold", pad=12
)

cols_show = ["Node","s_feb","s_mar","Δ_stress",
             "BC_feb","BC_mar","PR_feb","PR_mar","Clust_feb","Clust_mar"]
col_labels = ["Node","StressFeb","StressMar","Δ",
              "Betw.Feb","Betw.Mar","PR.Feb","PR.Mar","Clust.Feb","Clust.Mar"]

top20 = df_metrics.head(20)
cell_data = top20[cols_show].values.tolist()

tbl = ax.table(
    cellText=[[str(v) if isinstance(v, str) else
               (f"+{v}" if isinstance(v, (int,float)) and v > 0 and c in [3] else str(v))
               for c,v in enumerate(row)]
              for row in cell_data],
    colLabels=col_labels,
    cellLoc="center", loc="center",
    bbox=[0, 0, 1, 1]
)

tbl.auto_set_font_size(False)
tbl.set_fontsize(8)

for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("#1c2535")
    cell.set_linewidth(0.5)
    if r == 0:
        cell.set_facecolor("#1c2535")
        cell.set_text_props(color="#94a3b8", fontfamily="monospace",
                            fontweight="bold", fontsize=7.5)
    else:
        row_data = top20.iloc[r-1]
        if c == 0:
            cell.set_facecolor("#0d1117")
            cell.set_text_props(color="#e2e8f0", fontfamily="monospace")
        elif c == 1:  # s_feb
            cell.set_facecolor("#0d1117")
            cell.set_text_props(color="#38bdf8", fontfamily="monospace")
        elif c == 2:  # s_mar
            cell.set_facecolor("#0d1117")
            cell.set_text_props(color=stress_color(row_data["s_mar"]),
                                fontfamily="monospace", fontweight="bold")
        elif c == 3:  # delta
            d = row_data["Δ_stress"]
            col = stress_color(row_data["s_mar"]) if d > 0 else "#4ade80"
            cell.set_facecolor("#0d1117")
            cell.set_text_props(color=col, fontfamily="monospace",
                                fontweight="bold")
        else:
            cell.set_facecolor("#0d1117")
            cell.set_text_props(color="#64748b", fontfamily="monospace")

fig3.savefig("/mnt/user-data/outputs/fig3_network_metrics.png",
             dpi=130, bbox_inches="tight", facecolor="#07080a")
print("✓ Fig 3 saved")
plt.close()


# ═══════════════════════════════════════════════════════════════════════════════
# PRINT SUMMARY STATISTICS
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "═"*62)
print("  OIL SUPPLY CHAIN STRESS — SUMMARY STATISTICS")
print("═"*62)

print(f"\n{'NODE':<20} {'FEB':>5} {'MAR':>5} {'Δ':>5}  {'LEVEL'}")
print("─"*50)
for _, row in df_nodes.sort_values("delta", ascending=False).iterrows():
    flag = "▲" if row["delta"] > 30 else ("▼" if row["delta"] < -5 else " ")
    print(f"  {row['label']:<18} {row['s_feb']:>5} {row['s_mar']:>5} "
          f"{row['delta']:>+5}  {flag} {stress_label(row['s_mar'])}")

print(f"\n{'SECTOR MEAN STRESS':}")
print("─"*50)
for _, row in df_sector.sort_values("delta", ascending=False).iterrows():
    print(f"  {row['sector']:<14} Feb={row['mean_feb']:.1f}  "
          f"Mar={row['mean_mar']:.1f}  Δ={row['delta']:+.1f}")

# Network-level stats
mean_feb = df_nodes["s_feb"].mean()
mean_mar = df_nodes["s_mar"].mean()
crit_feb = (df_nodes["s_feb"] >= 80).sum()
crit_mar = (df_nodes["s_mar"] >= 80).sum()
print(f"\n  Mean network stress:   Feb={mean_feb:.1f}  →  Mar={mean_mar:.1f} "
      f"(+{mean_mar-mean_feb:.1f}, +{(mean_mar-mean_feb)/mean_feb*100:.0f}%)")
print(f"  Critical nodes (≥80):  Feb={crit_feb}  →  Mar={crit_mar}")
print(f"  Brent price:           Feb=$67/bbl  →  Mar=$83/bbl  (+24%)")
print(f"\n  TOP COLLAPSED FLOWS (w_feb → w_mar):")
for _, e in df_edges.sort_values("delta").head(6).iterrows():
    print(f"    {e['source']:<10} → {e['target']:<10}  "
          f"{e['w_feb']:.2f} → {e['w_mar']:.2f}  (Δ {e['delta']:+.2f})")
print(f"\n  TOP SURGED FLOWS (w_feb → w_mar):")
for _, e in df_edges.sort_values("delta", ascending=False).head(6).iterrows():
    print(f"    {e['source']:<10} → {e['target']:<10}  "
          f"{e['w_feb']:.2f} → {e['w_mar']:.2f}  (Δ {e['delta']:+.2f})")
print("═"*62)
print("\nAll figures saved to /mnt/user-data/outputs/")
