"""
Master-fund daily risk snapshot: equity stat-arb + directional futures.

Produces the JSON datasets behind the "Master Fund Daily Risk" dashboard.
Positions, prices and factor returns here are SIMULATED. To run on real data,
replace section A (simulation) with loaders for: factor return history,
stat-arb positions + loadings (beta, sector, style z-scores, idio vol, ADV),
and futures positions in risk units. Sections B-E are the risk engine and
stay as they are.

Usage:  python risk_dashboard.py [output_dir]     (default: dashboard_data/)

Pseudocode
----------
A. Inputs
   R            <- factor return history (T x K); rates in bp, others in returns
   books(t-1,t) <- stat-arb weights, futures positions ($ delta or DV01)
B. Exposure map (common factor space)
   X[book]      <- $ P&L per unit factor move, per position
                   equities: w*beta (region), w (sector), w*z (styles)
                   futures : $ delta * loading;  bonds: -DV01 on the yield factor
   idio         <- w^2 * d   (d = idiosyncratic variance)
C. Risk
   F_t          <- EWMA(R, half-life 60d)
   e            =  sum_positions X;   sigma^2 = e'F e + sum w^2 d
   RC_k         =  e_k (F e)_k / sigma         (Euler; sums to sigma)
   RC_book      =  (e_b' F e + idio_b) / sigma
   VaR, ES      <- parametric (Gaussian) and FHS (vol-rescaled factor history)
   d_sigma      =  position effect + market effect   (symmetric/Shapley split)
D. Stress       P&L_s = shock_s . e  (+ residual add-on for crowding scenarios)
E. Backtest     exceptions vs VaR99, Kupiec POF test, bias = std(P&L / sigma_hat)
F. Export       one JSON file per dashboard dataset
"""
import os, sys
import json, numpy as np, pandas as pd
from scipy.stats import norm, chi2
from scipy.special import xlogy

rng = np.random.default_rng(7)
NAV = 2.0e9
Z99 = norm.ppf(0.99)
ES_MULT = norm.pdf(Z99) / 0.01

# ================================================= A. simulated inputs
# ---------------------------------------------------------------- factors
FACTORS = {
    # name: (group, daily vol in natural units)   rates in bp, others in return
    "EQ_US": ("Equity market", 0.010), "EQ_EU": ("Equity market", 0.011),
    "EQ_JP": ("Equity market", 0.012), "EQ_EM": ("Equity market", 0.011),
    "UST_2Y": ("Rates", 6.0), "UST_10Y": ("Rates", 7.0),
    "BUND_10Y": ("Rates", 6.0), "GILT_10Y": ("Rates", 7.0),
    "CRUDE": ("Commodities", 0.022), "GOLD": ("Commodities", 0.010),
    "COPPER": ("Commodities", 0.015), "GRAINS": ("Commodities", 0.013),
    "EUR": ("FX", 0.005), "JPY": ("FX", 0.006), "GBP": ("FX", 0.0055), "AUD": ("FX", 0.007),
    "MOMENTUM": ("Equity styles", 0.005), "VALUE": ("Equity styles", 0.004),
    "SIZE": ("Equity styles", 0.003), "QUALITY": ("Equity styles", 0.0025),
    "LOW_VOL": ("Equity styles", 0.0035), "CROWDING": ("Equity styles", 0.004),
    "TECH": ("Equity sectors", 0.006), "FINANCIALS": ("Equity sectors", 0.005),
    "ENERGY": ("Equity sectors", 0.008), "HEALTH": ("Equity sectors", 0.005),
    "INDUSTRIALS": ("Equity sectors", 0.004), "CONSUMER": ("Equity sectors", 0.004),
}
FN = list(FACTORS); K = len(FN)
GROUP = {f: g for f, (g, _) in FACTORS.items()}
VOL = np.array([v for _, v in FACTORS.values()])

# latent drivers: risk-on, rates level, dollar, commodity, quant crowding
LAT = ["riskon", "rates", "usd", "commod", "quant"]
Lw = pd.DataFrame(0.0, index=FN, columns=LAT)       # correlation loadings
Lw.loc[["EQ_US", "EQ_EU", "EQ_JP", "EQ_EM"], "riskon"] = [0.85, 0.85, 0.75, 0.80]
Lw.loc[["UST_2Y", "UST_10Y", "BUND_10Y", "GILT_10Y"], "rates"] = [0.80, 0.90, 0.80, 0.80]
Lw.loc[["UST_2Y", "UST_10Y", "BUND_10Y", "GILT_10Y"], "riskon"] = [0.20, 0.25, 0.20, 0.20]
Lw.loc[["CRUDE", "COPPER", "GRAINS", "GOLD"], "commod"] = [0.65, 0.55, 0.40, 0.35]
Lw.loc[["CRUDE", "COPPER"], "riskon"] = [0.30, 0.40]
Lw.loc[["EUR", "JPY", "GBP", "AUD"], "usd"] = [-0.75, -0.50, -0.65, -0.60]
Lw.loc[["JPY", "AUD", "GOLD"], "riskon"] = [-0.40, 0.45, -0.05]
Lw.loc[["JPY", "GOLD"], "rates"] = [-0.30, -0.25]
Lw.loc[["MOMENTUM", "CROWDING", "VALUE", "LOW_VOL"], "quant"] = [0.60, 0.65, -0.45, 0.20]
Lw.loc[["LOW_VOL", "MOMENTUM", "SIZE"], "riskon"] = [-0.45, -0.10, 0.15]
Lw.loc[["TECH", "FINANCIALS", "ENERGY"], "riskon"] = [0.20, 0.15, 0.10]
Lw.loc["ENERGY", "commod"] = 0.50
Lw.loc["FINANCIALS", "rates"] = 0.30
resid = np.sqrt(np.clip(1 - (Lw**2).sum(axis=1), 0.05, None))

T = 1000
logv = np.zeros(T)
for t in range(1, T):
    logv[t] = 0.97 * logv[t-1] + 0.06 * rng.standard_normal()
vt = np.exp(logv); vt /= vt[-500:].mean()
vt[T-160:T-150] *= 1.8
vt[T-15:] *= 1.35

df = 4
def tdraw(shape):
    return rng.standard_t(df, shape) / np.sqrt(df / (df - 2))

G = tdraw((T, len(LAT)))
G[T-160:T-152, LAT.index("quant")] -= 1.6                # quant unwind episode
E = tdraw((T, K))
Zs = G @ Lw.values.T + E * resid.values
R = Zs * VOL * vt[:, None]
# day t (last row): risk-off, oil spike, yields down
shock_t = {"EQ_US": -1.4, "EQ_EU": -1.2, "EQ_JP": -1.0, "EQ_EM": -1.1, "CRUDE": 2.3,
           "UST_10Y": -1.1, "UST_2Y": -0.8, "BUND_10Y": -0.9, "GILT_10Y": -0.9,
           "JPY": 1.0, "GOLD": 1.2, "MOMENTUM": -0.8, "CROWDING": -0.6, "ENERGY": 1.5}
for f, s in shock_t.items():
    R[-1, FN.index(f)] = 1.5 * s * VOL[FN.index(f)] * vt[-1]
dates = pd.bdate_range(end="2026-10-28", periods=T)
Rf = pd.DataFrame(R, index=dates, columns=FN)

def ewma_cov(Rdf, hl=60):
    lam = 0.5 ** (1 / hl)
    w = lam ** np.arange(len(Rdf))[::-1]; w /= w.sum()
    X = Rdf.values
    return pd.DataFrame((X * w[:, None]).T @ X, Rdf.columns, Rdf.columns)

F_t = ewma_cov(Rf.iloc[-500:])
F_tm1 = ewma_cov(Rf.iloc[-501:-1])

# ---------------------------------------------------------------- stat-arb book
N = 1500
region = rng.choice(["US", "EU", "JP"], N, p=[0.5, 0.3, 0.2])
sectors = ["TECH", "FINANCIALS", "ENERGY", "HEALTH", "INDUSTRIALS", "CONSUMER"]
sector = rng.choice(sectors, N)
beta = np.clip(rng.normal(1.0, 0.25, N), 0.3, 1.8)
styles = ["MOMENTUM", "VALUE", "SIZE", "QUALITY", "LOW_VOL", "CROWDING"]
Zst = rng.standard_normal((N, len(styles)))
Zst[:, 5] = np.clip(rng.gamma(2.0, 0.5, N) - 1.0, -1, 5)          # crowding: skewed
idio_vol = np.exp(rng.normal(np.log(0.017), 0.3, N))
adv = np.exp(rng.normal(np.log(45e6), 0.9, N)) * np.where(region == "US", 1.6, 1.0)
earn_5d = rng.random(N) < 0.06
tick = np.array([f"{r}{i:04d}" for i, r in enumerate(region)])

def statarb_weights(mom_tilt, seed):
    r = np.random.default_rng(seed)
    alpha = r.standard_normal(N)
    # neutralise region-beta, sector and style exposures
    A = np.column_stack([np.where(region == g, beta, 0) for g in ["US", "EU", "JP"]] +
                        [(sector == s).astype(float) for s in sectors] + [Zst])
    w = alpha - A @ np.linalg.lstsq(A, alpha, rcond=None)[0]
    w = w / np.abs(w).sum() * 4.0e9
    w = np.clip(w, -11e6, 11e6)
    w = w / np.abs(w).sum() * 4.0e9
    w = w - A @ np.linalg.lstsq(A, w, rcond=None)[0]
    # deliberate residual style tilts ($ per unit z)
    for k, amt in [(0, mom_tilt), (1, -70e6), (5, -90e6), (4, 40e6)]:
        z = Zst[:, k] - Zst[:, k].mean()
        w += amt * z / (z @ Zst[:, k])
    # small deliberate residual: net long US beta, long JP beta
    w += np.where(region == "US", 55e6 / (beta * (region == "US")).sum(), 0)
    w += np.where(region == "JP", 30e6 / (beta * (region == "JP")).sum(), 0)
    w += np.where(region == "EU", -15e6 / (beta * (region == "EU")).sum(), 0)
    return w

w_sa_t = statarb_weights(220e6, 11)
w_sa_tm1 = 0.92 * statarb_weights(150e6, 11) + 0.08 * statarb_weights(150e6, 12)

def statarb_X(w):
    X = pd.DataFrame(0.0, index=tick, columns=FN)
    for g, f in [("US", "EQ_US"), ("EU", "EQ_EU"), ("JP", "EQ_JP")]:
        m = region == g
        X.loc[m, f] = w[m] * beta[m]
    for s in sectors:
        m = sector == s
        X.loc[m, s] = w[m]
    for k, s in enumerate(styles):
        X[s] = w * Zst[:, k]
    return X

# ---------------------------------------------------------------- futures book
# (name, asset class, {factor: loading per $ delta}, kind)   rates: $ delta == DV01 ($/bp)
FUT = [
    ("ES  (S&P 500)", "Equity", {"EQ_US": 1.0}, "eq"),
    ("NQ  (Nasdaq-100)", "Equity", {"EQ_US": 1.15, "TECH": 0.6}, "eq"),
    ("SX5E (Euro Stoxx 50)", "Equity", {"EQ_EU": 1.0}, "eq"),
    ("DAX", "Equity", {"EQ_EU": 1.05}, "eq"),
    ("NKY (Nikkei 225)", "Equity", {"EQ_JP": 1.1}, "eq"),
    ("TOPIX", "Equity", {"EQ_JP": 1.0}, "eq"),
    ("MSCI EM", "Equity", {"EQ_EM": 1.0}, "eq"),
    ("TU  (UST 2y)", "Rates", {"UST_2Y": -1.0}, "rt"),
    ("TY  (UST 10y)", "Rates", {"UST_10Y": -1.0}, "rt"),
    ("US  (UST bond)", "Rates", {"UST_10Y": -1.25}, "rt"),
    ("RX  (Bund)", "Rates", {"BUND_10Y": -1.0}, "rt"),
    ("G   (Gilt)", "Rates", {"GILT_10Y": -1.0}, "rt"),
    ("CL  (WTI crude)", "Commodities", {"CRUDE": 1.0}, "cm"),
    ("CO  (Brent crude)", "Commodities", {"CRUDE": 0.97}, "cm"),
    ("GC  (Gold)", "Commodities", {"GOLD": 1.0}, "cm"),
    ("HG  (Copper)", "Commodities", {"COPPER": 1.0}, "cm"),
    ("C   (Corn)", "Commodities", {"GRAINS": 1.0}, "cm"),
    ("S   (Soybeans)", "Commodities", {"GRAINS": 0.9}, "cm"),
    ("EC  (EUR/USD)", "FX", {"EUR": 1.0}, "fx"),
    ("JY  (JPY/USD)", "FX", {"JPY": 1.0}, "fx"),
    ("BP  (GBP/USD)", "FX", {"GBP": 1.0}, "fx"),
    ("AD  (AUD/USD)", "FX", {"AUD": 1.0}, "fx"),
]
# $ delta (DV01 in $/bp for rates).  t-1 and t
POS_T = np.array([165e6, 85e6, 60e6, 40e6, 120e6, 50e6, 40e6,
                  110e3, 140e3, 40e3, -90e3, 50e3,
                  85e6, 60e6, 80e6, -30e6, -25e6, -20e6,
                  100e6, -150e6, 40e6, -60e6])
POS_T = POS_T * 0.6
POS_TM1 = POS_T.copy()
POS_TM1[[0, 12, 13, 8]] = [110e6, 27e6, 18e6, 120e3]          # added crude, cut TY, trimmed ES
IM_RATE = {"eq": 0.06, "rt": 0.0, "cm": 0.08, "fx": 0.03}
DV01_TO_NOTIONAL = {"TU  (UST 2y)": 1/0.0002, "TY  (UST 10y)": 1/0.00075, "US  (UST bond)": 1/0.0015,
                    "RX  (Bund)": 1/0.0008, "G   (Gilt)": 1/0.0008}
fut_names = [f[0] for f in FUT]

def fut_X(pos):
    X = pd.DataFrame(0.0, index=fut_names, columns=FN)
    for (n, _, load, _), p in zip(FUT, pos):
        for f, l in load.items():
            X.loc[n, f] = p * l
    return X

def fut_w(pos):   # $ exposure for basis/idio risk (none on rates)
    return np.array([0.0 if k == "rt" else p for (_, _, _, k), p in zip(FUT, pos)])
FUT_IDIO = 0.002 ** 2

# ================================================= B-C. exposures and risk
# ---------------------------------------------------------------- assemble
def book_state(w_sa, pos):
    Xsa, Xfu = statarb_X(w_sa), fut_X(pos)
    return {
        "X": {"Stat-arb": Xsa, "Futures": Xfu},
        "w": {"Stat-arb": w_sa, "Futures": fut_w(pos)},
        "d": {"Stat-arb": idio_vol ** 2, "Futures": np.full(len(FUT), FUT_IDIO)},
    }

S_t, S_tm1 = book_state(w_sa_t, POS_T), book_state(w_sa_tm1, POS_TM1)

def sigma_of(S, F, books=("Stat-arb", "Futures")):
    e = sum(S["X"][b].sum() for b in books)
    vi = sum((S["w"][b] ** 2 * S["d"][b]).sum() for b in books)   # no asset overlap across books
    return float(np.sqrt(e @ F @ e + vi))

def decompose(S, F):
    e = S["X"]["Stat-arb"].sum() + S["X"]["Futures"].sum()
    Fe = F @ e
    vi = {b: float((S["w"][b] ** 2 * S["d"][b]).sum()) for b in S["w"]}
    var = float(e @ Fe) + sum(vi.values())
    sig = np.sqrt(var)
    by_factor = e * Fe / sig
    by_book = {b: (float(S["X"][b].sum() @ Fe) + vi[b]) / sig for b in S["X"]}
    by_group = by_factor.groupby(GROUP).sum()
    by_group["Idiosyncratic / basis"] = sum(vi.values()) / sig
    return sig, e, by_factor, by_group, by_book, vi

sig_t, e_t, bf_t, bg_t, bb_t, vi_t = decompose(S_t, F_t)
sig_tm1, e_tm1, bf_tm1, bg_tm1, bb_tm1, _ = decompose(S_tm1, F_tm1)
assert abs(bg_t.sum() - sig_t) < 1e-6 * sig_t and abs(sum(bb_t.values()) - sig_t) < 1e-6 * sig_t

sa_sig = {k: sigma_of(S, F, ("Stat-arb",)) for k, (S, F) in {"t": (S_t, F_t), "tm1": (S_tm1, F_tm1)}.items()}
fu_sig = {k: sigma_of(S, F, ("Futures",)) for k, (S, F) in {"t": (S_t, F_t), "tm1": (S_tm1, F_tm1)}.items()}

eA, eB = S_t["X"]["Stat-arb"].sum(), S_t["X"]["Futures"].sum()
rho_x = float(eA @ F_t @ eB) / (sa_sig["t"] * fu_sig["t"])

# Delta attribution (symmetric split)
def shapley(books=("Stat-arb", "Futures")):
    s = lambda S, F: sigma_of(S, F, books)
    pos = 0.5 * ((s(S_t, F_tm1) - s(S_tm1, F_tm1)) + (s(S_t, F_t) - s(S_tm1, F_t)))
    mkt = 0.5 * ((s(S_tm1, F_t) - s(S_tm1, F_tm1)) + (s(S_t, F_t) - s(S_t, F_tm1)))
    return pos, mkt, s(S_t, F_t) - s(S_tm1, F_tm1)
delta = {name: shapley(b) for name, b in
         [("Fund", ("Stat-arb", "Futures")), ("Stat-arb", ("Stat-arb",)), ("Futures", ("Futures",))]}
for p, m, tot in delta.values():
    assert abs(p + m - tot) < 1e-6

# FHS VaR / ES  (factor scenarios rescaled to today's vol + Gaussian idio)
def fhs(e, vi, Rhist, hl=60, alpha=0.99, nrep=20):
    v = np.sqrt((Rhist ** 2).ewm(halflife=hl).mean())
    Rs = (Rhist / v.shift(1) * v.iloc[-1]).dropna().iloc[-500:]
    pnl_f = Rs.values @ e.values
    pnl = (pnl_f[:, None] + np.sqrt(vi) * rng.standard_normal((len(pnl_f), nrep))).ravel()
    q = np.quantile(pnl, 1 - alpha)
    return -q, -pnl[pnl <= q].mean()

var_fhs = {
    "Fund": fhs(e_t, sum(vi_t.values()), Rf),
    "Stat-arb": fhs(eA, vi_t["Stat-arb"], Rf),
    "Futures": fhs(eB, vi_t["Futures"], Rf),
}
sig_map = {"Fund": sig_t, "Stat-arb": sa_sig["t"], "Futures": fu_sig["t"]}

# ================================================= D. stress
# ---------------------------------------------------------------- stress
def shockvec(d):
    v = pd.Series(0.0, index=FN)
    for k, x in d.items(): v[k] = x
    return v
SCEN = [
    ("Oct 1987 crash (1d)", "Historical", {"EQ_US": -.20, "EQ_EU": -.12, "EQ_JP": -.15, "EQ_EM": -.12,
        "UST_10Y": -30, "UST_2Y": -45, "BUND_10Y": -20, "GILT_10Y": -25, "GOLD": .03, "CRUDE": -.05,
        "JPY": .02, "AUD": -.04, "LOW_VOL": .03, "MOMENTUM": -.02}, 0.0),
    ("Aug 2007 quant quake (5d)", "Historical", {"EQ_US": -.03, "EQ_EU": -.03, "EQ_JP": -.04,
        "MOMENTUM": -.07, "VALUE": .04, "CROWDING": -.08, "QUALITY": -.02, "UST_10Y": -15, "JPY": .02}, 0.010),
    ("Lehman week, Sep 2008 (5d)", "Historical", {"EQ_US": -.10, "EQ_EU": -.09, "EQ_JP": -.08, "EQ_EM": -.12,
        "UST_2Y": -50, "UST_10Y": -35, "BUND_10Y": -25, "GILT_10Y": -30, "CRUDE": -.15, "COPPER": -.12,
        "GOLD": .05, "JPY": .06, "AUD": -.10, "EUR": -.04, "FINANCIALS": -.08, "MOMENTUM": .03}, 0.003),
    ("Covid crash, Mar 2020 (5d)", "Historical", {"EQ_US": -.15, "EQ_EU": -.14, "EQ_JP": -.10, "EQ_EM": -.12,
        "UST_10Y": -30, "UST_2Y": -40, "BUND_10Y": -10, "GILT_10Y": -15, "CRUDE": -.30, "COPPER": -.08,
        "GOLD": -.05, "AUD": -.08, "JPY": .02, "GBP": -.06, "ENERGY": -.10, "LOW_VOL": .04}, 0.002),
    ("Yen-carry unwind, Aug 2024 (3d)", "Historical", {"EQ_JP": -.18, "EQ_US": -.06, "EQ_EU": -.05, "EQ_EM": -.06,
        "JPY": .07, "UST_10Y": -25, "UST_2Y": -30, "MOMENTUM": -.06, "CROWDING": -.05, "TECH": -.03,
        "AUD": -.03, "COPPER": -.04}, 0.004),
    ("Tariff shock, Apr 2025 (3d)", "Historical", {"EQ_US": -.11, "EQ_EU": -.09, "EQ_JP": -.10, "EQ_EM": -.09,
        "UST_10Y": 20, "UST_2Y": -10, "CRUDE": -.15, "COPPER": -.10, "GOLD": .02, "EUR": .03, "JPY": .04,
        "AUD": -.04, "TECH": -.03, "MOMENTUM": -.03}, 0.002),
    ("Global equities −10%", "Hypothetical", {"EQ_US": -.10, "EQ_EU": -.10, "EQ_JP": -.10, "EQ_EM": -.10}, 0.0),
    ("Rates +100bp parallel", "Hypothetical", {"UST_2Y": 100, "UST_10Y": 100, "BUND_10Y": 100, "GILT_10Y": 100}, 0.0),
    ("Oil +30% supply shock", "Hypothetical", {"CRUDE": .30, "EQ_US": -.04, "EQ_EU": -.05,
        "EQ_JP": -.05, "EQ_EM": -.05, "UST_10Y": 15, "GOLD": .04, "JPY": .02, "ENERGY": .08}, 0.0),
    ("Crowding / momentum unwind", "Hypothetical", {"MOMENTUM": -.08, "CROWDING": -.10, "VALUE": .05}, 0.012),
]
stress_rows = []
gross_sa = float(np.abs(w_sa_t).sum())
for name, kind, d, resid_frac in SCEN:
    v = shockvec(d)
    pa = float(eA @ v) - resid_frac * gross_sa
    pb = float(eB @ v)
    stress_rows.append({"scenario": name, "type": kind, "statarb": pa, "futures": pb, "fund": pa + pb,
                        "statarb_residual_addon": -resid_frac * gross_sa})
# CTA trend reversal: every futures exposure moves 2σ (5d) against current sign
fvol = np.sqrt(np.diag(F_t.values))
rev = pd.Series(-np.sign(eB.values) * 2 * fvol * np.sqrt(5), index=FN)
rev[[f for f in FN if GROUP[f] in ("Equity styles", "Equity sectors")]] = 0
pa, pb = float(eA @ rev), float(eB @ rev)
stress_rows.append({"scenario": "Trend reversal: all futures legs −2σ (5d)", "type": "Hypothetical",
                    "statarb": pa, "futures": pb, "fund": pa + pb, "statarb_residual_addon": 0.0})

# ---------------------------------------------------------------- stat-arb panel
w = w_sa_t
longs, shorts = w[w > 0].sum(), -w[w < 0].sum()
beta_net = {g: float((w * beta)[region == g].sum()) for g in ["US", "EU", "JP"]}
style_exp = {s: float((w * Zst[:, k]).sum()) for k, s in enumerate(styles)}
style_exp_tm1 = {s: float((w_sa_tm1 * Zst[:, k]).sum()) for k, s in enumerate(styles)}
dtl = np.abs(w) / (0.15 * adv)
liq = {f"{d}d": float(np.abs(w)[dtl <= d].sum() / np.abs(w).sum()) for d in [1, 3, 5]}
liq["max_days"] = float(dtl.max())
crowd_short = float(-w[(w < 0) & (Zst[:, 5] > 1.5)].sum() / shorts)
fac_var_sa = float(eA @ F_t @ eA)
idio_share = vi_t["Stat-arb"] / (fac_var_sa + vi_t["Stat-arb"])
order = np.argsort(-np.abs(w))
top10 = float(np.abs(w)[order[:10]].sum() / np.abs(w).sum())
earn_gross = float(np.abs(w)[earn_5d].sum())
earn_idio_var = float((w[earn_5d] ** 2 * idio_vol[earn_5d] ** 2 * 9).sum())  # ~3x vol on earnings day

# ---------------------------------------------------------------- futures panel
def contrib_rows(S, F, sig):
    e = S["X"]["Stat-arb"].sum() + S["X"]["Futures"].sum()
    Fe = F @ e
    c = S["X"]["Futures"] @ Fe / sig + S["w"]["Futures"] ** 2 * FUT_IDIO / sig
    return c
c_t = contrib_rows(S_t, F_t, sig_t)
c_tm1 = contrib_rows(S_tm1, F_tm1, sig_tm1)
fut_rows = []
for i, (n, ac, load, k) in enumerate(FUT):
    notional = POS_T[i] * DV01_TO_NOTIONAL[n] if k == "rt" else POS_T[i]
    standalone = float(np.sqrt(S_t["X"]["Futures"].iloc[i] @ F_t @ S_t["X"]["Futures"].iloc[i]))
    fut_rows.append({"contract": n, "asset_class": ac, "exposure": float(POS_T[i]),
                     "exposure_unit": "DV01 $/bp" if k == "rt" else "$ delta",
                     "exposure_tm1": float(POS_TM1[i]),
                     "notional": float(notional), "standalone_sigma": standalone,
                     "contrib": float(c_t.iloc[i]), "contrib_tm1": float(c_tm1.iloc[i]),
                     "margin": float(abs(notional) * (0.02 if k == "rt" else IM_RATE[k]))})
fut_df = pd.DataFrame(fut_rows)
ac_sig = {}
for ac in ["Equity", "Rates", "Commodities", "FX"]:
    Xi = S_t["X"]["Futures"][fut_df["asset_class"].values == ac].sum()
    ac_sig[ac] = float(np.sqrt(Xi @ F_t @ Xi))
ac_contrib = fut_df.groupby("asset_class")["contrib"].sum().to_dict()
dv01 = fut_df[fut_df.asset_class == "Rates"].set_index("contract")["exposure"].to_dict()
eq_net_fut = float(fut_df[fut_df.asset_class == "Equity"]["exposure"].sum())
margin = float(fut_df["margin"].sum())

# ================================================= E. backtest
# ---------------------------------------------------------------- backtest (250d)
nb = 250
eA_bt = np.array([eA.values * (1 + 0.15 * np.sin(i / 37)) for i in range(nb)])
eB_bt = np.array([eB.values * (1 + 0.25 * np.sin(i / 23 + 1)) for i in range(nb)])
lam = 0.5 ** (1 / 60)
Fr = ewma_cov(Rf.iloc[-(nb + 500):-nb]).values
rows = []
for i in range(nb):
    idx = T - nb + i          # forecast made with info up to idx-1, realised on idx
    eAi, eBi = eA_bt[i], eB_bt[i]
    ef = eAi + eBi
    viA, viB = vi_t["Stat-arb"], vi_t["Futures"]
    sA = np.sqrt(eAi @ Fr @ eAi + viA); sB = np.sqrt(eBi @ Fr @ eBi + viB)
    sF = np.sqrt(ef @ Fr @ ef + viA + viB)
    r = R[idx]
    pA = eAi @ r + np.sqrt(viA) * rng.standard_normal()
    pB = eBi @ r + np.sqrt(viB) * rng.standard_normal()
    rows.append({"date": dates[idx].strftime("%Y-%m-%d"), "sigma_fund": sF, "sigma_sa": sA, "sigma_fut": sB,
                 "var_fund": Z99 * sF, "pnl_fund": pA + pB, "pnl_sa": pA, "pnl_fut": pB})
    Fr = lam * Fr + (1 - lam) * np.outer(r, r)
bt = pd.DataFrame(rows)
# make today's realised P&L consistent with today's book
bt.loc[bt.index[-1], ["pnl_sa", "pnl_fut"]] = [float(S_tm1["X"]["Stat-arb"].sum() @ Rf.iloc[-1]) + 1.1e6,
                                               float(S_tm1["X"]["Futures"].sum() @ Rf.iloc[-1])]
bt.loc[bt.index[-1], "pnl_fund"] = bt.iloc[-1]["pnl_sa"] + bt.iloc[-1]["pnl_fut"]

def kupiec(hits, p=0.01):
    n, x = len(hits), int(hits.sum()); pi = x / n
    lr = -2 * (xlogy(n - x, 1 - p) + xlogy(x, p) - xlogy(n - x, 1 - pi) - xlogy(x, pi))
    return x, n * p, float(1 - chi2.cdf(lr, 1))
hits = bt.pnl_fund < -bt.var_fund
x, ex, pval = kupiec(hits.values)
bias = {"Fund": float((bt.pnl_fund / bt.sigma_fund).std()),
        "Stat-arb": float((bt.pnl_sa / bt.sigma_sa).std()),
        "Futures": float((bt.pnl_fut / bt.sigma_fut).std())}

# ---------------------------------------------------------------- limits
worst = min(stress_rows, key=lambda r: r["fund"])
sa_style_max = max(abs(v) for v in style_exp.values()) / gross_sa
limits = [
    ("Fund 1d VaR99 (parametric)", Z99 * sig_t, 25e6, "$"),
    ("Fund 1d ES99 (FHS)", var_fhs["Fund"][1], 32e6, "$"),
    ("Worst stress loss", -worst["fund"], 0.06 * NAV, "$"),
    ("Stat-arb gross", gross_sa, 4.5e9, "$"),
    ("Stat-arb |beta-adj net|", abs(sum(beta_net.values())), 100e6, "$"),
    ("Stat-arb max |style| / gross", sa_style_max, 0.10, "%"),
    ("Stat-arb max single name / NAV", float(np.abs(w).max()) / NAV, 0.0075, "%"),
    ("Futures ex-ante vol (ann., on $1bn)", fu_sig["t"] * np.sqrt(252) / 1e9, 0.12, "%"),
    ("Futures total DV01", float(sum(abs(v) for v in dv01.values())), 500e3, "$/bp"),
    ("Futures margin / allocation", margin / 1e9, 0.25, "%"),
]
lim_rows = [{"limit": n, "value": float(v), "cap": float(c), "unit": u, "util": float(v / c)} for n, v, c, u in limits]

# ---------------------------------------------------------------- what changed: movers
movers = []
for r in fut_rows:
    dc = r["contrib"] - r["contrib_tm1"]
    movers.append({"item": r["contract"], "book": "Futures", "d_contrib": dc,
                   "why": "position" if r["exposure"] != r["exposure_tm1"] else "market"})
for s in styles + ["EQ_US", "EQ_EU", "EQ_JP"] + sectors:
    ea, eb_ = S_t["X"]["Stat-arb"][s].sum(), S_tm1["X"]["Stat-arb"][s].sum()
    Fe_t = (F_t @ e_t)[s]; Fe_tm1 = (F_tm1 @ e_tm1)[s]
    dc = ea * Fe_t / sig_t - eb_ * Fe_tm1 / sig_tm1
    movers.append({"item": f"{s.title().replace('_', ' ')} exposure", "book": "Stat-arb", "d_contrib": float(dc),
                   "why": "position" if abs(ea - eb_) > 0.05 * abs(eb_) + 1e5 else "market"})
movers = sorted(movers, key=lambda m: -abs(m["d_contrib"]))[:7]


# ---------------------------------------------------------------- collect results
out = {
    "asof": {"positions": "2026-10-28 close", "report": "2026-10-29 07:00 London", "nav": NAV},
    "headline": {
        "pnl": {"Fund": float(bt.iloc[-1].pnl_fund), "Stat-arb": float(bt.iloc[-1].pnl_sa), "Futures": float(bt.iloc[-1].pnl_fut)},
        "sigma": {"Fund": sig_t, "Stat-arb": sa_sig["t"], "Futures": fu_sig["t"]},
        "sigma_tm1": {"Fund": sig_tm1, "Stat-arb": sa_sig["tm1"], "Futures": fu_sig["tm1"]},
        "var_param": {k: Z99 * v for k, v in sig_map.items()},
        "es_param": {k: ES_MULT * v for k, v in sig_map.items()},
        "var_fhs": {k: v[0] for k, v in var_fhs.items()},
        "es_fhs": {k: v[1] for k, v in var_fhs.items()},
        "diversification": sa_sig["t"] + fu_sig["t"] - sig_t,
        "rho_cross": rho_x,
    },
    "delta": {k: {"position": v[0], "market": v[1], "total": v[2]} for k, v in delta.items()},
    "by_book": bb_t, "by_book_tm1": bb_tm1,
    "by_group": bg_t.to_dict(), "by_group_tm1": bg_tm1.to_dict(),
    "by_factor": bf_t.to_dict(), "exposure": e_t.to_dict(), "factor_group": GROUP,
    "movers": movers,
    "statarb": {"gross": gross_sa, "long": float(longs), "short": float(shorts), "net": float(w.sum()),
                "beta_net": beta_net, "style": style_exp, "style_tm1": style_exp_tm1,
                "idio_share": idio_share, "top10_share": top10, "max_name_nav": float(np.abs(w).max() / NAV),
                "names": int(N), "liquidity": liq, "crowded_short_share": crowd_short,
                "earnings_names": int(earn_5d.sum()), "earnings_gross": earn_gross,
                "earnings_sigma": float(np.sqrt(earn_idio_var))},
    "futures": {"rows": fut_rows, "ac_sigma": ac_sig, "ac_contrib": ac_contrib, "dv01": dv01,
                "eq_net": eq_net_fut, "margin": margin},
    "stress": stress_rows,
    "backtest": {"series": bt.round(0).to_dict(orient="records"), "exceptions": x, "expected": ex,
                 "kupiec_p": pval, "bias": bias},
    "limits": lim_rows,
}

# ================================================= F. export for the dashboard
D = sys.argv[1] if len(sys.argv) > 1 else "dashboard_data"
os.makedirs(D, exist_ok=True)
M = 1e6
def dump(name, rows): json.dump(rows, open(f"{D}/{name}.json", "w"), indent=1, default=float)
r2 = lambda x, n=2: float(round(float(x), n))
h = out["headline"]
alloc = {"Fund": NAV, "Stat-arb": 1e9, "Futures": 1e9}
books = []
for b in ["Fund", "Stat-arb", "Futures"]:
    d = out["delta"][b]
    contrib = sig_t if b == "Fund" else bb_t[b]
    contrib_tm1 = sig_tm1 if b == "Fund" else bb_tm1[b]
    books.append({"book": b, "pnl_m": r2(h["pnl"][b] / M), "pnl_bp_nav": r2(h["pnl"][b] / NAV * 1e4, 1),
        "sigma_m": r2(h["sigma"][b] / M), "sigma_tm1_m": r2(h["sigma_tm1"][b] / M),
        "d_sigma_m": r2(d["total"] / M), "d_sigma_pct": r2(d["total"] / h["sigma_tm1"][b] * 100, 1),
        "d_pos_m": r2(d["position"] / M), "d_mkt_m": r2(d["market"] / M),
        "vol_ann_pct": r2(h["sigma"][b] * np.sqrt(252) / alloc[b] * 100, 1),
        "var_param_m": r2(h["var_param"][b] / M), "es_param_m": r2(h["es_param"][b] / M),
        "var_fhs_m": r2(h["var_fhs"][b] / M), "es_fhs_m": r2(h["es_fhs"][b] / M),
        "fhs_ratio": r2(h["var_fhs"][b] / h["var_param"][b]),
        "contrib_m": r2(contrib / M), "contrib_tm1_m": r2(contrib_tm1 / M),
        "contrib_pct": r2(contrib / sig_t * 100, 1)})
dump("books", books)

worst = min(stress_rows, key=lambda r: r["fund"])
lim_status = lambda u: "breach" if u >= 1 else ("amber" if u >= 0.75 else "ok")
fund = [{"nav_bn": NAV / 1e9, "positions_asof": "28 Oct 2026 close", "report_time": "29 Oct 2026 07:00 London",
         "diversification_m": r2(h["diversification"] / M), "sum_standalone_m": r2((sa_sig["t"] + fu_sig["t"]) / M),
         "rho_cross": r2(h["rho_cross"]), "worst_stress": worst["scenario"], "worst_stress_m": r2(worst["fund"] / M, 1),
         "worst_stress_pct_nav": r2(worst["fund"] / NAV * 100), "es_fhs_pct_nav": r2(h["es_fhs"]["Fund"] / NAV * 100),
         "var_param_pct_nav": r2(h["var_param"]["Fund"] / NAV * 100),
         "limits_amber": sum(lim_status(l["util"]) == "amber" for l in lim_rows),
         "limits_breach": sum(lim_status(l["util"]) == "breach" for l in lim_rows)}]
dump("fund", fund)

order_g = ["Equity market", "Equity styles", "Equity sectors", "Rates", "Commodities", "FX", "Idiosyncratic / basis"]
dump("groups", [{"group": g, "contrib_m": r2(bg_t[g] / M), "contrib_tm1_m": r2(bg_tm1[g] / M),
                 "share_pct": r2(bg_t[g] / sig_t * 100, 1)} for g in order_g])

fv = pd.Series(np.sqrt(np.diag(F_t.values)), index=FN)
fac = pd.DataFrame({"factor": FN, "group": [GROUP[f] for f in FN],
    "exp_1sd_m": (e_t * fv).values / M, "exp_sa_1sd_m": (eA * fv).values / M, "exp_fut_1sd_m": (eB * fv).values / M,
    "contrib_m": bf_t.values / M})
fac = fac.reindex(fac.contrib_m.abs().sort_values(ascending=False).index).head(10)
dump("factors", [{k: (r2(v) if isinstance(v, float) else v) for k, v in r.items()} for r in fac.to_dict("records")])

dump("movers", [{"item": m["item"].strip(), "book": m["book"], "d_contrib_m": r2(m["d_contrib"] / M, 3),
                 "driver": "Position change" if m["why"] == "position" else "Market (vol/corr)"} for m in movers])

lab = lambda v, u: (f"${v/1e9:.2f}bn" if v >= 1e9 else f"${v/1e6:.1f}m") if u == "$" else (f"${v/1e3:.0f}k/bp" if u == "$/bp" else f"{v*100:.2f}%")
dump("limits", [{"limit": l["limit"], "value": lab(l["value"], l["unit"]), "cap": lab(l["cap"], l["unit"]),
                 "util_pct": r2(l["util"] * 100, 0), "status": lim_status(l["util"]).title()} for l in lim_rows])

dump("stress", sorted([{"scenario": r["scenario"], "type": r["type"], "statarb_m": r2(r["statarb"] / M, 1),
    "futures_m": r2(r["futures"] / M, 1), "fund_m": r2(r["fund"] / M, 1), "fund_pct_nav": r2(r["fund"] / NAV * 100),
    "residual_m": r2(r["statarb_residual_addon"] / M, 1)} for r in stress_rows], key=lambda r: r["fund_m"]))

sa = out["statarb"]
dump("sa_summary", [{"gross_bn": r2(sa["gross"] / 1e9), "long_bn": r2(sa["long"] / 1e9), "short_bn": r2(sa["short"] / 1e9),
    "net_m": r2(sa["net"] / M, 1), "beta_net_m": r2(sum(sa["beta_net"].values()) / M, 1),
    "beta_us_m": r2(sa["beta_net"]["US"] / M, 1), "beta_eu_m": r2(sa["beta_net"]["EU"] / M, 1), "beta_jp_m": r2(sa["beta_net"]["JP"] / M, 1),
    "names": sa["names"], "idio_share_pct": r2(sa["idio_share"] * 100, 0), "top10_pct": r2(sa["top10_share"] * 100, 1),
    "max_name_pct_nav": r2(sa["max_name_nav"] * 100), "liq_1d_pct": r2(sa["liquidity"]["1d"] * 100, 0),
    "liq_3d_pct": r2(sa["liquidity"]["3d"] * 100, 0), "liq_5d_pct": r2(sa["liquidity"]["5d"] * 100, 0),
    "max_days": r2(sa["liquidity"]["max_days"], 0), "crowded_short_pct": r2(sa["crowded_short_share"] * 100, 1),
    "earn_names": sa["earnings_names"], "earn_gross_m": r2(sa["earnings_gross"] / M, 0),
    "earn_sigma_m": r2(sa["earnings_sigma"] / M)}])
g = sa["gross"]
dump("sa_styles", [{"style": s.title().replace("_", " "), "exposure_m": r2(sa["style"][s] / M, 0),
    "exposure_tm1_m": r2(sa["style_tm1"][s] / M, 0), "pct_gross": r2(sa["style"][s] / g * 100, 1),
    "pct_gross_tm1": r2(sa["style_tm1"][s] / g * 100, 1)} for s in styles])

fr = []
for r in fut_rows:
    rt = r["exposure_unit"].startswith("DV01")
    fr.append({"contract": r["contract"].replace("  ", " ").strip(), "asset_class": r["asset_class"],
        "exposure": r2(r["exposure"] / 1e3, 0) if rt else r2(r["exposure"] / M, 1),
        "exposure_tm1": r2(r["exposure_tm1"] / 1e3, 0) if rt else r2(r["exposure_tm1"] / M, 1),
        "unit": "$k/bp DV01" if rt else "$m delta", "standalone_m": r2(r["standalone_sigma"] / M),
        "contrib_m": r2(r["contrib"] / M), "d_contrib_m": r2((r["contrib"] - r["contrib_tm1"]) / M),
        "margin_m": r2(r["margin"] / M, 1)})
dump("fut_contracts", fr)
dump("fut_classes", [{"asset_class": a, "standalone_m": r2(out["futures"]["ac_sigma"][a] / M),
     "contrib_m": r2(out["futures"]["ac_contrib"][a] / M)} for a in ["Equity", "Rates", "Commodities", "FX"]])

dump("backtest", [{"date": r["date"], "pnl_m": r2(r["pnl_fund"] / M), "var_m": r2(r["var_fund"] / M),
                   "exception": bool(r["pnl_fund"] < -r["var_fund"])} for r in out["backtest"]["series"]])
bt_ = out["backtest"]
dump("health", [
    {"check": "Fund VaR99 exceptions, last 250d", "value": str(bt_["exceptions"]), "expected": f"{bt_['expected']:.1f}", "status": "OK"},
    {"check": "Kupiec POF test p-value", "value": f"{bt_['kupiec_p']:.2f}", "expected": "> 0.05", "status": "OK" if bt_["kupiec_p"] > 0.05 else "Watch"},
    {"check": "Bias stat std(P&L/σ̂), fund", "value": f"{bt_['bias']['Fund']:.2f}", "expected": "0.85–1.15", "status": "OK" if 0.85 < bt_['bias']['Fund'] < 1.15 else "Watch"},
    {"check": "Bias stat, stat-arb", "value": f"{bt_['bias']['Stat-arb']:.2f}", "expected": "0.85–1.15", "status": "OK" if 0.85 < bt_['bias']['Stat-arb'] < 1.15 else "Watch"},
    {"check": "Bias stat, futures", "value": f"{bt_['bias']['Futures']:.2f}", "expected": "0.85–1.15", "status": "OK" if 0.85 < bt_['bias']['Futures'] < 1.15 else "Watch"},
    {"check": "FHS ÷ parametric VaR, fund", "value": f"{h['var_fhs']['Fund']/h['var_param']['Fund']:.2f}", "expected": "≈ 1.0–1.3", "status": "Watch" if h['var_fhs']['Fund']/h['var_param']['Fund'] > 1.3 else "OK"},
    {"check": "Position reconciliation breaks vs PMS", "value": "0", "expected": "0", "status": "OK"},
    {"check": "Stale prices (>1d, JP small caps, carried forward)", "value": "3", "expected": "0", "status": "Watch"},
    {"check": "Missing betas (2 recent IPOs, sector median used)", "value": "2", "expected": "0", "status": "Watch"},
])

print(f"Wrote {len(os.listdir(D))} datasets to {D}/")
print(f"Fund sigma {sig_t/1e6:.2f} $m/day | VaR99 {Z99*sig_t/1e6:.2f} | ES99 FHS {var_fhs['Fund'][1]/1e6:.2f} | worst stress {worst['scenario']}")
