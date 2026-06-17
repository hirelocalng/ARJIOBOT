# Profile Freeze

The strategy profile layer is frozen under `PROTECTED_PROFILE_LOGIC`.

`profiles.lock.json` is the source of truth for locked strategy profile records and protected strategy source hashes. The backend verifies this lock at app startup, and the CSV backtest runner verifies it before running strategy logic.

Runtime warning:

```text
Profile freeze active: strategy logic locked.
```

Local validation:

```powershell
python -m pytest backend/arjiobot/profile_freeze/tests -q
```

## Allowed Changes

- Bitget/Binance exchange connectors
- Demo/live mode switching
- Exchange credentials
- Isolated margin sizing
- Execution guards
- Order management
- SL/TP execution handling
- Trade logs and live/demo reporting

## Forbidden Changes

- Profile parameters
- Profile logic
- Timeframe structure
- Swing/FVG/retrace/entry strategy filters
- TP model behavior for locked profiles
- Recovered legacy behavior
- Profile registry behavior
- Optimization logic that mutates profiles

## Intentional Profile Migration

Profile mutation is blocked by default. For an intentional, reviewed migration only, set:

```powershell
$env:ALLOW_PROFILE_MUTATION = "true"
```

Then regenerate and review `profiles.lock.json`. Do not use this for exchange, risk, execution, credential, or logging work.

## Visible Profile

Only `PROFILE_RECOVERED_HIGH_WINRATE` and `PROFILE_2` are visible/selectable in the frontend. Other profile definitions remain in the repository for forensic reference and are not deleted.
