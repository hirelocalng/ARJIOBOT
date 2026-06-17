# Mobile Control Deployment

The trading engine runs on the VPS/server. The phone is only a browser dashboard.

## Required Environment

Set these on the VPS before exposing the dashboard:

```powershell
$env:ARJIOBOT_DASHBOARD_PASSWORD = "use-a-long-private-password"
$env:ARJIOBOT_DASHBOARD_SECRET = "use-a-long-random-signing-secret"
```

When `ARJIOBOT_DASHBOARD_PASSWORD` is set, private `/api/*` routes require a dashboard login token. Public routes are limited to:

- `/api/health`
- `/api/auth/status`
- `/api/auth/login`

## HTTPS

Run the backend and frontend behind a TLS reverse proxy such as Nginx, Caddy, or a managed load balancer.

Recommended proxy behavior:

- Redirect HTTP to HTTPS.
- Terminate TLS with a valid certificate.
- Forward `/api/*` to the backend service.
- Serve the frontend static build from `frontend/dist`.
- Set secure proxy headers: `X-Forwarded-Proto`, `X-Forwarded-For`, `Host`.

## Mobile Controls

The phone dashboard exposes:

- Emergency stop: switches server trading mode to `OFF`.
- Demo/live/OFF mode controls.
- Frozen selected profile display.
- Risk and margin controls.
- Trade status and open position panels.
- Recent mode log panel.

The phone never runs strategy, execution, or exchange code.
