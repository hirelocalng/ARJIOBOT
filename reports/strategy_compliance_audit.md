# Strategy Compliance Audit

| Rule | Expected behavior | Status | File path | Function/class | Fix applied | Remaining risk |
|---|---|---|---|---|---|---|
| Swing high strict greater-than | High(C2) > High(C1) and High(C2) > High(C3) | PASS | `backend/arjiobot/swings/swings.py` | `ThreeCandleSwingDefinition.is_swing_high` | Strict > used; equality rejected. | None |
| Swing low strict less-than | Low(C2) < Low(C1) and Low(C2) < Low(C3) | PASS | `backend/arjiobot/swings/swings.py` | `ThreeCandleSwingDefinition.is_swing_low` | Strict < used; equality rejected. | None |
| Bearish FVG strict | Low(C1) > High(C3) | PASS | `backend/arjiobot/fvg/fvg.py` | `FVGDetectionEngine._detect_window` | Strict > used. | None |
| Bullish FVG strict | High(C1) < Low(C3) | PASS | `backend/arjiobot/fvg/fvg.py` | `FVGDetectionEngine._detect_window` | Strict < used. | Bullish is supported but strategy is bearish-first. |
| Expansion ratio | 2.0 <= ratio <= 4.0 | PASS | `backend/arjiobot/expansion/expansion.py` | `ExpansionDetectionEngine.detect_from_swing` | Bounds are inclusive. | None |
| Bearish expansion displacement | C3 must move downward | PASS | `backend/arjiobot/expansion/expansion.py` | `displacement_for_swing` | Bearish distance uses middle low minus right close. | None |
| HTF FVG tap | Wait for price to tap HTF bearish FVG | PARTIAL | `backend/arjiobot/fvg/fvg.py` | `FVGDetectionEngine.mark_tapped` | Tap exists; full orchestrated strategy pipeline is not yet a single service. | Needs historical orchestration during large CSV strategy pass. |
| 16M swing high | Valid 3-candle swing high | PASS | `backend/arjiobot/swings/swings.py` | `SwingDetectionEngine.detect_all_swings` | Strict swing engine reused for 16M. | None |
| 16M FVG after swing | Bearish FVG includes displacement candle | PASS | `backend/arjiobot/fvg/fvg.py` | `FVGDetectionEngine._detect_window` | Links expansion to FVG C2 and strategy FVG flag. | Immediate-after-swing orchestration remains service-level. |
| 16M leg | swing high to low of 16M FVG completion candle | PASS | `backend/arjiobot/setup_tracker/setup_timing.py` | `calculate_target_references` | Target A uses 16M FVG completion candle low. | None |
| 12M FVG inside 16M leg | Bearish 12M FVG inside leg | PASS | `backend/arjiobot/setup_tracker/setup_tracker.py` | `qualify_fvg_inside_16m_leg` | Rejects outside leg. | None |
| 8M FVG inside 16M leg | Bearish 8M FVG inside same leg | PASS | `backend/arjiobot/setup_tracker/setup_tracker.py` | `qualify_fvg_inside_16m_leg` | Same leg validator used. | None |
| 3 completed 8M retrace window | Tap within first 3 8M candles | PASS | `backend/arjiobot/setup_tracker/setup_invalidation.py` | `should_invalidate_retrace_window` | Invalidates after three untapped candles. | None |
| 12M FVG tap close boundary | Tap/high candles must not close above upper boundary | PASS | `backend/arjiobot/setup_tracker/setup_invalidation.py` | `close_above_12m_fvg` | Tapping candle close above upper invalidates. | None |
| Second high allowed once | Second high may close inside/below | PASS | `backend/arjiobot/fvg/fvg_tap_rules.py` | `evaluate_bearish_high_sequence` | Allows up to two rising highs. | None |
| Third high invalidation | Third new high inside 12M FVG invalidates | PASS | `backend/arjiobot/setup_tracker/setup_invalidation.py` | `high_sequence_invalidation_reason` | Third high maps to THIRD_HIGH_INSIDE_12M_FVG. | Consolidation reason is reserved but not separately reachable before third high. |
| 1M bearish FVG confirmation | Confirm bearish 1M FVG after swing high | PARTIAL | `backend/arjiobot/fvg/fvg.py` | `FVGDetectionEngine._detect_window` | 1M bearish FVG detection exists. | Full sequence is not yet one orchestrator. |
| Entry from first/second 1M FVG retest | ENTRY_READY only after retest | PARTIAL | `backend/arjiobot/setup_tracker/setup_tracker.py` | `mark_entry_ready` | Entry-ready API exists and target-before-entry guard exists. | First/second FVG retest ordering is not enforced by a dedicated orchestrator. |
| Target before entry | Invalidate before entry if target reached | PASS | `backend/arjiobot/setup_tracker/setup_tracker.py` | `mark_entry_ready` | Invalidates when latest_price <= final target. | None |
| Strategy signal only ENTRY_READY | MARKET_SELL_READY only from ENTRY_READY | PASS | `backend/arjiobot/strategy/strategy_engine.py` | `generate_signal_from_setup` | Existing Strategy Engine validation rejects non-entry-ready setups. | None |
| Risk stop/target passthrough | Risk does not recalc stop/target | PASS | `backend/arjiobot/risk/risk_engine.py` | `create_trade_plan` | TradePlan carries signal stop/target references. | None |
| Execution paper-only | No live orders | PASS | `backend/arjiobot/execution/paper_executor.py` | `paper_execute` | Paper execution only; Bitget not called. | None |
| Backtest entry no-lookahead | Next available 1M candle open after signal | PASS | `backend/arjiobot/backtesting/trade_simulator.py` | `simulate_trade` | Uses first candle timestamp > generated_at. | None |
| Conservative same-candle | TP/SL same candle uses stop-first | PASS | `backend/arjiobot/backtesting/trade_simulator.py` | `simulate_trade` | Default policy supports CONSERVATIVE_STOP_FIRST. | None |
| Live trading disabled | Default no live trading | PASS | `backend/arjiobot/exchange/live_trading_guard.py` | `evaluate_live_trading_guard` | Central guard rejects unless all future conditions are true. | None |
