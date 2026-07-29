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
git clone <repo-url>
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

# Body weight for macro computation (optional, default 189.3)
CALTRACK_BODY_WEIGHT_LBS=189.3
```

Generate a random API key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Deploy the Garmin sync service

See [`service/SETUP.md`](service/SETUP.md) for full deployment instructions.
Quick version:

```bash
cd service
cp .env.example .env
# Edit .env with your Garmin email, password, and the API key from step 2
chmod 600 .env
docker compose up -d --build
```

Verify the service is running:

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
| `CALTRACK_BODY_WEIGHT_LBS` | No | Body weight for macro targets (default: 189.3) |

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

## License

Proprietary. All rights reserved.
