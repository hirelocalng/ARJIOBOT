# Backend API Routes Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Backend API Routes module exposes frozen ArjioBot services through modular
FastAPI `APIRouter` route groups for future dashboard use. It must not rewrite
trading logic, duplicate strategy logic, place live orders directly, or expose
API secrets.

## Audit Findings And Amendments

- Route ownership is grouped by module: health, accounts, pairs, settings,
  radar/setups, signals, risk, execution, backtesting, and reports.
- All responses use `{ "success": true, "data": ... }`.
- Errors use `{ "success": false, "error": { "code": "...", "message": "..." } }`.
- Account routes return safe masked credential records only.
- Live order routes do not exist in v1.
- Execution routes expose paper execution only.
- API routes call existing frozen services or service-ready adapters.
- Authentication is not implemented in v1, but `require_local_access()` exists
  as a future middleware/dependency boundary.
- Backtesting CSV upload stores normalized request metadata for v1 API
  validation; dashboard visualization is not implemented.

## Route Groups

- `/api/health`
- `/api/status`
- `/api/accounts`
- `/api/pairs`
- `/api/settings`
- `/api/radar`
- `/api/setups`
- `/api/signals`
- `/api/risk`
- `/api/execution`
- `/api/backtesting`
- `/api/reports`

## Safety Rules

- Do not expose raw API secrets.
- Do not log secrets.
- Do not place real orders directly.
- Do not bypass Risk Engine.
- Do not bypass Execution Engine.
- Do not bypass Bitget adapter safeguards.
- Do not mutate frozen engine internals directly.

## Known Limitations

- v1 does not implement login/authentication.
- v1 does not build frontend/dashboard screens.
- v1 does not expose any live trading route.
- v1 stores API route state in memory for validation and future service wiring.

## Final Validation Report

Execution date: 2026-06-06

- Tests executed: 11
- Tests passed: 11
- Endpoint count: 47
- Account route validation: PASS
- Settings route validation: PASS
- Radar route validation: PASS
- Strategy route validation: PASS
- Risk route validation: PASS
- Execution route validation: PASS
- Backtesting route validation: PASS
- Report route validation: PASS
- OpenAPI validation: PASS
- Security/safety validation: PASS
- HTML report: `backend/arjiobot/api/reports/backend_api_validation_report.html`
- PNG report: `backend/arjiobot/api/reports/backend_api_validation_report.png`

Validation confirms:

- Account responses mask API keys and do not expose API secret or passphrase values.
- The API exposes paper execution only under `/api/execution/paper/{trade_plan_id}`.
- No live execution or live Bitget order route exists in v1.
- Strategy, Risk, Execution, and Exchange routes call their frozen service/adaptor boundaries.
- Error responses use the required `{ success: false, error: { code, message } }` shape.
- Health/status, account, pair, settings, radar/setup, signal, risk, execution, backtesting, report, and OpenAPI endpoints were validated.
- Frontend/dashboard, login/authentication, and live trading remain out of scope.

Ready For Integration: YES
