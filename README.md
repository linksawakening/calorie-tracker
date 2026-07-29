# Caltrack

Agent-mediated calorie tracking with Garmin Connect integration. Syncs
calorie expenditure from Garmin, logs food intake via USDA/Open Food Facts,
and computes daily energy balance with macro targets.

## Architecture

```
Garmin Sync Service (FastAPI, Docker)
├── Holds Garmin credentials in .env (mode 0600)
├── Caches login tokens in a Docker volume
└── REST API on :8700 (API key auth)

Caltrack CLI (Python, local)
├── Calls the sync service via HTTP for expenditure data
├── Searches USDA / Open Food Facts for intake logging
├── Stores everything in SQLite
└── Computes TDEE, targets, and daily summaries
```

**Security model:** Garmin credentials live only in the sync service's
`.env` file. The CLI gets an API key that grants access to calorie data
only — never to the Garmin credentials themselves.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (or pip)
- Docker + Docker Compose (for the Garmin sync service)
- A [USDA FoodData Central API key](https://fdc.nal.usda.gov/api-key-signup) (free)
- A Garmin Connect account

### 1. Clone and install

```bash
git clone https://github.com/linksawakening/calorie-tracker.git
cd calorie-tracker
uv sync
```

Or with pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment variables

Create a `.env` file (gitignored — never committed):

```bash
# USDA food search (free): https://fdc.nal.usda.gov/api-key-signup
USDA_API_KEY=your-usda-api-key

# Garmin sync service connection
GARMIN_SYNC_URL=http://localhost:8700
GARMIN_SYNC_API_KEY=<shared-key-you-generate>

# Body weight for macro computation (optional, overrides Garmin scale data)
CALTRACK_BODY_WEIGHT_LBS=180.0
```

Generate a random API key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Deploy the Garmin sync service (Docker)

The pre-built image is published to GitHub Container Registry
automatically on every push to `main` and on version tags.

**Option A: Pre-built image (recommended)**

```bash
cd service
cp .env.example .env
# Edit .env with your Garmin email, password, and the API key from step 2
chmod 600 .env
docker compose up -d
```

The compose file pulls `ghcr.io/linksawakening/calorie-tracker-garmin-sync:latest`
by default. No build step needed.

**Option B: Build from source**

```bash
cd service
cp .env.example .env
# Edit .env with your Garmin email, password, and the API key from step 2
chmod 600 .env
docker compose up -d --build
```

To use the build-from-source option, uncomment the `build:` line and
comment out the `image:` line in `compose.yaml`.

**Option C: Manual docker run (no compose)**

```bash
cd service
docker build -t garmin-sync .
docker run -d \
  --name garmin-sync \
  --restart unless-stopped \
  -p 8700:8700 \
  -e GARMIN_EMAIL=your.email@example.com \
  -e GARMIN_PASSWORD=your-password \
  -e GARMIN_SYNC_API_KEY=your-api-key \
  -e GARMIN_DATA_TYPES=summary,sleep,activities \
  -v garmin-tokens:/root/.garminconnect \
  garmin-sync
```

**Verify the service is running:**

```bash
curl http://localhost:8700/health
# {"status":"ok"}
```

### 4. Test the CLI

```bash
# Check service connectivity
caltrack sync --check

# Pull today's calorie data from Garmin
caltrack sync

# Log a food item
caltrack log --name breakfast "2 eggs and toast"

# View today's status
caltrack status

# View 7-day summary
caltrack summary
```

## Garmin Data Types

The sync service exposes 14 data types from Garmin Connect, configurable
via the `GARMIN_DATA_TYPES` env var on the service. See
[`service/SETUP.md`](service/SETUP.md) for the full list and configuration.

The most useful for calorie tracking:
- **summary** — calories, steps, HR, stress, body battery
- **activities** — individual workouts with sport-specific calorie burns
- **body_composition** — weight, BMI, body fat %
- **sleep** — recovery quality (affects TDEE)
- **hrv** — recovery indicator

## CLI Commands

| Command | Description |
|---|---|
| `caltrack log` | Add a food intake entry (manual or USDA search) |
| `caltrack sync` | Pull expenditure data from the Garmin sync service |
| `caltrack status` | Show today's intake, expenditure, and balance |
| `caltrack targets` | Show computed daily calorie/macro targets |
| `caltrack summary` | Show N-day rolling summary (default 7) |
| `caltrack search <query>` | Search USDA for a food item |
| `caltrack barcode <code>` | Look up a product by barcode (Open Food Facts) |
| `caltrack add-by-id <id> <g>` | Add a food by USDA FDC ID and grams |
| `caltrack summarize` | Compute and store daily summary for a date |

## Project Structure

```
calorie-tracker/
├── src/caltrack/          # Main Python package
│   ├── cli.py             # Click CLI with all subcommands
│   ├── db.py              # SQLite schema and data layer
│   ├── garmin.py          # Garmin sync service client
│   ├── nutrition.py       # USDA + Open Food Facts lookup
│   ├── targets.py         # TDEE and macro target computation
│   └── reminder.py        # Food logging reminder script
├── service/               # Standalone Garmin sync service (Docker)
│   ├── src/garmin_sync/   # FastAPI app
│   ├── Dockerfile
│   ├── compose.yaml
│   └── SETUP.md           # Deployment instructions
├── tests/                 # 33 tests (db, nutrition, targets, garmin, reminder)
├── pyproject.toml
└── PLAN.md                # Research findings and design decisions
```

## Configuration

All configuration is via environment variables:

| Variable | Required | Description |
|---|---|---|
| `USDA_API_KEY` | For food search | [Get free key](https://fdc.nal.usda.gov/api-key-signup) |
| `GARMIN_SYNC_URL` | For Garmin sync | URL of the sync service (default: `http://localhost:8700`) |
| `GARMIN_SYNC_API_KEY` | For Garmin sync | Shared API key for the sync service |
| `CALTRACK_BODY_WEIGHT_LBS` | No | Fallback body weight for macros if no Garmin scale data (default: 180.0) |

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/ tests/
ruff format --check src/ tests/
```

## CI/CD

GitHub Actions workflows handle automated builds and releases:

- **CI** (`.github/workflows/ci.yml`) — runs ruff, mypy, and pytest on
  every PR and push to `main`
- **Docker Release** (`.github/workflows/docker-release.yml`) — builds the
  Docker image and pushes to `ghcr.io/linksawakening/calorie-tracker-garmin-sync`
  on every push to `main`. Tags: `latest`, `sha-<hash>`, and version tags
  from `pyproject.toml` on release. Also creates a GitHub Release with
  the image pull command when the version in `service/pyproject.toml` changes.

### Updating the release version

Bump the version in `service/pyproject.toml`:

```toml
version = "0.3.0"
```

Push to `main`. The workflow will:
1. Build and push the Docker image tagged with the new version
2. Create a GitHub Release `v0.3.0` with the image pull instructions

## License

Proprietary. All rights reserved.
