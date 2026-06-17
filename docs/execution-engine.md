# Execution Engine Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Execution Engine converts approved Risk Engine `TradePlan` objects into
deterministic execution records. v1 implements paper/simulated execution only.
It does not place real orders, call Bitget, store API keys, or build dashboard
features.

## Purpose

The Execution Engine consumes approved `TradePlan` objects and produces:

- OrderInstruction records
- ExecutionRecord records
- Fill metadata
- Stop loss order plans
- Take profit order plans
- Execution status tracking
- Retry-safe lifecycle records

## Audit Findings And Amendments

- v1 supports bearish `MARKET_SELL_READY` only.
- v1 builds `MARKET_SELL` paper order instructions.
- The engine may only execute approved `TradePlan` objects.
- The engine must not recalculate stop, target, position size, leverage, or
  risk amount. These are produced by the Risk Engine and must be preserved.
- Paper fill price is exactly `entry_reference_price`.
- Protective orders are planned records only in v1.
- One active execution record is allowed per `trade_plan_id`.
- Future exchange adapter methods are represented by an interface boundary, but
  no live Bitget adapter is implemented.
- Deterministic IDs use trade plan identity and caller-supplied timestamps.

## Required TradePlan Fields

- `trade_plan_id`
- `signal_id`
- `setup_id`
- `symbol`
- `direction`
- `action`
- `entry_reference_price`
- `stop_loss_price`
- `take_profit_price`
- `position_size`
- `leverage`
- `risk_amount`
- `rr_ratio`

## OrderInstruction

Every order instruction stores:

- `order_instruction_id`
- `trade_plan_id`
- `signal_id`
- `setup_id`
- `symbol`
- `side`
- `order_type`
- `position_size`
- `leverage`
- `entry_reference_price`
- `stop_loss_price`
- `take_profit_price`
- `reduce_only`
- `time_in_force`
- `created_at`
- `metadata`

For bearish v1:

- `side = SELL`
- `order_type = MARKET`
- `reduce_only = False`

## Execution Lifecycle

Supported statuses:

- `CREATED`
- `VALIDATED`
- `SUBMITTED`
- `PARTIALLY_FILLED`
- `FILLED`
- `PROTECTIVE_ORDERS_PLANNED`
- `CANCELLED`
- `REJECTED`
- `FAILED`

Expected v1 paper lifecycle:

```text
CREATED
VALIDATED
SUBMITTED
FILLED
PROTECTIVE_ORDERS_PLANNED
```

## Rejection Reasons

Supported:

- `TRADE_PLAN_NOT_APPROVED`
- `MISSING_REQUIRED_FIELD`
- `UNSUPPORTED_ACTION`
- `INVALID_POSITION_SIZE`
- `INVALID_LEVERAGE`
- `INVALID_STOP_LOSS`
- `INVALID_TAKE_PROFIT`
- `DUPLICATE_EXECUTION`
- `PAPER_EXECUTION_FAILED`
- `UNKNOWN_EXECUTION_ERROR`

## Service API

Expose:

- `build_order_instruction(trade_plan)`
- `execute_trade_plan(trade_plan)`
- `paper_execute(order_instruction)`
- `get_execution_by_id(execution_id)`
- `get_execution_by_trade_plan_id(trade_plan_id)`
- `get_executions_by_status(status)`
- `get_open_executions(symbol=None)`
- `get_filled_executions(symbol=None)`
- `cancel_execution(execution_id, reason=None)`
- `mark_execution_status(execution_id, status, changed_at, reason=None)`

## Known Limitations

- v1 is paper execution only.
- v1 does not call Bitget or place live orders.
- v1 protective orders are planned records only.
- v1 supports bearish `MARKET_SELL_READY` only.

## Final Validation Report

Execution date: 2026-06-06

- Tests executed: 21
- Tests passed: 21
- Order instruction validation: PASS
- Paper execution validation: PASS
- Duplicate protection validation: PASS
- Protective order planning validation: PASS
- Adapter boundary validation: PASS
- Benchmark result: PASS, 30 trade plans evaluated in demo benchmark
- HTML report: `backend/arjiobot/execution/reports/execution_validation_report.html`
- PNG report: `backend/arjiobot/execution/reports/execution_validation_report.png`

Validation confirms:

- Execution Engine only consumes approved Risk Engine `TradePlan` objects.
- Execution Engine rejects non-approved, missing-field, unsupported-action, and invalid stop/target plans.
- Execution Engine preserves `stop_loss_price`, `take_profit_price`, `position_size`, `leverage`, and risk-derived values from the TradePlan.
- Bearish v1 instructions are `SELL` `MARKET` instructions with `reduce_only = False`.
- Paper fill price equals `entry_reference_price`.
- Stop loss and take profit protective orders are planned as reduce-only `BUY` records and are not placed live.
- Duplicate execution attempts are rejected with `DUPLICATE_EXECUTION` without replacing the original execution record.
- Future exchange adapter methods are placeholders only; no Bitget calls, API key storage, dashboard work, or live order placement is implemented.

Ready For Integration: YES
