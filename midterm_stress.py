"""
midterm_stress.py — US 2026 midterm stress scenarios (YAML trio → shock table → P&L)

MODEL
-----
For instrument i, outcome k ∈ {DD, DR, RR, RD}, policy factor f ∈ {FISC, REG, GRID, FEDI, WARP}:

    Δ_ik = Σ_f β_if · (x_fk − x̄_f) + c_ik + o_i(k)          x̄_f = Σ_l p_l x_fl

  • β_if   : 1M response to a unit factor surprise (transmission_map.yaml)
  • x_fk   : policy state under outcome k (events.yaml)
  • p_l    : market-implied outcome probabilities (prediction markets)
  • c_ik   : deterministic common term (event-vol crush on VIX)
  • o_i(k) : optional tail overlay (CONTESTED count, TP_TANTRUM)

Property: Σ_k p_k (Δ_ik − c_ik) = 0  → the information part is a martingale under p.
A priced outcome produces a small shock; an unpriced one (RR, p≈8%) a large one.

Severity: SEVERE = 2 × information shock (β uncertainty cv≈50%, z≈1.96) + c_ik.
Adverse residual: most-likely k-σ move against the book, r = −k Σw/√(wᵀΣw).

PSEUDOCODE
----------
    load events, transmission_map, base_prices
    validate(schema, Σp≈1, every instrument has every factor beta)
    p      ← normalise(prob_market)
    x̄_f    ← Σ_k p_k x_fk
    for k in outcomes:
        info_k ← B · (x_k − x̄)                     # B: instruments × factors
        central_k ← info_k + common_k
        severe_k  ← 2·info_k + common_k
    combos ← {RR+TP_TANTRUM, DD+CONTESTED, DR+CONTESTED}
    assert |Σ_k p_k info_k| < tol                     # martingale check
    stressed_level ← apply(shock_type, base_level, Δ)
    if positions: pnl_k ← Σ_i pnl(position_i, Δ_ik); add adverse residual
    if xbbg: sign-check model directions against analog windows (binomial test)
    write shock_table.csv, stressed_levels.csv, pnl.csv
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent
CFG = ROOT / "config"
OUT = ROOT / "output"
ANCHOR = "2026-10-05"
SEVERE_MULT = 2.0
COMBOS = {"RR_TANTRUM": ("RR", "TP_TANTRUM"),
          "DD_CONTESTED": ("DD", "CONTESTED"),
          "DR_CONTESTED": ("DR", "CONTESTED")}


# ── 1. load + validate ────────────────────────────────────────────────────────
def load(anchor: str = ANCHOR):
    ev = yaml.safe_load(open(CFG / f"events_{anchor}.yaml"))
    tm = yaml.safe_load(open(CFG / f"transmission_map_{anchor}.yaml"))["instruments"]
    bp = yaml.safe_load(open(CFG / f"base_prices_{anchor}.yaml"))
    validate(ev, tm, bp)
    return ev, tm, bp


def validate(ev, tm, bp):
    F = list(ev["factors"])
    errs = []
    for k, o in ev["outcomes"].items():
        if set(o["state"]) != set(F):
            errs.append(f"outcome {k}: state keys {set(o['state'])} != factors {set(F)}")
    for i, d in tm.items():
        if set(d["betas"]) != set(F):
            errs.append(f"instrument {i}: missing betas {set(F) - set(d['betas'])}")
        if d["shock_type"] not in {"relative", "yield_bp", "absolute"}:
            errs.append(f"instrument {i}: bad shock_type")
        if i not in bp["instruments"]:
            errs.append(f"instrument {i}: no base price entry")
    for name, ov in ev["overlays"].items():
        extra = set(ov["shocks"]) - set(tm)
        if extra:
            errs.append(f"overlay {name}: unknown instruments {extra}")
    s = sum(o["prob_market"] for o in ev["outcomes"].values())
    if abs(s - 1) > 0.05:
        errs.append(f"outcome probabilities sum to {s:.3f} (tolerance 0.05)")
    if errs:
        raise ValueError("Schema validation failed:\n  " + "\n  ".join(errs))


# ── 2. shock engine ───────────────────────────────────────────────────────────
def shock_table(ev, tm):
    F = list(ev["factors"])
    K = list(ev["outcomes"])
    I = list(tm)
    p = np.array([ev["outcomes"][k]["prob_market"] for k in K], float)
    p /= p.sum()
    X = np.array([[ev["outcomes"][k]["state"][f] for k in K] for f in F])   # F×K
    B = np.array([[tm[i]["betas"][f] for f in F] for i in I])               # I×F
    xbar = X @ p                                                             # F
    info = pd.DataFrame(B @ (X - xbar[:, None]), index=I, columns=K)       # I×K

    common = pd.Series(0.0, index=I)
    for c in ev.get("common", {}).values():
        for i, v in c["shocks"].items():
            common[i] += v

    mart = info @ p
    assert (mart.abs() < 1e-9).all(), f"martingale check failed:\n{mart}"

    cols = {}
    for k in K:
        cols[f"{k}_central"] = info[k] + common
        cols[f"{k}_severe"] = SEVERE_MULT * info[k] + common
    for name, (k, ov) in COMBOS.items():
        cols[name] = info[k] + common + pd.Series(ev["overlays"][ov]["shocks"]).reindex(I).fillna(0)
    tab = pd.DataFrame(cols)
    tab.insert(0, "unit", [tm[i]["unit"] for i in I])
    surprise = pd.DataFrame((X - xbar[:, None]), index=F, columns=K)
    return tab, dict(zip(K, p)), surprise


# ── 3. stressed levels ────────────────────────────────────────────────────────
def stressed_levels(tab, tm, bp):
    rows = {}
    for i in tab.index:
        L = bp["instruments"][i].get("level")
        if L is None:
            continue
        st = tm[i]["shock_type"]
        r = {"base": L}
        for c in tab.columns[1:]:
            d = tab.at[i, c]
            r[c] = L * (1 + d / 100) if st == "relative" else (L + d / 100 if st == "yield_bp" else L + d)
        rows[i] = r
    return pd.DataFrame(rows).T


# ── 4. P&L on a positions file (qty in contracts, + = long) ──────────────────
def one_sigma_1m(tm):
    s = {}
    for i, d in tm.items():
        ann = d.get("vol_ann") or d.get("vol_ann_bp") or d.get("vol_ann_pts")
        s[i] = ann / math.sqrt(12)
    return pd.Series(s)


def stylised_corr(tm, eq_bond=0.3):
    """Fallback correlation in the current regime (replace with history-estimated Σ).
    eq_bond > 0: equity returns vs YIELD changes negatively correlated is the 'old' regime;
    here equities fall when yields rise, i.e. corr(ret, Δy) = −eq_bond."""
    I = list(tm); g = {i: tm[i]["group"] for i in I}
    C = pd.DataFrame(np.eye(len(I)), index=I, columns=I)
    rule = {("EQ_US", "EQ_US"): .85, ("EQ_US", "EQ_EU"): .65, ("EQ_US", "EQ_AS"): .55,
            ("EQ_EU", "EQ_EU"): .9, ("EQ_EU", "EQ_AS"): .5, ("EQ_AS", "EQ_AS"): .6,
            ("RATES", "RATES"): .8, ("RATES", "STIR"): .85, ("EQ_US", "RATES"): -eq_bond,
            ("EQ_US", "VOL"): -.75, ("EQ_EU", "VOL"): -.6, ("EQ_AS", "VOL"): -.5,
            ("EQ_US", "CRYPTO"): .4, ("CMDTY", "CMDTY"): .2, ("FX", "FX"): .5}
    for a in I:
        for b in I:
            if a == b:
                continue
            v = rule.get((g[a], g[b]), rule.get((g[b], g[a]), 0.0))
            if (a, b) in {("CL", "CO"), ("CO", "CL")}: v = .97
            if g[a] == g[b] == "FX" and ("DX" in (a, b)): v = -.8   # DX vs foreign-ccy futures
            C.at[a, b] = v
    # nearest-PSD fix
    w, V = np.linalg.eigh(C.values); w = np.clip(w, 1e-6, None)
    C2 = V @ np.diag(w) @ V.T; d = np.sqrt(np.diag(C2))
    return pd.DataFrame(C2 / np.outer(d, d), index=I, columns=I)


def pnl_per_unit_shock(pos, tm, bp):
    """$ P&L of the position for a +1 (%/bp/pt) shock in each instrument."""
    fx = bp.get("fx_to_usd", {})
    g = {}
    for _, r in pos.iterrows():
        i, q = r["instrument"], r["qty"]
        b = bp["instruments"][i]; st = tm[i]["shock_type"]
        if st == "yield_bp":
            g[i] = -q * b["dv01"]                       # long futures lose when yields rise
        elif st == "absolute":
            g[i] = q * b["mult"]
        else:
            L = b.get("level"); conv = 1.0 if b["ccy"] == "USD" else fx.get(b["ccy"])
            if L is None or conv is None:
                print(f"  ! {i}: missing level/FX — excluded from P&L"); g[i] = 0.0; continue
            g[i] = q * b["mult"] * L * conv / 100
    return pd.Series(g)


def book_pnl(tab, pos, tm, bp, k_sigma=2.0, corr=None):
    grad = pnl_per_unit_shock(pos, tm, bp).reindex(tab.index).fillna(0)
    scen = tab.columns[1:]
    pnl = pd.Series({c: float(grad @ tab[c]) for c in scen})
    # most-likely adverse residual (Studer/Breuer): r = -k Σ g / sqrt(gᵀΣg)
    s = one_sigma_1m(tm).reindex(tab.index)
    C = corr if corr is not None else stylised_corr(tm)
    Sigma = np.outer(s, s) * C.values
    gv = grad.values; sp = math.sqrt(gv @ Sigma @ gv)
    resid = -k_sigma * Sigma @ gv / sp if sp > 0 else np.zeros_like(gv)
    out = pd.DataFrame({"pnl_usd": pnl, "pnl_plus_adverse_resid": pnl + gv @ resid})
    return out, pd.Series(resid, index=tab.index, name=f"adverse_{k_sigma}sigma_residual")


# ── 5. optional: Bloomberg refresh + analog sign check ───────────────────────
def refresh_base_prices(bp, date=None):
    """Fill null levels from Bloomberg (xbbg). Run on a terminal-attached box."""
    from xbbg import blp
    tick = {i: d["bbg"] for i, d in bp["instruments"].items()}
    px = blp.bdp(list(tick.values()), "PX_LAST")
    for i, t in tick.items():
        if t.lower() in px.index:
            bp["instruments"][i]["level"] = float(px.loc[t.lower(), "px_last"])
            bp["instruments"][i]["asof"] = date or pd.Timestamp.today().strftime("%Y-%m-%d")
            bp["instruments"][i].pop("stale", None)
    return bp


def calibrate_from_history(ev, tm, tab, bp, horizon_days=21):
    """Realised 1M moves after each analog t0 vs model sign (binomial sign test per outcome type).
    Midterm windows are heavily confounded (see events.yaml) → treat as a SIGN check only."""
    from xbbg import blp
    from scipy.stats import binomtest
    res = []
    for a in ev["analogs"]:
        typ = a["type"].replace("_elasticity", "")
        if typ not in ev["outcomes"]:
            continue
        t0 = pd.Timestamp(a["t0"])
        for i, d in tm.items():
            tk = bp["instruments"][i]["bbg"]
            h = blp.bdh(tk, "PX_LAST", t0 - pd.Timedelta(days=5), t0 + pd.Timedelta(days=45))
            if h.empty or len(h) < horizon_days + 1:
                continue
            s = h.iloc[:, 0].dropna(); s0 = s[s.index <= t0].iloc[-1]; s1 = s[s.index > t0].iloc[horizon_days - 1]
            real = (s1 - s0) * 100 if d["shock_type"] == "yield_bp" else (
                   s1 - s0 if d["shock_type"] == "absolute" else (s1 / s0 - 1) * 100)
            res.append({"analog": a["name"], "type": typ, "inst": i,
                        "model": tab.at[i, f"{typ}_central"], "realised": real})
    df = pd.DataFrame(res)
    if df.empty:
        return df
    df["sign_ok"] = np.sign(df.model) == np.sign(df.realised)
    n, x = len(df), int(df.sign_ok.sum())
    print(f"sign agreement {x}/{n}; binomial p (H0: 50%) = {binomtest(x, n, 0.5, alternative='greater').pvalue:.3f}")
    return df


# ── 6. main ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", default=ANCHOR)
    ap.add_argument("--positions", default=None, help="CSV with columns instrument,qty")
    ap.add_argument("--bbg", action="store_true", help="refresh levels + analog sign check via xbbg")
    a = ap.parse_args()

    ev, tm, bp = load(a.anchor)
    if a.bbg:
        bp = refresh_base_prices(bp)
    tab, p, surprise = shock_table(ev, tm)
    OUT.mkdir(exist_ok=True)
    tab.round(2).to_csv(OUT / f"shock_table_{a.anchor}.csv")
    lv = stressed_levels(tab, tm, bp)
    lv.round(4).to_csv(OUT / f"stressed_levels_{a.anchor}.csv")

    pd.set_option("display.width", 200)
    print("probabilities:", {k: round(v, 3) for k, v in p.items()})
    print("\nfactor surprises (x_k − x̄):\n", surprise.round(3))
    print("\nshock table:\n", tab.round(2))

    if a.positions:
        pos = pd.read_csv(a.positions)
        pnl, resid = book_pnl(tab, pos, tm, bp)
        pnl.round(0).to_csv(OUT / f"pnl_{a.anchor}.csv")
        print("\nbook P&L (USD):\n", pnl.round(0))
        print("\nadverse residual vector:\n", resid.round(2))
    if a.bbg:
        calibrate_from_history(ev, tm, tab, bp).to_csv(OUT / f"analog_signcheck_{a.anchor}.csv")


if __name__ == "__main__":
    main()
