# Garmin Connect Log

MCP server that fetches Garmin Connect health data (daily summaries and activities) for ME/CFS PEM threshold research.

## Features

- Daily health summaries: resting HR, max HR, HRV, body battery min/max, steps, sleep duration, sleep score, and activity count
- Stress and body battery flow per day: average/max stress, rest/low/medium/high stress percentages (of the full day, including activity time), body battery charged/drained and body battery at wake time
  - Cached summaries from before these fields existed are refetched automatically
- Activity details: type, duration, distance, time in heart-rate zones, and body-battery impact
- MCP tools for AI clients over stdio
- Date-range JSON caching keyed by start and end date
- HR zone label support for Garmin and Olympiatoppen schemes

## Quick start with uvx (no local clone)

Requires [uv](https://docs.astral.sh/uv/) and a Garmin Connect account. uvx fetches Python 3.14 and dependencies automatically.

1. Authenticate with Garmin (stores the session token in your OS keychain):

```bash
uvx --from git+https://github.com/stian-overasen/connectlog connectlog-setup
```

2. Add the server to your MCP client.

Claude Code:

```bash
claude mcp add connectlog -- uvx --from git+https://github.com/stian-overasen/connectlog connectlog
```

Claude Desktop (`claude_desktop_config.json`) or any client using the `mcpServers` format:

```json
{
  "mcpServers": {
    "connectlog": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/stian-overasen/connectlog",
        "connectlog"
      ]
    }
  }
}
```

Optionally add a [config file](#configuration).

To pick up the latest version, run `uvx --refresh --from git+https://github.com/stian-overasen/connectlog connectlog` once, or add `--refresh` to the args. Pin a version with `git+https://github.com/stian-overasen/connectlog@<tag-or-commit>`.

## Local development setup

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

This stores your Garmin session token in your OS keychain.

### Running

Start the MCP server:

```bash
uv run app.py
```

The process runs as an MCP server over stdio. The repository's [.mcp.json](.mcp.json) runs it this way for Claude Code.

## Configuration

Optional configuration is read from `~/.connectlog.json` (see [connectlog.example.json](connectlog.example.json)). If the file is missing, defaults are used.

- `hr_profiles`: date-based HR profile overrides (device, max HR and zone scheme `garmin` or `olympiatoppen`). Without it, default Garmin zones are used.

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
├── credentials.py
├── setup_oauth.py
├── pyproject.toml
├── connectlog.example.json
├── bin/
│   ├── format.sh
│   └── lint.sh
└── README.md
```

## Troubleshooting

- GARMIN session token not found in OS keychain: run `uvx --from git+https://github.com/stian-overasen/connectlog connectlog-setup` (or `uv run setup_oauth.py` from a clone)
- Authentication expired: re-run the setup command above
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
