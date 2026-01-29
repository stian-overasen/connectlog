# GitHub Copilot Instructions for Garmin Connect Log

## Project Overview

This is a Flask API that fetches Garmin Connect health data for ME/CFS (Myalgic Encephalomyelitis/Chronic Fatigue Syndrome) PEM (Post-Exertional Malaise) threshold research. The app retrieves daily health summaries and activity details to help identify safe exertion levels.

## Technology Stack

- **Language**: Python 3.14+
- **Package Manager**: uv (NOT pip)
- **Web Framework**: Flask
- **API Client**: garminconnect library
- **Database**: SQLite (local caching)
- **Configuration**: python-dotenv for environment variables

## Code Style & Standards

### Python Standards

- Line length: 160 characters (configured in pyproject.toml)
- Follow ruff linting rules (E, W, F, I, B, C4, UP)
- Use type hints where appropriate
- Write docstrings for all functions
- Use f-strings for string formatting

### Formatting

- Auto-formatted with ruff
- Import sorting with isort (via ruff)
- Run `uv run ruff format .` before commits
- **IMPORTANT**: Always run `./bin/format.sh` and `./bin/lint.sh` after making code changes to verify correctness

### Commands

- **Install dependencies**: `uv sync` (NOT `pip install`)
- **Run scripts**: `uv run <script.py>` (NOT `python <script.py>`)
- **Add dependencies**: Edit `pyproject.toml` dependencies array, then `uv sync`

## Project Structure

```
connectlog/
├── app.py              # Main Flask API with data fetchers and endpoints
├── setup_oauth.py      # OAuth authentication script
├── pyproject.toml      # uv project configuration
├── .env.example        # Environment variable template
├── .env                # OAuth session token (gitignored)
├── bin/
│   ├── format.sh       # Code formatting script
│   └── lint.sh         # Linting script
├── cache/
│   ├── summary-last-X-months.json    # Cached daily summaries (JSON)
│   └── activities-last-X-months.json # Cached activities (JSON)
└── README.md           # Documentation
```

## Key Implementation Details

### Authentication

- Uses Garmin Connect OAuth via `garminconnect` library
- Session token stored in `.env` file (valid ~1 year)
- Run `uv run setup_oauth.py` to generate token
- Never commit `.env` file

### Cache Storage

Data is cached in JSON files (not SQLite database) for easy sharing:

**summary-last-X-months.json:**

- date, resting_hr, max_hr, hrv_overnight_avg
- body_battery_min, body_battery_max
- steps, sleep_duration, sleep_score

**activities-last-X-months.json:**

- datetime, activity_type, duration, distance
- hr_zones (JSON array of time per zone)
- bb_impact (body battery impact)

### Data Fetching Strategy

- Configurable date range via `?months=3` parameter
- Check JSON cache for existing data before API calls
- If cache exists, return immediately (no incremental updates)
- If no cache, fetch all data from Garmin and save to JSON
- Use tqdm progress bars for batch operations
- Skip individual dates/activities on errors (partial data OK)

### Garmin API Endpoints Used

- `client.get_stats(date)` - Daily resting/max HR, steps
- `client.get_hrv_data(date)` - Heart rate variability
- `client.get_body_battery(start, end)` - Hourly body battery values
- `client.get_sleep_data(date)` - Sleep duration and scores
- `client.get_activities_by_date(start, end)` - Activity list
- `client.get_activity(id)` - Detailed activity with HR zones

### Error Handling

- Wrap all API calls in try-except blocks
- Skip individual failures, continue processing
- Return partial data when some requests fail
- Log errors to console for debugging

## ME/CFS PEM Research Context

This tool helps patients identify safe exertion thresholds by analyzing:

1. **Heart Rate Zones**: Time spent in each zone indicates exertion level
2. **Body Battery**: Hourly tracking shows energy depletion and recovery
3. **Recovery Metrics**: Next-day resting HR and HRV changes indicate PEM
4. **Sleep Impact**: How activity affects sleep quality and duration

**Critical**: All HR zone details and body battery data must be preserved for threshold analysis.

## Common Tasks

### Adding a New Dependency

```bash
# Edit pyproject.toml dependencies array
"new-package>=1.0.0",

# Sync dependencies
uv sync
```

### Adding a New API Endpoint

```python
@app.route("/api/new-endpoint")
def new_endpoint():
    """Description of what this endpoint does."""
    # Implementation
    return jsonify({"data": result})
```

### Fetching New Garmin Data Type

```python
def fetch_new_metric(client, date_str):
    """Fetch new health metric from Garmin."""
    try:
        data = client.get_new_metric(date_str)
        return data.get("metric_value")
    except Exception as e:
        print(f"  Warning: Failed to get metric for {date_str}: {e}")
        return None
```

## Security Notes

- Never commit `.env` file (contains OAuth token)
- Never commit `cache/` directory (contains personal health data)
- `.gitignore` is configured to exclude sensitive files
- No authentication on API endpoints (local use only)

## Testing

- Test authentication: `uv run setup_oauth.py`
- Test API: `curl http://127.0.0.1:5000/api/summary?months=1`
- Clear cache: `rm cache/*.json` then re-fetch

## Resources

- [garminconnect documentation](https://github.com/cyberjunky/python-garminconnect)
- [uv documentation](https://github.com/astral-sh/uv)
- [Flask documentation](https://flask.palletsprojects.com/)

## Code Generation Guidelines

When generating code for this project:

1. **Use uv commands** not pip/python directly
2. **Preserve all health data fields** - research depends on completeness
3. **Add tqdm progress bars** for any loops over dates/activities
4. **Handle API failures gracefully** - partial data is valuable
5. **Update database schema** if adding new data fields
6. **Document all functions** with clear docstrings
7. **Follow existing patterns** for consistency
8. **Test locally** before committing

## Known Limitations

- Garmin API rate limits may slow initial data fetch
- OAuth token expires after ~1 year (re-run setup_oauth.py)
- Some Garmin metrics may not be available for all users
- Database grows with more data (no automatic cleanup)
