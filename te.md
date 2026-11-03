
Tracking error vs cumulative performance · TXT
TRACKING ERROR AND CUMULATIVE RELATIVE PERFORMANCE
Notes on Alexander, Market Risk Analysis Vol. II, Ch. II.1, Sections II.1.5-II.1.6,
extended with a horizon (drift vs diffusion) analysis.
Companion code: te_analysis.py   Figure: te_vs_cumulative.png
=====================================================================================
 
 
0. SUMMARY
----------
Tracking error (TE) is the standard deviation of active returns. It measures the
NOISE of the fund around its own mean active return, never the DISTANCE of the fund
from the benchmark. Cumulative relative performance contains both the noise and the
mean (drift). The noise grows like sqrt(H); the drift grows like H. So:
 
    TE describes relative risk at short horizons;
    the drift dominates beyond the crossover horizon  H* = (TE / mu)^2 = 1 / IR^2.
 
TE is estimated precisely and the drift is estimated very poorly. That is why risk
models forecast TE, and why cumulative performance keeps surprising people.
 
 
1. DEFINITIONS (BOOK, II.1.6.1 - II.1.6.4)
-----------------------------------------
Portfolio and benchmark one-period returns:
    R_P,t = V_P,t / V_P,t-1 - 1          R_B,t = V_B,t / V_B,t-1 - 1
 
Active return, geometric definition (II.1.44):
    (1 + a_t)(1 + R_B,t) = (1 + R_P,t)   =>   a_t = (1 + R_P,t)/(1 + R_B,t) - 1
 
Active log return (II.1.47):
    l_t = ln(1 + a_t) = r_P,t - r_B,t
 
Active weights (II.1.50):
    w_a,i = w_P,i - w_B,i ,   l_t ~= sum_i w_a,i r_i,t   (log approx., short periods)
 
Why the geometric definition is the right one:
    prod_t (1 + a_t) = W_P(H) / W_B(H)        (exact)
i.e. geometric active returns compound EXACTLY to the fund/benchmark wealth ratio.
Arithmetic differences R_P - R_B do not.
 
Ex post tracking error (II.1.51):
    TE = sqrt( 1/(T-1) * sum_t (a_t - a_bar)^2 ) ,   annualised by sqrt(h)
 
Ex post mean-adjusted tracking error, MATE (II.1.52-53):
    MATE = sqrt( 1/T * sum_t a_t^2 )
    MATE^2 = (T-1)/T * TE^2 + a_bar^2
 
Ex ante, from a factor model of active returns (II.1.54-56):
    a = alpha + beta' X + eps
    E[a] = alpha + beta' E[X]
    V[a] = beta' Sigma beta + V(eps)            ex ante TE = sqrt(V[a]), annualised
In holdings form:
    TE^2 = w_a' Sigma_assets w_a = b_a' Sigma_F b_a + w_a' Omega w_a
           (b_a = B w_a: active factor exposures; Omega: specific covariance)
 
Ex ante MATE (II.1.57, corrected):
    MATE = sqrt( TE^2 + (E[a] - a*)^2 )         a* = target active return
    (the book prints V(Y)^2; it should be V(Y) = TE^2)
 
 
2. THE BOOK'S ARGUMENT
----------------------
Claim: TE is a valid measure of active risk only for funds that TRACK the benchmark
(E[a] = 0). For active funds it ignores the risk that the mean active return differs
from zero or from the target.
 
Supporting examples (numbers re-checked):
 
Ex II.1.8   Active return exactly -1% every month  =>  TE = 0. Fund steadily
            underperforms, yet "zero risk".
 
Ex II.1.9   16 annual returns. Fund ends at 164 vs benchmark 319 (half).
            TE = 1%, but mean active return = -4.06%/yr.
            Check: (164/319)^(1/16) - 1 = -4.07%.  Consistent.
 
Ex II.1.10  One fund, two benchmarks. TE = 1.38% against both, yet the fund tracks
            benchmark 1 (mean active -0.04%) and trails benchmark 2 (-3.04%).
            Conclusion: TE is blind to the LEVEL of the benchmark.
 
Ex II.1.11  MATE:  (a) sqrt(0.01^2*15/16 + 0.0406^2) = 4.18%
                   (b) bmk 1: 1.34%   bmk 2: 3.32%
            MATE separates the two cases; TE does not.
 
Ex II.1.12  Fund A tracks (mean active 0, TE 2.38%, MATE 2.30%);
            Fund B lags by "5% every year" (TE 0, MATE 5%).
            CORRECTIONS:
              - The text calls the underperformer "fund A"; it is fund B.
              - Fund B's active returns are arithmetic (-5% flat) while fund A's use
                the geometric definition. Geometrically, B's active returns range from
                -4.2% to -6.7%, so TE_B ~= 0.62%, not 0. Conclusion unchanged.
              - MATE_A < TE_A is just the (T-1)/T factor with a_bar = 0.
 
Ex II.1.13  Ex ante TE = 4% for both; E[a] = 0% (A) and 1% (B); target 2%.
            MATE_A = sqrt(.04^2+.02^2) = 4.47%,  MATE_B = sqrt(.04^2+.01^2) = 4.12%.
 
Ex II.1.14  E[a] = 1% for both; TE_A = 2%, TE_B = 5%. Assuming normality:
              P(a < 0): A = Phi(-0.5) = 31%,  B = Phi(-0.2) = 42%  -> B riskier
              P(a < 2%): A = Phi(+0.5) = 69%, B = Phi(+0.2) = 58%  -> A riskier
            MATE ranks B riskier for BOTH targets ("benchmarks" in the text should
            read "targets"): MATE is symmetric, not a downside measure.
 
Book's proposed properties of an active-risk metric (II.1.7):
    (a) metric falls     => fund moves closer to the benchmark
    (b) fund moves closer => metric falls
The book says TE has neither.
 
 
3. WHERE THE BOOK IS RIGHT, AND WHERE IT OVERREACHES
---------------------------------------------------
Right:
  - TE is dispersion about E[a], not about 0 and not about the target.
    Quoting TE as a confidence band around a TARGET outperformance is wrong unless
    E[a] = target.
  - Ex post TE can be tiny for a fund that is drifting far away from its benchmark.
 
Overreaches:
  - EX ANTE, TE = sqrt(w_a' Sigma w_a) is a norm on active weights (Sigma > 0):
    TE = 0 iff w_a = 0 (fund = benchmark). In the Sigma-metric it DOES satisfy (a)
    and (b). The pathologies are ex post (time-varying weights, drifting mean).
  - It conflates mean and dispersion. A fund that loses 4%/yr steadily has a
    MEAN problem (negative alpha). The right diagnostic is the information ratio and
    the t-stat of the mean active return, not a "better" risk measure.
  - "If E[a] < target, investors prefer a large TE": true only for shortfall
    PROBABILITY Phi((a* - mu)/sigma). For expected shortfall magnitude (lower partial
    moments), larger sigma always makes it worse. The conclusion depends on the metric.
  - MATE is frequency dependent (see section 4.3), a defect the book does not note.
 
 
4. TRACKING ERROR vs CUMULATIVE RELATIVE PERFORMANCE
----------------------------------------------------
4.1 Model
    l_t = mu*dt + sigma*sqrt(dt)*z_t ,  z_t i.i.d. N(0,1)
    A_H = sum_{t<=H} l_t = ln( W_P(H)/W_B(H) )  ~  N( mu*H , sigma^2*H )
 
    sigma = TE      -> diffusion, grows like sqrt(H)
    mu    = drift   -> systematic out/underperformance, grows like H
    Cumulative relative performance = exp(A_H) - 1  (contains both)
 
4.2 Horizon decomposition
    Diffusion                     sigma * sqrt(H)
    Drift                         mu * H
    RMS gap to benchmark          sqrt( sigma^2*H + mu^2*H^2 )
    P(trail benchmark over H)     Phi( -IR * sqrt(H) ),   IR = mu / sigma
    Crossover horizon             H* = (sigma/mu)^2 = 1/IR^2
 
    H << H*  : relative risk ~ TE*sqrt(H)  (TE is the right descriptor)
    H >> H*  : relative outcome ~ mu*H     (drift dominates; TE nearly irrelevant)
 
    Examples:
      Book Ex II.1.9 (TE 1%, mu -4%):  IR = -4,  H* = 1/16 yr ~ 3 weeks
      Typical active fund (TE 4%, mu +2%): IR = 0.5, H* = 4 yrs
          P(trail) = 31% at 1y, 16% at 4y, 2.3% at 16y
 
4.3 MATE is a one-period special case and frequency dependent
    Per period: MATE^2 = sigma^2*dt + mu^2*dt^2. Annualised with the book's
    convention: MATE_ann^2 = sigma^2 + mu^2*dt.
      Fund with TE 1%, mu -4%:  monthly data -> MATE ~ 1.5%
                                annual data  -> MATE ~ 4.1%
    The frequency-free object is the horizon RMS  sqrt(sigma^2*H + mu^2*H^2).
 
4.4 The estimation asymmetry (why TE is what gets forecast)
    SE(sigma_hat) ~= sigma / sqrt(2T)          precise, even with 1y of daily data
    SE(mu_hat_ann) = sigma / sqrt(years)       independent of sampling frequency
    Years needed for a t-stat of t on the drift:  (t / IR)^2
      IR = 0.5, t = 2  ->  16 years
    Cumulative performance is dominated by the parameter we estimate worst.
 
4.5 When sqrt-time scaling of TE fails
    Variance ratio  VR(H) = Var(sum of H active returns) / (H * Var(l))
      VR = 1  i.i.d. active returns
      VR > 1  persistent active bets (factor/style tilts, trend exposure):
              TE * sqrt(H) UNDERSTATES horizon relative risk by sqrt(VR)
              (AR(1) with rho = 0.5: VR(12) ~ 2.7 -> understated by ~1.6x)
      VR < 1  non-synchronous closes between fund and benchmark, mean reversion:
              daily TE OVERSTATES horizon risk
    Remedy: estimate TE on the horizon you care about, or Newey-West / VR-adjust.
 
4.6 Path risk: relative drawdown
    W_t = exp(cumsum l_t);   DD_t = W_t / max_{s<=t} W_s - 1
    Max relative drawdown depends on IR and horizon, not on sigma alone. TE carries
    no path information.
 
 
5. SIMULATION (16 years, monthly, seed 11; see te_vs_cumulative.png)
-------------------------------------------------------------------
                           TE     drift    IR      t      MATE    cum     maxDD   H*(y)
Fund 1 (TE 1%, -4%/yr)   0.91%  -3.93%  -4.31  -17.2   1.45%  -46.7%  -46.5%   0.06
Fund 2 (TE 5%,  0)       5.09%   1.19%   0.23    0.9   5.09%   20.9%  -12.2%    inf
Fund 3 (TE 4%, +2%/yr)   3.74%   1.69%   0.45    1.8   3.76%   31.1%   -7.3%    4.0
 
Reading:
  - Fund 1 has the lowest TE and the worst outcome: -47% relative. TE says nothing.
  - Fund 2 has zero true drift but ends +21% by chance: pure diffusion.
  - Fund 3 (true IR 0.5) is still NOT statistically significant after 16 years.
  - Across seeds, Fund 3's sample drift ranged 0.8%-3.7% while its TE stayed
    3.7%-4.1%: the estimation asymmetry of 4.4, in practice.
  - The monthly MATE of Fund 1 (1.45%) barely registers the -4% drift (see 4.3).
 
 
6. PSEUDOCODE
-------------
INPUT: fund returns R_P[t], benchmark returns R_B[t], periods per year h
 
# ex post
l      = log((1 + R_P) / (1 + R_B))          # active log returns, additive
TE     = std(l, ddof=1) * sqrt(h)
mu     = mean(l) * h
IR     = mu / TE
t_stat = IR * sqrt(T / h)
MATE   = sqrt(mean(l^2) * h)                 # frequency dependent: report with care
W      = exp(cumsum(l))                      # cumulative relative performance
DD     = W / cummax(W) - 1 ;  maxDD = min(DD)
VR(H)  = var(rolling_sum(l - mean(l), H)) / (H * var(l))
rollTE = rolling_std(l, 36) * sqrt(h)        # regime shifts, style drift
 
# horizon profile (H in years)
drift(H)     = mu * H
diffusion(H) = TE * sqrt(H) * sqrt(VR)       # VR-adjusted if persistence present
rms(H)       = sqrt(diffusion(H)^2 + drift(H)^2)
p_under(H)   = Phi(-IR * sqrt(H))
H_star       = 1 / IR^2
 
# ex ante (factor model)
Sigma  = B' Sigma_F B + Omega
TE     = sqrt(w_a' Sigma w_a)
factor_TE2   = (B w_a)' Sigma_F (B w_a)
specific_TE2 = w_a' Omega w_a
MCTE   = Sigma w_a / TE                      # marginal contribution
CTE    = w_a * MCTE                          # Euler: sum(CTE) = TE
 
# forecast backtest
z_t = realised active return_t / forecast TE_t   (same horizon)
calibrated  <=>  std(z) ~= 1 ;  bias statistic = std(z) over rolling windows
 
 
7. REPORTING RECOMMENDATION
---------------------------
Report together:
  TE (ex ante and ex post)       noise of active returns
  IR and its t-stat              is there a drift, and can we tell?
  H* = 1/IR^2                    horizon beyond which drift dominates
  P(trail benchmark) at the client horizon, Phi(-IR*sqrt(H))
  VR at the client horizon       is sqrt-time scaling valid?
  Max relative drawdown          path risk
  Factor vs specific split of TE, with Euler contributions
 
TE alone describes the noise band; the drift decides where the fund ends up.
