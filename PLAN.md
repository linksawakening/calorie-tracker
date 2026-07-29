# Calorie Tracker — Research & Implementation Plan

Created: 2026-07-28
Status: Planning — awaiting user stats for TDEE estimate

---

## 1. Problem Statement

Build an agent-mediated calorie tracking system that:
- Syncs calorie **expenditure** from Garmin Connect automatically
- Accepts **intake** logging via Telegram messages (text-based food entry)
- Computes daily energy balance (intake vs. expenditure)
- Surfaces trends and alerts via Telegram
- Stores all data locally (SQLite, self-hosted)

## 2. Garmin Integration

### Path: python-garminconnect (unofficial, pull-based)

**Why not the official Health API?**
- Requires partner program application (days-weeks approval)
- OAuth 1.0a with signed requests (complex)
- Push-based delivery (needs public HTTPS callback endpoints)
- Designed for companies building products for other users

**python-garminconnect advantages:**
- Pull-based (call methods whenever you want, no webhook infra)
- Token-based auth with auto-refresh (login once with MFA, then hands-off)
- 142+ API methods across 13 categories
- Tokens stored at `~/.garminconnect/garmin_tokens.json` (mode 0600)

**Key data available:**
- Daily: active calories, BMR calories, steps, floors, intensity minutes
- Health: resting HR, sleep stages, stress, Body Battery, HRV, SpO2
- Body composition (if Garmin Index scale): weight, BMI, body fat %, muscle mass, bone mass, body water
- Activities: 100+ sport types with detailed metrics

**Install:**
```
pip install --upgrade garminconnect curl_cffi
```

**Pitfalls:**
- Scrapes undocumented internal endpoints — Garmin can break it without notice
- Handle re-login gracefully (refresh token expiry)
- Keep auth path simple, don't depend on obscure methods

### Garmin Data = Measured TDEE

Garmin provides active_calories + BMR_calories directly. No need for Mifflin-St Jeor + activity multiplier estimation. This is the actual measured expenditure for the day.

## 3. Nutrition Databases (Intake Side)

| Database | Cost | Rate Limit | Strength | Weakness |
|---|---|---|---|---|
| USDA FoodData Central | Free | 1,000/hr per IP | Authoritative US reference, public domain | US-centric, no barcode scanning |
| Open Food Facts | Free | 10/min per IP | Barcode lookup, 3M+ products, self-hostable | Crowdsourced quality varies, low rate limit |
| FatSecret | Free tier | 5,000/day | Largest verified global database | Commercial, requires API key |
| Edamam | $14/mo | 100k/mo | Natural-language ingredient parser | Paid, caching restrictions |
| Nutritionix | Quote-based | Unpublished | NLP food logging (powers MyFitnessPal) | Opaque pricing |

**Recommendation:** USDA FoodData Central (primary, free, authoritative) + Open Food Facts (barcode lookup for packaged foods). Both free, both self-hostable.

- USDA API key: https://fdc.nal.usda.gov/api-key-signup
- USDA API docs: https://fdc.nal.usda.gov/api-guide

## 4. Food Logging Approach

**Text-based logging via Telegram** (best fit for chat agent):
- User messages: "chicken breast 200g, rice 1 cup"
- Agent resolves against USDA/OFF API
- Logs macros to SQLite
- Returns running daily total

**Alternatives considered:**
- Photo-based estimation: 60-70% accuracy at best, needs vision model
- Barcode scanning: OFF handles this, best for packaged foods
- Manual calorie entry: fastest, lowest accuracy

## 5. Proposed Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│ Garmin Watch│────▶│ python-          │────▶│  Local DB    │
│ (your wrist)│     │ garminconnect    │     │  (SQLite)    │
└─────────────┘     │ (cron: daily)    │     │              │
                    └──────────────────┘     │  calories    │
┌─────────────┐     ┌──────────────────┐     │  intake      │
│ You (Telegram)│──▶│ USDA / Open Food  │────▶│  expenditure │
│ "2 eggs, toast"│  │ Facts API lookup  │     │  weight      │
└─────────────┘     └──────────────────┘     │  trends      │
                                             └──────────────┘
                                                    │
                                            ┌───────┴───────┐
                                            │ Daily summary │
                                            │ via Telegram  │
                                            └───────────────┘
```

## 6. Data Model (SQLite)

### expenditure (from Garmin, daily sync)
```sql
CREATE TABLE expenditure (
    date TEXT PRIMARY KEY,
    active_calories INTEGER,
    bmr_calories INTEGER,
    total_calories INTEGER,  -- active + bmr
    steps INTEGER,
    floors INTEGER,
    intensity_minutes INTEGER,
    resting_hr INTEGER,
    sleep_hours REAL,
    stress_avg INTEGER,
    body_battery_max INTEGER
);
```

### intake (from food logging)
```sql
CREATE TABLE intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    meal_name TEXT,
    food_description TEXT,
    calories INTEGER,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    fiber_g REAL,
    source TEXT,  -- 'usda' | 'off' | 'manual'
    source_id TEXT,  -- FDC ID or OFF barcode
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### body_composition (from Garmin scale, if applicable)
```sql
CREATE TABLE body_composition (
    date TEXT PRIMARY KEY,
    weight_kg REAL,
    body_fat_pct REAL,
    muscle_mass_kg REAL,
    bone_mass_kg REAL,
    bmi REAL,
    body_water_pct REAL
);
```

### daily_summary (computed)
```sql
CREATE TABLE daily_summary (
    date TEXT PRIMARY KEY,
    total_intake INTEGER,
    total_expenditure INTEGER,
    energy_balance INTEGER,  -- intake - expenditure
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    weight_kg REAL,  -- from body_composition if available
    rolling_weight_kg REAL  -- 7-day average
);
```

## 7. Implementation Components

| Component | How | Complexity |
|---|---|---|
| Garmin sync | `python-garminconnect` cron job, daily pull | Low |
| Food logging | Telegram message → USDA/OFF API → SQLite | Medium |
| Daily summary | Cron at end of day: "You ate X, burned Y, deficit Z" | Low |
| Trend tracking | 7-day/30-day rolling averages, weight trend | Medium |
| Goal tracking | Target deficit/surplus, projected weight change | Low |
| Anomaly alerts | "You're 800 cal over your average today" | Low |

## 8. Pitfalls

- **python-garminconnect fragility**: Garmin can change internal endpoints. Handle re-login gracefully.
- **Portion estimation**: Weakest link. Text logging ±20%. Kitchen scale is the only real fix.
- **BMR accuracy**: Garmin's BMR is an estimate based on profile data. Track trends, not absolute values.
- **Calories aren't equal**: 2000 cal junk vs whole foods = different satiety/TEF/hormonal impact. Track macros but don't pretend calories are the whole picture.
- **Daily weight noise**: Body water causes ±1-2 kg day-to-day. Use 7-day rolling average for trend decisions.

## 9. Existing Self-Hosted Options (reference)

- **nutritrace** — Node.js, SQLite, Open Food Facts mirror (2026)
- **OpenNutriTracker** — Cross-platform, multi-source food DB, Supabase backend
- **calorific** — Dead simple, just calorie counts, no macros

None integrate with Garmin. A purpose-built tool is cleaner for a Telegram-native agent.

## 10. TDEE Estimation (pending user stats)

Awaiting from Ryan:
- Age
- Sex
- Height
- Weight
- Activity level / typical training
- Goal (cut / maintain / bulk)
- Target rate (e.g., -500 cal/day for ~1 lb/week loss)

Once Garmin is connected, we replace the estimated TDEE with measured expenditure. But we need a starting estimate for initial targets.

### TDEE Formula (Mifflin-St Jeor, most validated)

**Men:** BMR = 10 × weight(kg) + 6.25 × height(cm) − 5 × age + 5
**Women:** BMR = 10 × weight(kg) + 6.25 × height(cm) − 5 × age − 161

TDEE = BMR × activity multiplier:
- Sedentary: 1.2
- Lightly active: 1.375
- Moderately active: 1.55
- Very active: 1.725
- Extra active: 1.9

Once Garmin data flows, we replace this estimate with actual measured values.
