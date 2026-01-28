# Garmin Connect Log

**TL;DR**: Flask API that fetches Garmin Connect health data (daily summaries and activities) to analyze ME/CFS PEM (Post-Exertional Malaise) thresholds. Returns comprehensive JSON with heart rate zones, body battery trends, sleep metrics, and activity details for research purposes.

## Features

- **Daily Health Summaries**: Resting HR, max HR, HRV, hourly body battery values, steps, sleep duration, and sleep scores
- **Activity Details**: Type, duration, distance, time in each heart rate zone, and body battery impact
- **Smart Caching**: SQLite database stores fetched data (delete `cache/data.db` to refresh)
- **Configurable Date Range**: Query parameter for months (default: 3)
- **ME/CFS Research Focus**: All HR zones and body battery data for PEM threshold analysis

## Setup

### Prerequisites

- Python 3.14+
- [uv package manager](https://github.com/astral-sh/uv)
- Garmin Connect account

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/stian-overasen/connectlog.git
   cd connectlog
   ```

2. **Install dependencies with uv**

   ```bash
   uv sync
   ```

   This creates a virtual environment and installs all dependencies from [pyproject.toml](pyproject.toml).

3. **Set up Garmin Connect authentication**

   ```bash
   uv run setup_oauth.py
   ```

   Enter your Garmin Connect email and password when prompted. This generates a session token saved to `.env` (valid for ~1 year).

## Usage

### Start the Flask API

```bash
uv run app.py
```

The API runs on `http://127.0.0.1:5000`

On first run, the API will fetch data from Garmin Connect with progress indicators. Subsequent runs use cached data from the SQLite database.

### Fetch Data

**Get last 3 months (default)**

```bash
curl http://127.0.0.1:5000/api/summary
```

**Get last 6 months**

```bash
curl http://127.0.0.1:5000/api/summary?months=6
```

**Refresh data**

```bash
rm cache/data.db
curl http://127.0.0.1:5000/api/summary
```

## Example JSON Response

```json
{
  "start_date": "2025-10-26",
  "end_date": "2026-01-26",
  "daily_summaries": [
    {
      "date": "2025-10-26",
      "resting_hr": 55,
      "max_hr": 160,
      "hrv_overnight_avg": 45,
      "body_battery_hourly": [
        { "hour": 0, "value": 85 },
        { "hour": 1, "value": 88 },
        { "hour": 2, "value": 92 },
        { "hour": 6, "value": 100 },
        { "hour": 12, "value": 75 },
        { "hour": 18, "value": 45 },
        { "hour": 23, "value": 34 }
      ],
      "steps": 8500,
      "sleep_duration": 26400,
      "sleep_score": 77
    }
  ],
  "activities": [
    {
      "activity_id": 123456789,
      "date": "2025-10-26",
      "activity_type": "running",
      "duration": 3600,
      "distance": 10000.0,
      "hr_zones": [
        { "zone": 1, "time_seconds": 300 },
        { "zone": 2, "time_seconds": 1200 },
        { "zone": 3, "time_seconds": 1500 },
        { "zone": 4, "time_seconds": 600 },
        { "zone": 5, "time_seconds": 0 }
      ],
      "bb_impact": -28
    }
  ]
}
```

## Data Fields

### Daily Summaries

- `date`: Date in YYYY-MM-DD format
- `resting_hr`: Average resting heart rate (bpm)
- `max_hr`: Maximum heart rate during the day (bpm)
- `hrv`: Heart rate variability (ms)
- `body_battery_hourly`: Array of hourly body battery values (0-100)
- `steps`: Total steps for the day
- `sleep_duration`: Sleep duration in seconds
- `sleep_score`: Garmin sleep score (0-100)

### Activities

- `activity_id`: Unique Garmin activity identifier
- `date`: Activity date in YYYY-MM-DD format
- `activity_type`: Type of activity (running, cycling, walking, etc.)
- `duration`: Activity duration in seconds
- `distance`: Distance in meters
- `hr_zones`: Array of time spent in each heart rate zone (seconds)
  - Zone 1: Warm-up / Recovery
  - Zone 2: Easy / Fat burn
  - Zone 3: Aerobic / Endurance
  - Zone 4: Threshold / Performance
  - Zone 5: Maximum / Speed
- `bb_impact`: Body battery net impact (negative = drain, positive = gain)

## PEM Threshold Research

This API provides comprehensive data for analyzing Post-Exertional Malaise (PEM) thresholds in ME/CFS patients:

- **Heart Rate Zones**: Detailed time distribution helps identify exertion levels that trigger PEM
- **Body Battery Trends**: Hourly tracking reveals recovery patterns and crash indicators
- **Multi-day Correlation**: Compare activity intensity with subsequent days' resting HR and HRV changes
- **Sleep Impact**: Analyze how exertion affects sleep quality and duration

### Research Tips

1. **Identify Baseline**: Look at resting HR, HRV, and body battery on rest days
2. **Track Exertion**: Monitor HR zone distribution during activities
3. **Measure Recovery**: Compare body battery depletion vs. overnight recovery
4. **Find Thresholds**: Correlate activity metrics with next-day symptom severity
5. **Temporal Analysis**: Track multi-day trends after crossing suspected thresholds

## Project Structure

```# Flask API with data fetchers and endpoints
├── setup_oauth.py                  # OAuth authentication script
├── pyproject.toml                  # uv project configuration and dependencies
├── .env.example                    # Environment variable template
├── .env                            # OAuth session token (generated, gitignored)
├── .gitignore                      # Excludes .env and cache/
├── .github/
│   └── copilot-instructions.md     # GitHub Copilot project context
├── cache/
│   └── data.db                     # SQLite database (auto-generated)
└── README.md                       # This file
```

## Dependencies

Managed via [pyproject.toml](pyproject.toml) and uv package manager:

- **flask** - Web framework
- **garminconnect** - Garmin Connect API client
- **python-dotenv** - Environment variable management
- **tqdm** - Progress bars for data fetching

To add dependencies, edit `dependencies` array in [pyproject.toml](pyproject.toml) and run `uv sync`. └── data.db # SQLite database (auto-generated)
└── README.md # This file

```

## Troubleshooting

**"GARMIN_SESSION not found" error**
- Run `uv run setup_oauth.py` to generate authentication token

**No data returned**
- Check Garmin Connect credentials
- Ensure you have data in the requested date range
- Check console output for API errors (some data may be missing)

**Old data showing**
- Delete `cache/data.db` to force refresh from Garmin

**Authentication expired**
- OAuth tokens expire after ~1 year
- Run `uv run setup_oauth.py` again to regenerate

## License

MIT License - See repository for details

## Contributing

This is a research tool for personal use. Issues and pull requests welcome for bug fixes and data accuracy improvements.
```
