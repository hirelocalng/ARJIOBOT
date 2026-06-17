# VPS Hosting Quickstart

## Recommended VPS

- 2 vCPU minimum
- 4 GB RAM minimum
- 40 GB SSD
- Windows Server or Linux VPS
- Stable outbound internet connection

## Install Python

Install Python 3.12+ and create a virtual environment:

```bat
python -m venv ..\.venv
..\.venv\Scripts\python.exe -m pip install pytest
```

## Install Node.js

Install Node.js LTS for the Vite dashboard.

## Backend Dependencies

The current validation shell uses a FastAPI-compatible shim because external
dependency installation was unavailable. For production, install real FastAPI
and an ASGI server:

```bat
..\.venv\Scripts\python.exe -m pip install fastapi uvicorn python-multipart
```

## Frontend Dependencies

```bat
cd frontend
npm install
```

## Environment

Copy `.env.example` to `.env`.

Keep:

```text
ADAPTER_MODE=MOCK
LIVE_TRADING_ENABLED=false
```

## Run Manually

Backend:

```bat
scripts\run_backend.bat
```

Frontend:

```bat
scripts\run_frontend.bat
```

## Build Frontend

```bat
cd frontend
npm run build
```

## PM2 Or Systemd

On Linux, run backend and frontend as managed services with PM2 or systemd.
On Windows VPS, use Task Scheduler or NSSM.

## Reverse Proxy

Use Nginx/Caddy/IIS as a reverse proxy:

- `/api` to backend on `127.0.0.1:8000`
- `/` to the Vite/production frontend

## Firewall

Expose only required ports. Keep backend private behind the reverse proxy.

## Domain And SSL

Use a domain and TLS certificate before public exposure.

## Production Warnings

- Use encrypted database storage.
- Do not store raw secrets in JSON.
- Enable authentication before public exposure.
- Keep live trading disabled until paper mode and CSV backtests are validated.
