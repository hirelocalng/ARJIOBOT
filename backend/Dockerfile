FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV API_HOST=0.0.0.0
EXPOSE 8000

# Railway injects $PORT at runtime; fall back to 8000 for local `docker run`.
CMD ["sh", "-c", "API_PORT=${PORT:-8000} python -m arjiobot.api.dev_server"]
