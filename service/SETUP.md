# Garmin Sync Service Setup

This service holds your Garmin credentials and exposes health data via a
REST API. The calorie-tracker CLI calls it with a shared API key.

## Architecture

```
Garmin Sync Service (Docker, port 8700)
├── .env          ← Garmin credentials + API key (mode 0600)
└── garmin_tokens ← Auto-cached login tokens (Docker volume)

Calorie Tracker (client)
├── .env          ← GARMIN_SYNC_API_KEY + GARMIN_SYNC_URL only
└── garmin.py     ← Calls http://<service-host>:8700/...
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

# Optional: restrict which data types are exposed (default: all)
# Comma-separated. See "Data Types" below for available values.
GARMIN_DATA_TYPES=summary,sleep,activities,hrv
```

### 3. On the service host — start the container

**Using the pre-built image (recommended):**

```bash
cd /opt/garmin-sync
docker compose up -d
```

The compose file pulls `ghcr.io/linksawakening/calorie-tracker-garmin-sync:latest`
automatically.

**Building from source:**

```bash
cd /opt/garmin-sync
docker compose up -d --build
```

### 4. Verify the service is running

```bash
curl http://localhost:8700/health
# {"status":"ok"}
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

The API key grants access to health **data** only — it cannot retrieve
Garmin credentials. The client can call the API but cannot read the
service's `.env` file.

## Data Types

The service exposes 14 data types from Garmin Connect. Control which are
available via the `GARMIN_DATA_TYPES` env var (comma-separated, default: all).

| Type | Description |
|---|---|
| `summary` | Calories, steps, HR, stress, body battery (daily overview) |
| `body_composition` | Weight, BMI, body fat %, muscle mass |
| `sleep` | Sleep stages, duration, score |
| `activities` | Individual workouts with sport-specific calories |
| `hrv` | Heart Rate Variability |
| `training_readiness` | Training readiness score and factors |
| `stress` | Stress levels throughout the day |
| `heart_rates` | HR zones and time-in-zone |
| `respiration` | Respiration rate |
| `spo2` | Blood oxygen saturation |
| `hydration` | Water intake |
| `body_battery` | Energy levels (charged/drained) |
| `max_metrics` | VO2 max and other max metrics |
| `training_status` | Training status (productive, recovery, etc.) |

### Examples

Enable only calorie + sleep + activities:
```
GARMIN_DATA_TYPES=summary,sleep,activities
```

Enable everything (default):
```
# Omit the variable entirely, or:
GARMIN_DATA_TYPES=summary,body_composition,sleep,activities,hrv,training_readiness,stress,heart_rates,respiration,spo2,hydration,body_battery,max_metrics,training_status
```

### Discovering enabled types at runtime

```bash
curl -H "X-API-Key: <your-key>" http://localhost:8700/config
```

Returns all available types and which are currently enabled.

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

### Core

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| GET | `/config` | X-API-Key | Available and enabled data types |
| GET | `/day/{day}` | X-API-Key | All enabled data types for a date (single call) |

### Data Type Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/data/{type}/{day}` | X-API-Key | Single data type for a date |
| GET | `/data/summary/{day}` | X-API-Key | Calories, steps, HR, stress, body battery |
| GET | `/data/sleep/{day}` | X-API-Key | Sleep stages and score |
| GET | `/data/activities/{day}` | X-API-Key | Workouts with sport-specific calories |
| GET | `/data/hrv/{day}` | X-API-Key | Heart Rate Variability |
| GET | `/data/body_composition/{day}` | X-API-Key | Weight, BMI, body fat % |

(All 14 types follow the same `/data/{type}/{day}` pattern.)

### Legacy Endpoints (backward-compatible)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/calories/{day}` | X-API-Key | Daily calorie expenditure (uses summary type) |
| GET | `/calories?start=&end=` | X-API-Key | Date range (max 30 days) |
| GET | `/weight/{day}` | X-API-Key | Body composition |
| POST | `/auth/refresh` | X-API-Key | Force re-authentication |
