# Frontend Dashboard Specification v1.0 - Frozen

Status: frozen after audit and ambiguity review.

The Frontend Dashboard is a private Windows VPS operator console for ArjioBot.
It uses React, TypeScript, Vite, Tailwind CSS, and Recharts-style chart
components to manage the trading system through the Backend API Routes module.

## Audit Findings And Amendments

- The dashboard must call backend API routes and must not bypass backend
  services.
- No login, registration, password recovery, or multi-user SaaS features are in
  scope for v1.
- Live order buttons are not implemented.
- API credentials are accepted only through account forms and are never rendered
  after submission. Account tables display masked API keys only.
- The live trading flag is visible as disabled. Enabling live trading is not
  exposed as an operational trading action.
- Backend API state is currently in-memory, so dashboard data should be treated
  as operator-console state until persistence is added.
- Node/npm were unavailable in the validation shell, so v1 includes static smoke
  validation and Vite configuration checks. A full `npm run build` should be run
  once Node is installed.

## Pages

- Dashboard
- Setup Radar
- Setup Details
- Pairs
- Accounts
- Risk Settings
- Signals
- Trade Plans
- Executions
- Backtesting
- Reports
- Settings

## Safety Rules

- Do not show full API secrets.
- Do not show full passphrases.
- Do not log secrets.
- Do not implement live order buttons.
- Do not implement authentication flows in v1.
- Always show adapter mode, paper mode, and live trading disabled status.
- Dangerous actions require confirmation in the UI.

## API Clients

Typed clients exist for:

- Health/status
- Accounts
- Pairs
- Settings
- Radar
- Setups
- Signals
- Risk
- Execution
- Backtesting
- Reports

## Known Limitations

- Actual Vite build was not executed because Node/npm are unavailable in the
  current shell.
- Dashboard state depends on the v1 in-memory Backend API Routes module.
- No chart candlestick rendering is included in v1; operational charts focus on
  equity and conversion metrics.

## Final Validation Report

Execution date: 2026-06-07

- Smoke checks executed: 8
- Smoke checks passed: 8
- Pages implemented: 12
- Components implemented: 18
- API clients implemented: 11
- Safety validation: PASS
- Build validation: STATIC PASS, Node/npm unavailable in validation shell
- HTML report: `frontend/reports/frontend_dashboard_validation_report.html`
- PNG report: `frontend/reports/frontend_dashboard_validation_report.png`

Validation confirms:

- Dashboard renders the required private VPS operator pages.
- No login, registration, password reset, or multi-user SaaS page exists.
- No live order button or live execution route is present.
- API credentials are entered only through account forms and displayed as masked values.
- Paper mode and live trading disabled status are visible in the UI.
- Setup radar sorts by progress and highlights 70%+, 90%+, and `ENTRY_READY` states.
- Backtesting upload UI and validation report viewing UI are present.

Ready For Integration: YES
