# Garmin Connect Log

**TL;DR**: Flask API that fetches Garmin Connect health data (daily summaries and activities) to analyze ME/CFS PEM (Post-Exertional Malaise) thresholds. Returns comprehensive JSON with heart rate zones, body battery min/max, sleep metrics, and activity details for research purposes.

## Features

- **Daily Health Summaries**: Resting HR, max HR, HRV, body battery min/max, steps, sleep duration, sleep scores, and activity count per day
- **Activity Details**: Type, duration, distance, time in each heart rate zone, and body battery impact
- **MCP Support**: Exposes Garmin fetch functions as MCP tools for AI clients
- **Smart Caching**: JSON files cache fetched data (delete cache files to refresh)
- **Configurable Date Range**: Query parameter for weeks (default: 1)
- **ME/CFS Research Focus**: All HR zones and daily body battery min/max for PEM threshold analysis

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

4. **(Optional) Configure HR zone context overrides**

Create a JSON file with date-based device settings and point to it in `.env` via `HR_PROFILE_OVERRIDES_PATH`. If the file is missing, the API defaults to Garmin zones. See [hr_profiles.example.json](hr_profiles.example.json).

## Usage

### Start the Flask API

```bash
uv run app.py
```

The API runs on `http://127.0.0.1:5000`

### Start the MCP Server

```bash
uv run app.py --mcp
```

This starts an MCP server over stdio with tools:

- `fetch_daily_summary(date)`
- `fetch_activities(start_date, end_date)`

On first run, the API will fetch data from Garmin Connect with progress indicators. Subsequent runs use cached JSON files.

### Fetch Data

**Get last week (default)**

```bash
curl http://127.0.0.1:5000/api/summary
```

**Get last 6 weeks**

```bash
curl http://127.0.0.1:5000/api/summary?weeks=6
```

**Refresh data**

```bash
rm cache/*.json
curl http://127.0.0.1:5000/api/summary
```

## API Endpoints

### `/api/summary`

Returns daily health summaries for the specified time period.

**Parameters:**

- `weeks` (optional, default: 1) - Number of weeks to fetch

**Response:** See [Example JSON Response](#example-json-response) below.

### `/api/activities`

Returns detailed activity data for the specified time period.

**Parameters:**

- `weeks` (optional, default: 1) - Number of weeks to fetch

## MCP Tools

When running with `uv run app.py --mcp`, the server exposes:

- `fetch_daily_summary(date)`
  - Input: `date` in `YYYY-MM-DD`
  - Output: Same daily summary object used by `/api/summary`
- `fetch_activities(start_date, end_date)`
  - Input: `start_date` and `end_date` in `YYYY-MM-DD`
  - Output: Activities payload with formatted durations/distances and `hr_zone_percentages`

## Example JSON Response

```json
{
  "summaries": [
    {
      "date": "2025-10-26",
      "totalSteps": 8500,
      "hrvLastNightAvg": 45,
      "restingHeartRate": 55,
      "maxHeartRate": 160,
      "bodyBatteryMax": 100,
      "bodyBatteryMin": 34,
      "sleepDuration": "7h 20m",
      "sleepScore": 77,
      "numberOfActivities": 2
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
        { "Zone 1 (Garmin)": 1, "time_seconds": 300 },
        { "Zone 2 (Garmin)": 2, "time_seconds": 1200 },
        { "Zone 3 (Garmin)": 3, "time_seconds": 1500 },
        { "Zone 4 (Garmin)": 4, "time_seconds": 600 },
        { "Zone 5 (Garmin)": 5, "time_seconds": 0 }
      ],
      "device": "Fenix 7S",
      "device_max_hr": 184,
      "body_battery_impact": -28
    }
  ]
}
```

## Data Fields

### Daily Summaries

- `date`: Date in YYYY-MM-DD format
- `totalSteps`: Total steps for the day
- `hrvLastNightAvg`: Overnight average heart rate variability (ms)
- `restingHeartRate`: Average resting heart rate (bpm)
- `maxHeartRate`: Maximum heart rate during the day (bpm)
- `bodyBatteryMax`: Maximum body battery level (0-100)
- `bodyBatteryMin`: Minimum body battery level (0-100)
- `sleepDuration`: Sleep duration (formatted as "Xh XXm")
- `sleepScore`: Garmin sleep score (0-100)
- `numberOfActivities`: Number of activities recorded on this date

### Activities

- `activity_id`: Unique Garmin activity identifier
- `date`: Activity date in YYYY-MM-DD format
- `activity_type`: Type of activity (running, cycling, walking, etc.)
- `duration`: Activity duration in seconds
- `distance`: Distance in meters
- `hr_zones`: Array of time spent in each heart rate zone with scheme-specific labels
  - Zone label format: `Zone 1 (Garmin)` or `I-1 (Olympiatoppen)`
  - Each zone includes the zone number and time in seconds
- `device`: Device name (e.g., "Fenix 7S")
- `device_max_hr`: Max heart rate configured on device at time of activity (bpm)
- `body_battery_impact`: Body battery net impact (negative = drain, positive = gain)

### HR Zone Percentages

Top-level context providing zone definitions for both schemes:

- `hr_zone_percentages`: Object containing zone definitions for `garmin` and `olympiatoppen` schemes
  - Each scheme includes zone labels with `min_percent` and `max_percent` of max HR

### HR Zone Schemes

**Garmin Zones:**

- Zone 5: 90-100% of max HR (Maximum / Speed)
- Zone 4: 80-89% of max HR (Threshold / Performance)
- Zone 3: 70-79% of max HR (Aerobic / Endurance)
- Zone 2: 60-69% of max HR (Easy / Fat burn)
- Zone 1: 50-59% of max HR (Warm-up / Recovery)

**Olympiatoppen Zones:**

- I-5: 92-100% of max HR
- I-4: 87-91% of max HR
- I-3: 82-86% of max HR
- I-2: 72-81% of max HR
- I-1: 55-71% of max HR

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
