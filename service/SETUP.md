# Garmin Sync Service Setup

This service holds your Garmin credentials and exposes calorie data via a
REST API. The calorie-tracker CLI calls it with a shared API key.

## Architecture

```
Garmin Sync Service (Docker, port 8700)
├── .env          ← Garmin credentials + API key (mode 0600)
└── garmin_tokens ← Auto-cached login tokens (Docker volume)

Calorie Tracker (client)
├── .env          ← GARMIN_SYNC_API_KEY + GARMIN_SYNC_URL only
└── garmin.py     ← Calls http://<service-host>:8700/calories/{day}
```

## Deploy Steps

### 1. On the client host — generate an API key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Save this key. You'll put it in both the service `.env` and the
client `.env`.

### 2. On the service host — create the .env file

Create the service directory and copy the service files:

```bash
mkdir -p /opt/garmin-sync
cd /opt/garmin-sync
cp .env.example .env
chmod 600 .env
nano .env
```

Fill in:
```
GARMIN_EMAIL=your.garmin@email.com
GARMIN_PASSWORD=your-garmin-password
GARMIN_SYNC_API_KEY=<the key you generated in step 1>
```

### 3. On the service host — build and start the container

```bash
cd /opt/garmin-sync
docker compose up -d --build
```

### 4. Verify the service is running

```bash
curl http://localhost:8700/health
# Should return: {"status":"ok"}
```

### 5. On the client host — set the API key

Add to your `.env` file:

```bash
GARMIN_SYNC_API_KEY=<same key from step 1>
GARMIN_SYNC_URL=http://<service-host>:8700
```

### 6. Test the sync

```bash
cd ~/projects/calorie-tracker
caltrack sync --check    # should say ✅ reachable
caltrack sync            # should pull today's data from Garmin
```

## Security Model

| Component | Has Garmin credentials? | Has API key? |
|---|---|---|
| Calorie tracker client | ❌ No | ✅ Yes |
| Garmin sync service | ✅ Yes (in .env, mode 0600) | ✅ Yes |

The API key grants access to calorie **data** only — it cannot retrieve
Garmin credentials. The client can call the API but cannot read the
service's `.env` file.

## First Login (MFA)

The first time the service starts and you call `caltrack sync`, Garmin will
require MFA. This happens inside the container — you may need to:

1. Check container logs: `docker logs garmin-sync`
2. If MFA is stuck, exec into the container and run the login interactively:
   ```bash
   docker exec -it garmin-sync python -c "
   from garminconnect import Garmin
   import os
   g = Garmin(os.environ['GARMIN_EMAIL'], os.environ['GARMIN_PASSWORD'])
   g.login()
   "
   ```
3. Enter the MFA code when prompted. The token is cached to the Docker
   volume and auto-refreshed thereafter.

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| GET | `/calories/{day}` | X-API-Key | Daily calorie expenditure |
| GET | `/calories?start=&end=` | X-API-Key | Date range (max 30 days) |
| GET | `/weight/{day}` | X-API-Key | Body composition |
| POST | `/auth/refresh` | X-API-Key | Force re-authentication |
