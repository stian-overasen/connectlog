#!/usr/bin/env python3
"""
Garmin Connect Log API
Flask app to fetch and analyze Garmin Connect health data for ME/CFS PEM threshold research
"""

import json
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from garminconnect import Garmin
from tqdm import tqdm

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.json.sort_keys = False

# Configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
GARMIN_SESSION = os.getenv("GARMIN_SESSION")
GARMIN_NAME = os.getenv("GARMIN_NAME")
HR_PROFILE_OVERRIDES_PATH = os.getenv("HR_PROFILE_OVERRIDES_PATH")
DEFAULT_WEEKS = 1

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)

GARMIN_ZONE_RANGES = [
    {"label": "Zone 5", "min_percent": 90, "max_percent": 100},
    {"label": "Zone 4", "min_percent": 80, "max_percent": 89},
    {"label": "Zone 3", "min_percent": 70, "max_percent": 79},
    {"label": "Zone 2", "min_percent": 60, "max_percent": 69},
    {"label": "Zone 1", "min_percent": 50, "max_percent": 59},
]

OLYMPIATOPPEN_ZONE_RANGES = [
    {"label": "I-5", "min_percent": 92, "max_percent": 100},
    {"label": "I-4", "min_percent": 87, "max_percent": 91},
    {"label": "I-3", "min_percent": 82, "max_percent": 86},
    {"label": "I-2", "min_percent": 72, "max_percent": 81},
    {"label": "I-1", "min_percent": 55, "max_percent": 71},
]

SUMMARY_FIELD_RENAMES = {
    "steps": "totalSteps",
    "hrv_overnight_avg": "hrvLastNightAvg",
    "resting_hr": "restingHeartRate",
    "max_hr": "maxHeartRate",
    "body_battery_max": "bodyBatteryMax",
    "body_battery_min": "bodyBatteryMin",
    "sleep_duration": "sleepDuration",
    "sleep_score": "sleepScore",
}


def parse_date_or_none(date_str, field_name):
    """Parse a YYYY-MM-DD string to a date or return None."""
    if date_str in (None, ""):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {date_str}. Expected YYYY-MM-DD.") from exc


def load_hr_profile_overrides():
    """Load HR profile overrides from JSON file specified by HR_PROFILE_OVERRIDES_PATH."""
    if not HR_PROFILE_OVERRIDES_PATH:
        return []

    if not os.path.exists(HR_PROFILE_OVERRIDES_PATH):
        print(f"Warning: HR_PROFILE_OVERRIDES_PATH not found: {HR_PROFILE_OVERRIDES_PATH}")
        return []

    try:
        with open(HR_PROFILE_OVERRIDES_PATH) as f:
            raw_overrides = json.load(f)
    except Exception as exc:
        print(f"Warning: Failed to load HR profile overrides: {exc}")
        return []

    overrides = []
    for entry in raw_overrides:
        zone_scheme = (entry.get("zone_scheme") or "").lower()
        if zone_scheme not in {"garmin", "olympiatoppen"}:
            raise ValueError(f"Invalid zone_scheme in overrides: {zone_scheme}")

        start_date = parse_date_or_none(entry.get("start_date"), "start_date")
        end_date = parse_date_or_none(entry.get("end_date"), "end_date")

        if start_date and end_date and start_date > end_date:
            raise ValueError(f"start_date after end_date in overrides: {entry}")

        overrides.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "device": entry.get("device"),
                "max_hr": entry.get("max_hr"),
                "zone_scheme": zone_scheme,
            }
        )

    validate_hr_profile_overlaps(overrides)
    return overrides


def validate_hr_profile_overlaps(overrides):
    """Validate that HR profile override ranges do not overlap."""
    if not overrides:
        return

    def range_bounds(item):
        start = item["start_date"] or datetime.min.date()
        end = item["end_date"] or datetime.max.date()
        return start, end

    for idx, current in enumerate(overrides):
        current_start, current_end = range_bounds(current)
        for other in overrides[idx + 1 :]:
            other_start, other_end = range_bounds(other)
            overlaps = current_start <= other_end and other_start <= current_end
            if overlaps:
                raise ValueError(
                    "Overlapping HR profile overrides detected between "
                    f"{current.get('start_date')}–{current.get('end_date')} and "
                    f"{other.get('start_date')}–{other.get('end_date')}"
                )


def get_hr_zone_context(activity_date, overrides):
    """Get HR zone context for the activity date, using overrides or default Garmin zones."""
    if activity_date is None:
        return {
            "zone_scheme": "garmin",
            "max_hr": None,
            "device": None,
        }

    selected = None
    for override in overrides:
        start = override["start_date"]
        end = override["end_date"]
        if start and activity_date < start:
            continue
        if end and activity_date > end:
            continue
        selected = override
        break

    return {
        "zone_scheme": (selected or {}).get("zone_scheme", "garmin"),
        "max_hr": (selected or {}).get("max_hr"),
        "device": (selected or {}).get("device"),
    }


def format_hr_zones_with_labels(zones, zone_scheme):
    """Format HR zones with scheme-specific labels."""
    if not zones:
        return None

    scheme_name = "Olympiatoppen" if zone_scheme == "olympiatoppen" else "Garmin"
    zone_ranges = OLYMPIATOPPEN_ZONE_RANGES if zone_scheme == "olympiatoppen" else GARMIN_ZONE_RANGES

    formatted_zones = []
    for zone_data in zones:
        zone_num = zone_data["zone"]
        # Find the matching zone label (zone_ranges are ordered 5 to 1)
        zone_label = zone_ranges[5 - zone_num]["label"]
        formatted_zones.append(
            {
                f"{zone_label} ({scheme_name})": zone_num,
                "time_seconds": zone_data["time_seconds"],
            }
        )

    return formatted_zones


def get_cache_filename(data_type, weeks):
    """Get cache filename for specified data type and weeks."""
    return os.path.join(CACHE_DIR, f"{data_type}-last-{weeks}-weeks.json")


def load_cache(data_type, weeks):
    """Load cached data from JSON file."""
    cache_file = get_cache_filename(data_type, weeks)
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached_data = json.load(f)

            if data_type == "summary":
                normalized_data = normalize_summary_cache_payload(cached_data)
                if normalized_data != cached_data:
                    save_cache(data_type, weeks, normalized_data)
                return normalized_data

            return cached_data
        except Exception as e:
            print(f"Warning: Failed to load cache from {cache_file}: {e}")
    return None


def save_cache(data_type, weeks, data):
    """Save data to JSON cache file."""
    cache_file = get_cache_filename(data_type, weeks)
    try:
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save cache to {cache_file}: {e}")


def get_garmin_client():
    """Create and authenticate Garmin Connect client."""
    if not GARMIN_SESSION:
        raise Exception("GARMIN_SESSION not found in .env file. Run setup_oauth.py first.")

    client = Garmin()
    client.garth.loads(GARMIN_SESSION)

    # Fetch user profile to set display name (prevents 403 errors)
    client.display_name = client.get_full_name()
    profile = client.get_user_profile()

    try:
        client.display_name = client.get_full_name() or GARMIN_NAME
    except Exception:
        # Fallback to getting display name from user summary
        try:
            profile = client.get_user_profile()
            client.display_name = profile.get("displayName") or profile.get("userName")
        except Exception:
            pass

    return client


def format_duration(seconds):
    """Format duration in seconds to human-readable format (HHh MMm SSs)."""
    if seconds is None:
        return None
    seconds = int(seconds)  # Convert to int in case it's a float
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:01d}h {minutes:02d}m {secs:02d}s"


def format_sleep_duration(seconds):
    """Format sleep duration without leading zero for hours."""
    if seconds is None:
        return None
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m"


HR_PROFILE_OVERRIDES = load_hr_profile_overrides()


def parse_required_date(date_str, field_name):
    """Parse and validate a required YYYY-MM-DD date string."""
    parsed = parse_date_or_none(date_str, field_name)
    if parsed is None:
        raise ValueError(f"Missing required {field_name}. Expected YYYY-MM-DD.")
    return parsed


def parse_positive_int_query_param(name, default):
    """Parse a positive integer query parameter from the current request."""
    raw_value = request.args.get(name, str(default))

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc

    if value < 1:
        raise ValueError(f"{name} must be a positive integer.")

    return value


def get_date_range_for_weeks(weeks):
    """Get an inclusive date range covering the requested number of weeks."""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=(weeks * 7) - 1)
    return start_date, end_date


def normalize_summary_field_names(summary):
    """Rename legacy summary field names to the current API field names."""
    normalized_summary = summary.copy()

    for legacy_name, current_name in SUMMARY_FIELD_RENAMES.items():
        if legacy_name in normalized_summary:
            legacy_value = normalized_summary.pop(legacy_name)
            normalized_summary.setdefault(current_name, legacy_value)

    return normalized_summary


def normalize_summary_cache_payload(payload):
    """Normalize cached summary payloads to the current API field names."""
    if not isinstance(payload, dict):
        return payload

    summaries = payload.get("summaries")
    if not isinstance(summaries, list):
        return payload

    normalized_payload = payload.copy()
    normalized_payload["summaries"] = [normalize_summary_field_names(summary) for summary in summaries]
    return normalized_payload


def fetch_daily_summary(client, date_str):
    """Fetch daily health summary for a specific date."""
    summary = {
        "date": date_str,
        "totalSteps": None,
        "hrvLastNightAvg": None,
        "restingHeartRate": None,
        "maxHeartRate": None,
        "bodyBatteryMax": None,
        "bodyBatteryMin": None,
        "sleepDuration": None,
        "sleepScore": None,
        "numberOfActivities": 0,
    }

    try:
        # Get daily stats (resting HR, max HR, steps)
        stats = client.get_stats(date_str)
        if stats:
            summary["totalSteps"] = stats.get("totalSteps")
            summary["restingHeartRate"] = stats.get("restingHeartRate")
            summary["maxHeartRate"] = stats.get("maxHeartRate")
    except Exception as e:
        print(f"  Warning: Failed to get stats for {date_str}: {e}")

    try:
        # Get HRV data
        hrv_data = client.get_hrv_data(date_str)
        if hrv_data and "hrvSummary" in hrv_data:
            summary["hrvLastNightAvg"] = hrv_data["hrvSummary"].get("lastNightAvg")
    except Exception as e:
        print(f"  Warning: Failed to get HRV for {date_str}: {e}")

    try:
        # Get Body Battery hourly data
        bb_data = client.get_body_battery(date_str)

        values = []
        if bb_data:
            for entry in bb_data:
                values.extend(point[-1] for point in entry.get("bodyBatteryValuesArray", []) if point and point[-1] is not None)

            if values:
                summary["bodyBatteryMax"] = max(values)
                summary["bodyBatteryMin"] = min(values)
    except Exception as e:
        print(f"  Warning: Failed to get Body Battery for {date_str}: {e}")

    try:
        # Get sleep data
        sleep_data = client.get_sleep_data(date_str)
        if sleep_data and "dailySleepDTO" in sleep_data:
            sleep = sleep_data["dailySleepDTO"]
            summary["sleepDuration"] = sleep.get("sleepTimeSeconds")
            summary["sleepScore"] = sleep.get("sleepScores", {}).get("overall", {}).get("value")
    except Exception as e:
        print(f"  Warning: Failed to get sleep data for {date_str}: {e}")

    return summary


def fetch_activities(client, start_date, end_date):
    """Fetch activities for a date range."""
    activities = []

    try:
        # Get activities in date range
        activity_list = client.get_activities_by_date(start_date, end_date)

        for activity in activity_list:
            # Extract HR zones from hrTimeInZone fields
            hr_zones = None

            zones = []
            for i in range(5, 0, -1):  # HR zones 5-1 inclusive
                time_in_zone = activity.get(f"hrTimeInZone_{i}")
                if time_in_zone is not None:
                    zones.append({"zone": i, "time_seconds": float(f"{time_in_zone:.2f}")})

            if zones:
                hr_zones = zones

            # Extract body battery impact from differenceBodyBattery
            body_battery_impact = activity.get("differenceBodyBattery")

            # Combine date and time into single datetime string
            start_time_local = activity.get("startTimeLocal", "")
            activity_date = None
            if start_time_local:
                try:
                    activity_date = datetime.strptime(start_time_local[:10], "%Y-%m-%d").date()
                except ValueError:
                    activity_date = None

            hr_zone_context = get_hr_zone_context(activity_date, HR_PROFILE_OVERRIDES) if activity_date else get_hr_zone_context(None, HR_PROFILE_OVERRIDES)

            # Format hr_zones with scheme-specific labels
            formatted_hr_zones = format_hr_zones_with_labels(hr_zones, hr_zone_context["zone_scheme"])

            activities.append(
                {
                    "datetime": start_time_local,
                    "activity_type": activity.get("activityType", {}).get("typeKey"),
                    "duration": activity.get("duration"),
                    "distance": activity.get("distance"),
                    "hr_zones": formatted_hr_zones,
                    "device": hr_zone_context["device"],
                    "device_max_hr": hr_zone_context["max_hr"],
                    "body_battery_impact": body_battery_impact,
                }
            )

    except Exception as e:
        print(f"  Warning: Failed to get activities: {e}")

    return activities


def count_activities_by_date(activities):
    """Count activities per date from activities list."""
    activity_counts = {}
    for activity in activities:
        # Extract date from datetime string (format: "YYYY-MM-DD HH:MM:SS")
        datetime_str = activity.get("datetime", "")
        if datetime_str:
            date = datetime_str.split()[0] if " " in datetime_str else datetime_str[:10]
            activity_counts[date] = activity_counts.get(date, 0) + 1
    return activity_counts


def format_summaries_for_output(summaries):
    """Format summaries with human-readable durations for output."""
    formatted = []
    for summary in summaries:
        formatted_summary = normalize_summary_field_names(summary)
        sleep_duration = formatted_summary.get("sleepDuration")
        if isinstance(sleep_duration, int | float):
            formatted_summary["sleepDuration"] = format_sleep_duration(sleep_duration)
        formatted.append(formatted_summary)
    return formatted


def format_activities_for_output(activities):
    """Format activities with human-readable durations and distances for output."""
    formatted = []
    for activity in activities:
        formatted_activity = activity.copy()
        formatted_activity["duration"] = format_duration(activity.get("duration"))
        if activity.get("distance") is not None:
            formatted_activity["distance"] = f"{activity['distance'] / 1000:.2f}km"
        formatted.append(formatted_activity)
    return formatted


def create_mcp_server():
    """Create an MCP server exposing Garmin fetch tools."""
    if FastMCP is None:
        raise RuntimeError("MCP support requires the 'mcp' package. Run 'uv sync' to install dependencies.")

    mcp = FastMCP("connectlog")

    @mcp.tool(name="fetch_daily_summary")
    def mcp_fetch_daily_summary(date):
        """Fetch Garmin daily summary for a single date.

        Args:
            date: Date in YYYY-MM-DD format.
        """
        parsed_date = parse_required_date(date, "date")
        client = get_garmin_client()
        return fetch_daily_summary(client, parsed_date.strftime("%Y-%m-%d"))

    @mcp.tool(name="fetch_activities")
    def mcp_fetch_activities(start_date, end_date):
        """Fetch Garmin activities for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
        """
        parsed_start = parse_required_date(start_date, "start_date")
        parsed_end = parse_required_date(end_date, "end_date")
        if parsed_start > parsed_end:
            raise ValueError("start_date must be before or equal to end_date.")

        activities = fetch_activities(
            client=get_garmin_client(),
            start_date=parsed_start.strftime("%Y-%m-%d"),
            end_date=parsed_end.strftime("%Y-%m-%d"),
        )
        return {
            "activities": format_activities_for_output(activities),
            "hr_zone_percentages": {
                "garmin": GARMIN_ZONE_RANGES,
                "olympiatoppen": OLYMPIATOPPEN_ZONE_RANGES,
            },
        }

    return mcp


def run_flask_server():
    """Run Flask API server."""
    print("Garmin Connect Log API")
    print("=" * 50)
    print("Starting Flask server on http://127.0.0.1:5000")
    print("API endpoints:")
    print("  /api/summary - Daily health summaries (JSON)")
    print("  /api/activities - Activities (JSON)")
    print("Parameters:")
    print(f"  weeks={DEFAULT_WEEKS} (default for summary/activities)")
    print()
    app.run(debug=True, port=5000)


def run_mcp_server():
    """Run MCP server exposing Garmin fetch tools over stdio."""
    mcp_server = create_mcp_server()
    print("Garmin Connect Log MCP server")
    print("=" * 50)
    print("Starting MCP server over stdio")
    print("Tools:")
    print("  fetch_daily_summary(date)")
    print("  fetch_activities(start_date, end_date)")
    mcp_server.run()


@app.route("/")
def index():
    """API documentation endpoint."""
    return jsonify(
        {
            "name": "Garmin Connect Log API",
            "description": "Fetch Garmin Connect health data for ME/CFS PEM threshold research",
            "endpoints": {
                "/api/summary": {
                    "method": "GET",
                    "parameters": {
                        "weeks": f"Number of weeks to fetch (default: {DEFAULT_WEEKS})",
                    },
                    "description": "Get daily health summaries for specified period",
                },
                "/api/activities": {
                    "method": "GET",
                    "parameters": {
                        "weeks": f"Number of weeks to fetch (default: {DEFAULT_WEEKS})",
                    },
                    "description": "Get activities for specified period",
                },
            },
        }
    )


@app.route("/api/summary")
def api_summary():
    """Get daily health summaries for specified period."""
    try:
        weeks = parse_positive_int_query_param("weeks", DEFAULT_WEEKS)
        start_date, end_date = get_date_range_for_weeks(weeks)
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        print(f"Fetching summaries from {start_date_str} to {end_date_str}...")

        # Try to load from cache
        cached_data = load_cache("summary", weeks)

        if cached_data:
            print(f"✓ Loaded summaries from cache (summary-last-{weeks}-weeks.json)")
            return jsonify(cached_data)

        # Generate all dates in range
        all_dates = []
        current = end_date
        while current >= start_date:
            all_dates.append(current.strftime("%Y-%m-%d"))
            current -= timedelta(days=1)

        # Fetch daily summaries from Garmin
        print(f"Fetching {len(all_dates)} days from Garmin Connect...")
        client = get_garmin_client()

        daily_summaries = []
        for date_str in tqdm(all_dates, desc="Daily summaries", unit="day"):
            summary = fetch_daily_summary(client, date_str)
            daily_summaries.append(summary)

        # Fetch activities and count per date
        print("Fetching activities to count per day...")
        activities = fetch_activities(client, start_date_str, end_date_str)
        activity_counts = count_activities_by_date(activities)

        # Add activity counts to summaries
        for summary in daily_summaries:
            summary["numberOfActivities"] = activity_counts.get(summary["date"], 0)

        # Prepare response data
        response_data = {
            "summaries": format_summaries_for_output(daily_summaries),
        }

        # Save to cache
        save_cache("summary", weeks, response_data)
        print(f"✓ Summaries cached to summary-last-{weeks}-weeks.json")

        return jsonify(response_data)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Error fetching summaries from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/activities")
def api_activities():
    """Get activities for specified period."""
    try:
        weeks = parse_positive_int_query_param("weeks", DEFAULT_WEEKS)
        start_date, end_date = get_date_range_for_weeks(weeks)
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        print(f"Fetching activities from {start_date_str} to {end_date_str}...")

        # Try to load from cache
        cached_data = load_cache("activities", weeks)

        if cached_data:
            print(f"✓ Loaded activities from cache (activities-last-{weeks}-weeks.json)")
            return jsonify(cached_data)

        # Fetch activities from Garmin
        print("Fetching activities from Garmin Connect...")
        client = get_garmin_client()

        activities = fetch_activities(client, start_date_str, end_date_str)

        # Prepare response data
        response_data = {
            "activities": format_activities_for_output(activities),
            "hr_zone_percentages": {
                "garmin": GARMIN_ZONE_RANGES,
                "olympiatoppen": OLYMPIATOPPEN_ZONE_RANGES,
            },
        }

        # Save to cache
        save_cache("activities", weeks, response_data)
        print(f"✓ Activities cached to activities-last-{weeks}-weeks.json")

        return jsonify(response_data)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Error fetching activities from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    if "--mcp" in sys.argv:
        run_mcp_server()
    else:
        run_flask_server()
