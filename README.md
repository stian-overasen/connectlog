# Garmin Connect Log

MCP server that fetches Garmin Connect health data (daily summaries and activities) for ME/CFS PEM threshold research.

## Features

- Daily health summaries: resting HR, max HR, HRV, body battery min/max, steps, sleep duration, sleep score, and activity count
- Activity details: type, duration, distance, time in heart-rate zones, and body-battery impact
- MCP tools for AI clients over stdio
- Date-range JSON caching keyed by start and end date
- HR zone label support for Garmin and Olympiatoppen schemes

## Setup

### Prerequisites

- Python 3.14+
- uv package manager
- Garmin Connect account

### Installation

1. Clone the repository.

```bash
git clone https://github.com/stian-overasen/connectlog.git
cd connectlog
```

2. Install dependencies.

```bash
uv sync
```

3. Set up Garmin authentication.

```bash
uv run setup_oauth.py
```

This stores your Garmin session token in your OS keychain (not in `.env`).

4. Optional: configure date-based HR profile overrides using [hr_profiles.example.json](hr_profiles.example.json) and set HR_PROFILE_OVERRIDES_PATH in .env.

## Running

Start the MCP server:

```bash
uv run app.py
```

The process runs as an MCP server over stdio.

## MCP Tools

The server exposes:

- fetch_daily_summary(date)
  - Input: date in YYYY-MM-DD
  - Output: one day summary
- fetch_daily_summaries(start_date, end_date)
  - Input: start_date and end_date in YYYY-MM-DD
  - Output: summaries array for the date range, including numberOfActivities
- fetch_activities(start_date, end_date)
  - Input: start_date and end_date in YYYY-MM-DD
  - Output: activities array and hr_zone_percentages

## Caching

Cached files are written to an OS-specific per-user cache directory and include both range boundaries:

- macOS: ~/Library/Caches/connectlog
- Linux: $XDG_CACHE_HOME/connectlog or ~/.cache/connectlog
- Windows: %LOCALAPPDATA%\\connectlog\\cache

Cache files:

- summary-YYYY-MM-DD-to-YYYY-MM-DD.json
- activities-YYYY-MM-DD-to-YYYY-MM-DD.json

To force refetch, delete matching files in your OS cache directory.

Examples:

```bash
rm ~/Library/Caches/connectlog/*.json
```

```bash
rm ~/.cache/connectlog/*.json
```

## Data Fields

Daily summary fields:

- date
- totalSteps
- hrvLastNightAvg
- restingHeartRate
- maxHeartRate
- bodyBatteryMax
- bodyBatteryMin
- sleepDuration
- sleepScore
- numberOfActivities

Activity fields:

- datetime
- activity_type
- duration
- distance
- hr_zones
- device
- device_max_hr
- body_battery_impact

## Project Structure

```text
connectlog/
├── app.py
├── setup_oauth.py
├── pyproject.toml
├── hr_profiles.example.json
├── .env.example
├── bin/
│   ├── format.sh
│   └── lint.sh
└── README.md
```

## Troubleshooting

- GARMIN session token not found in OS keychain: run uv run setup_oauth.py
- Authentication expired: re-run uv run setup_oauth.py
- No data returned: verify Garmin credentials and available data for the requested date range

To remove a stored token on macOS:

```bash
security delete-generic-password -s connectlog -a garmin_session
```

## Development

- Format: ./bin/format.sh
- Lint: ./bin/lint.sh

## License

MIT License.
