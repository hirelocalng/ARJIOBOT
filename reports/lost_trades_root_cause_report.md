# Lost Trades Root Cause Report

Dataset: `ArjioBot/data/SOLUSDT-1m-2026-04.csv`
Pair: `SOLUSDT`; fixed risk: `100`; fees/slippage: `0`; date range: April 2026 CSV.

Investigation only. No strategy rules, production settings, or optimizer settings were changed.

## Executive Root Cause

The major lost-opportunity cause is the expansion/16M-leg qualification stack before entry: first the selected expansion range rejects most 16M swing candidates, then many surviving candidates fail to produce the immediate C3-driven 16M FVG, and a smaller but still material group expires before a 1M retrace into the 12M FVG.

The major losing-trade cause is not one single entry failure. On this dataset, `RR_1_5_CURRENT` produces higher full-period net PnL but weaker validation than `RR_1_0`; many losses are explained by RR 1.5 being too far for the validation segment, while structure-boundary TP has high win rate but too few valid trades because TP is often invalid or too close.

## Lost Opportunities Funnel
### PROFILE_F_VOLUME
| Stage | Count | % of candidates |
|---|---:|---:|
| 16M swing candidates | 602 | 100.00% |
| C3 expansion / ratio rejected | 403 | 66.94% |
| passed expansion | 199 | 33.06% |
| 16M FVG missing | 129 | 21.43% |
| passed 16M FVG | 70 | 11.63% |
| 12M FVG missing / same-leg failed | 3 | 0.50% |
| passed 12M FVG | 67 | 11.13% |
| 8M FVG missing / same-leg failed | 0 | 0.00% |
| passed 8M FVG | 67 | 11.13% |
| retracement window expired / no 1M entry into 12M FVG | 30 | 4.98% |
| passed retrace | 37 | 6.15% |
| 1M close beyond 12M FVG boundary | 0 | 0.00% |
| duplicate 12M FVG trade blocked | 17727 | 2944.68% |
| signals generated / entry ready | 37 | 6.15% |
| risk rejected | 0 | 0.00% |

### PROFILE_F_BALANCED
| Stage | Count | % of candidates |
|---|---:|---:|
| 16M swing candidates | 602 | 100.00% |
| C3 expansion / ratio rejected | 533 | 88.54% |
| passed expansion | 69 | 11.46% |
| 16M FVG missing | 34 | 5.65% |
| passed 16M FVG | 35 | 5.81% |
| 12M FVG missing / same-leg failed | 1 | 0.17% |
| passed 12M FVG | 34 | 5.65% |
| 8M FVG missing / same-leg failed | 0 | 0.00% |
| passed 8M FVG | 34 | 5.65% |
| retracement window expired / no 1M entry into 12M FVG | 17 | 2.82% |
| passed retrace | 17 | 2.82% |
| 1M close beyond 12M FVG boundary | 0 | 0.00% |
| duplicate 12M FVG trade blocked | 6165 | 1024.09% |
| signals generated / entry ready | 17 | 2.82% |
| risk rejected | 0 | 0.00% |

### PROFILE_F_SELECTIVE
| Stage | Count | % of candidates |
|---|---:|---:|
| 16M swing candidates | 602 | 100.00% |
| C3 expansion / ratio rejected | 572 | 95.02% |
| passed expansion | 30 | 4.98% |
| 16M FVG missing | 9 | 1.50% |
| passed 16M FVG | 21 | 3.49% |
| 12M FVG missing / same-leg failed | 0 | 0.00% |
| passed 12M FVG | 21 | 3.49% |
| 8M FVG missing / same-leg failed | 0 | 0.00% |
| passed 8M FVG | 21 | 3.49% |
| retracement window expired / no 1M entry into 12M FVG | 11 | 1.83% |
| passed retrace | 10 | 1.66% |
| 1M close beyond 12M FVG boundary | 0 | 0.00% |
| duplicate 12M FVG trade blocked | 3198 | 531.23% |
| signals generated / entry ready | 10 | 1.66% |
| risk rejected | 0 | 0.00% |

### STRICT_PROFILE
| Stage | Count | % of candidates |
|---|---:|---:|
| 16M swing candidates | 602 | 100.00% |
| C3 expansion / ratio rejected | 572 | 95.02% |
| passed expansion | 30 | 4.98% |
| 16M FVG missing | 9 | 1.50% |
| passed 16M FVG | 21 | 3.49% |
| 12M FVG missing / same-leg failed | 0 | 0.00% |
| passed 12M FVG | 21 | 3.49% |
| 8M FVG missing / same-leg failed | 0 | 0.00% |
| passed 8M FVG | 21 | 3.49% |
| retracement window expired / no 1M entry into 12M FVG | 11 | 1.83% |
| passed retrace | 10 | 1.66% |
| 1M close beyond 12M FVG boundary | 0 | 0.00% |
| duplicate 12M FVG trade blocked | 0 | 0.00% |
| signals generated / entry ready | 0 | 0.00% |
| risk rejected | 0 | 0.00% |

## Top 3 Lost-Opportunity Stages
1. C3 expansion / ratio rejected: 403 candidates in PROFILE_F_VOLUME.
2. 16M FVG missing after expansion: 129 candidates in PROFILE_F_VOLUME.
3. retracement window expired / no 1M entry: 30 candidates in PROFILE_F_VOLUME.

## Expansion Distribution
| Bucket | Count |
|---|---:|
| below_1_0 | 188 |
| 1_0_to_1_5 | 130 |
| 1_5_to_2_0 | 39 |
| 2_0_to_3_0 | 27 |
| 3_0_to_4_0 | 3 |
| above_4_0 | 2 |

Profile effect: Volume accepts expansion ratios 1.0-4.0 and catches 37 entries; Balanced removes the 1.0-1.5 band and drops to 17 entries; Selective removes 1.0-2.0 and drops to 10 entries. The filter is doing what it is configured to do, but it is the largest source of lost opportunities.

## TP Model Failure Analysis
- PROFILE_F_VOLUME + RR_1_0: trades=37, win_rate=52.78%, net_pnl=200.0000000000000000000000000, PF=1.117647058823529411764705882, validation=12 trades / 54.55% / PnL 100.0000000000000000000000000.
- PROFILE_F_VOLUME + 8M_PRE_RETRACE_EXTREME: trades=25, win_rate=64.00%, net_pnl=-70.88653803649328993455717614, PF=0.9212371799594519000727142488, validation=7 trades / 42.86% / PnL -331.5146595178311842775963299.
- PROFILE_F_VOLUME + RR_1_5_CURRENT: trades=37, win_rate=44.44%, net_pnl=400.0000000000000000000000000, PF=1.2, validation=12 trades / 36.36% / PnL -99.99999999999999999999999999.
- PROFILE_F_VOLUME + 16M_FVG_BOUNDARY: trades=9, win_rate=88.89%, net_pnl=159.7030531496550914026642182, PF=2.597030531496550914026642182, validation=4 trades / 75.00% / PnL 14.96503496503496503496503496.
- PROFILE_F_SELECTIVE + RR_1_5_CURRENT: trades=10, win_rate=50.00%, net_pnl=250.0000000000000000000000000, PF=1.5, validation=3 trades / 66.67% / PnL 200.0000000000000000000000000.
- PROFILE_F_SELECTIVE + RR_1_0: trades=10, win_rate=50.00%, net_pnl=0E-26, PF=1, validation=3 trades / 66.67% / PnL 99.99999999999999999999999999.
- PROFILE_F_BALANCED + RR_1_5_CURRENT: trades=17, win_rate=47.06%, net_pnl=300.0000000000000000000000000, PF=1.333333333333333333333333333, validation=5 trades / 40.00% / PnL 1E-26.
- PROFILE_F_BALANCED + 16M_FVG_BOUNDARY: trades=6, win_rate=83.33%, net_pnl=-47.67789923129728954971673419, PF=0.5232210076870271045028326581, validation=3 trades / 66.67% / PnL -65.03496503496503496503496504.
- PROFILE_F_SELECTIVE + 8M_PRE_RETRACE_EXTREME: trades=6, win_rate=83.33%, net_pnl=11.76804422582886207989142754, PF=1.117680442258288620798914275, validation=2 trades / 50.00% / PnL -76.08695652173913043478260870.
- PROFILE_F_SELECTIVE + 16M_FVG_BOUNDARY: trades=4, win_rate=75.00%, net_pnl=-83.83951539291345116587835034, PF=0.1616048460708654883412164966, validation=2 trades / 50.00% / PnL -92.30769230769230769230769231.
- PROFILE_F_BALANCED + RR_1_0: trades=17, win_rate=52.94%, net_pnl=100.0000000000000000000000000, PF=1.125, validation=5 trades / 40.00% / PnL -100.0000000000000000000000000.
- PROFILE_F_BALANCED + 8M_PRE_RETRACE_EXTREME: trades=12, win_rate=75.00%, net_pnl=6.1264266409995058715355195, PF=1.020421422136665019571785065, validation=3 trades / 33.33% / PnL -176.0869565217391304347826087.

- Trades won under RR_1_0 but lost under RR_1_5_CURRENT: 4
- Trades won under 16M_FVG_BOUNDARY but lost under RR_1_5_CURRENT: 9
- Trades that hit SL before any tested TP model won: 15

## Losing Trade Cause Groups
| Cause | Count |
|---|---:|
| bad entry timing / immediate adverse reaction | 28 |
| unknown | 24 |
| weak expansion | 24 |
| TP too far / RR 1.5 too ambitious | 4 |

## Profile Comparison
- Catches most trades: PROFILE_F_VOLUME (37 direct entries).
- Rejects most by expansion range: PROFILE_F_SELECTIVE (572 rejected_no_expansion).
- Best validation performance in TP optimization ranking: PROFILE_F_VOLUME + RR_1_0.
- Most selective/stable by fewer but cleaner entries: PROFILE_F_SELECTIVE with RR_1_5_CURRENT has positive validation PnL, but only 3 validation trades.
- Loses most from TP distance: PROFILE_F_VOLUME under RR_1_5_CURRENT has 12 validation trades, 36.36% validation win rate, and -100 validation PnL despite positive full-period PnL.
- Weak expansion mainly affects Volume because it admits 1.0-1.5 ratio trades; Balanced/Selective reduce those but also lose trade count.

## STRICT_PROFILE Audit
STRICT_PROFILE is not mechanically broken, but it is effectively blocked by strict post-retrace confirmation/invalidation behavior on this dataset. It reaches 10 passed retraces, then all 10 are rejected by `rejected_close_above_12m_fvg` before entry, so it produces 0 signals and 0 entries.
Responsible function: `scripts/backtest_csv.py::_build_strategy_funnel`, strict branch using `setup_tracker.setup_invalidation.close_above_12m_fvg` before `_classify_1m_confirmation`.

## Root Cause Ranking
1. Expansion filter and C3 expansion availability reject the most setup candidates. Evidence: PROFILE_F_VOLUME rejected_no_expansion=403 of 602 candidates; PROFILE_F_SELECTIVE rejected_no_expansion=572 of 602.
2. Immediate 16M FVG requirement removes many otherwise valid expansions. Evidence: PROFILE_F_VOLUME rejected_no_immediate_16m_fvg=129 after expansion; Balanced=34; Selective=9.
3. Retracement timing removes remaining valid-looking setups. Evidence: PROFILE_F_VOLUME rejected_retrace_window_expired=30; Balanced=17; Selective=11.
4. TP selection changes whether entries become profitable. Evidence: RR_1_0 has best validation stability; RR_1_5_CURRENT has best full-period net PnL but weaker validation for Volume.
5. STRICT_PROFILE is blocked after retrace by 12M FVG close-above invalidation, not by missing swings/FVGs.

## Final Answers

MAIN_CAUSE_OF_LOST_OPPORTUNITIES: Expansion/16M FVG qualification stack, led by expansion ratio/displacement rejection.

MAIN_CAUSE_OF_LOSING_TRADES: TP distance and adverse post-entry reaction; RR_1_5 is profitable full-period but weaker in validation, while RR_1_0 is more stable.

IS_EXPANSION_FILTER_TOO_RESTRICTIVE: NO for configured Selective/Balanced intent, but YES if the goal is maximum trade count; it is the largest trade-count reducer.

IS_TP_MODEL_THE_MAIN_PROBLEM: YES for losing-trade conversion/validation stability, NO for lost opportunities before entry.

IS_ENTRY_LOGIC_THE_MAIN_PROBLEM: NO for Profile F direct entry; direct boundary failures were 0. Strict entry confirmation is the blocker for STRICT_PROFILE.

IS_STRICT_PROFILE_BROKEN: NO, but it is too strict for this dataset and dies at `rejected_close_above_12m_fvg` after 10 passed retraces.

WHICH_PROFILE_IS MOST STABLE: PROFILE_F_VOLUME with RR_1_0 by validation stability and 25+ trade count; PROFILE_F_SELECTIVE is cleaner but sample size is small.

WHICH_TP_MODEL_IS MOST STABLE: RR_1_0.

WHAT SHOULD BE TESTED NEXT: Test Profile F Volume/Balanced with RR_1_0 vs RR_1_5 on additional months/pairs, and separately test whether delayed/non-immediate 16M FVG allowance improves opportunity count without degrading validation.
