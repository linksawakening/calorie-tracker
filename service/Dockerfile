FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src/ src/

RUN uv pip install --system --no-cache .

EXPOSE 8700

CMD ["uvicorn", "garmin_sync.app:app", "--host", "0.0.0.0", "--port", "8700"]
