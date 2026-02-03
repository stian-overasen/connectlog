#!/usr/bin/env python3
"""
Garmin Connect Log API
Flask app to fetch and analyze Garmin Connect health data for ME/CFS PEM threshold research
"""

import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from garminconnect import Garmin
from tqdm import tqdm

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.json.sort_keys = False

# Configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
GARMIN_SESSION = os.getenv("GARMIN_SESSION")
GARMIN_NAME = os.getenv("GARMIN_NAME")
HR_PROFILE_OVERRIDES_PATH = os.getenv("HR_PROFILE_OVERRIDES_PATH")

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


def get_cache_filename(data_type, months):
    """Get cache filename for specified data type and months."""
    return os.path.join(CACHE_DIR, f"{data_type}-last-{months}-months.json")


def load_cache(data_type, months):
    """Load cached data from JSON file."""
    cache_file = get_cache_filename(data_type, months)
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load cache from {cache_file}: {e}")
    return None


def save_cache(data_type, months, data):
    """Save data to JSON cache file."""
    cache_file = get_cache_filename(data_type, months)
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


def fetch_daily_summary(client, date_str):
    """Fetch daily health summary for a specific date."""
    summary = {
        "date": date_str,
        "steps": None,
        "hrv_overnight_avg": None,
        "resting_hr": None,
        "max_hr": None,
        "body_battery_max": None,
        "body_battery_min": None,
        "body_battery_values": None,
        "sleep_duration": None,
        "sleep_score": None,
        "num_activities": 0,
    }

    try:
        # Get daily stats (resting HR, max HR, steps)
        stats = client.get_stats(date_str)
        if stats:
            summary["steps"] = stats.get("totalSteps")
            summary["resting_hr"] = stats.get("restingHeartRate")
            summary["max_hr"] = stats.get("maxHeartRate")
    except Exception as e:
        print(f"  Warning: Failed to get stats for {date_str}: {e}")

    try:
        # Get HRV data
        hrv_data = client.get_hrv_data(date_str)
        if hrv_data and "hrvSummary" in hrv_data:
            summary["hrv_overnight_avg"] = hrv_data["hrvSummary"].get("lastNightAvg")
    except Exception as e:
        print(f"  Warning: Failed to get HRV for {date_str}: {e}")

    try:
        # Get Body Battery hourly data
        bb_data = client.get_body_battery(date_str)

        if bb_data:
            for entry in bb_data:
                values = [tup[-1] for tup in entry.get("bodyBatteryValuesArray", [])]

            if values:
                summary["body_battery_max"] = max(values)
                summary["body_battery_min"] = min(values)
                summary["body_battery_values"] = values
    except Exception as e:
        print(f"  Warning: Failed to get Body Battery for {date_str}: {e}")

    try:
        # Get sleep data
        sleep_data = client.get_sleep_data(date_str)
        if sleep_data and "dailySleepDTO" in sleep_data:
            sleep = sleep_data["dailySleepDTO"]
            summary["sleep_duration"] = sleep.get("sleepTimeSeconds")
            summary["sleep_score"] = sleep.get("sleepScores", {}).get("overall", {}).get("value")
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
        formatted_summary = summary.copy()
        formatted_summary["sleep_duration"] = format_sleep_duration(summary.get("sleep_duration"))
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
                        "months": "Number of months to fetch (default: 2)",
                    },
                    "description": "Get daily health summaries for specified period",
                },
                "/api/activities": {
                    "method": "GET",
                    "parameters": {
                        "months": "Number of months to fetch (default: 2)",
                    },
                    "description": "Get activities for specified period",
                },
            },
        }
    )


@app.route("/api/summary")
def api_summary():
    """Get daily health summaries for specified period."""
    # Get months parameter (default: 2)
    months = request.args.get("months", default=2, type=int)

    # Calculate date range - include today
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)  # Approximate months

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    print(f"Fetching summaries from {start_date_str} to {end_date_str}...")

    try:
        # Try to load from cache
        cached_data = load_cache("summary", months)

        if cached_data:
            print(f"✓ Loaded summaries from cache (summary-last-{months}-months.json)")
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
            summary["num_activities"] = activity_counts.get(summary["date"], 0)

        # Prepare response data
        response_data = {
            "summaries": format_summaries_for_output(daily_summaries),
        }

        # Save to cache
        save_cache("summary", months, response_data)
        print(f"✓ Summaries cached to summary-last-{months}-months.json")

        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching summaries from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/activities")
def api_activities():
    """Get activities for specified period."""
    # Get months parameter (default: 2)
    months = request.args.get("months", default=2, type=int)

    # Calculate date range - include today
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)  # Approximate months

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    print(f"Fetching activities from {start_date_str} to {end_date_str}...")

    try:
        # Try to load from cache
        cached_data = load_cache("activities", months)

        if cached_data:
            print(f"✓ Loaded activities from cache (activities-last-{months}-months.json)")
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
        save_cache("activities", months, response_data)
        print(f"✓ Activities cached to activities-last-{months}-months.json")

        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching activities from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def status():
    """Get current training readiness status based on today's metrics."""
    # Get subjective readiness score from query params (1-10 scale) - optional
    subjective_energy = request.args.get("energy")

    if subjective_energy is not None:
        try:
            subjective_energy = int(subjective_energy)
            if subjective_energy < 1 or subjective_energy > 10:
                return jsonify({"error": "Energy score must be between 1-10"}), 400
        except ValueError:
            return jsonify({"error": "Energy score must be an integer"}), 400

    try:
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")

        # Fetch today's data from Garmin
        client = get_garmin_client()
        summary = fetch_daily_summary(client, today)

        # Extract metrics
        hrv = summary.get("hrv_overnight_avg")
        body_battery_values = summary.get("body_battery_values")
        body_battery_start = max(body_battery_values) if body_battery_values else None
        body_battery_current = body_battery_values[-1] if body_battery_values else None
        sleep_score = summary.get("sleep_score")
        resting_hr = summary.get("resting_hr")

        # Evaluate each metric against thresholds
        def evaluate_metric(value, green_condition, yellow_condition):
            """Evaluate a metric and return status color."""
            if value is None:
                return "unknown"
            if green_condition(value):
                return "green"
            elif yellow_condition(value):
                return "yellow"
            else:
                return "red"

        hrv_status = evaluate_metric(hrv, lambda v: v > 62, lambda v: 58 <= v <= 62)
        body_battery_status = evaluate_metric(body_battery_start, lambda v: v > 75, lambda v: 65 <= v <= 75)
        sleep_score_status = evaluate_metric(sleep_score, lambda v: v > 75, lambda v: 70 <= v <= 75)
        resting_hr_status = evaluate_metric(resting_hr, lambda v: v < 48, lambda v: 48 <= v <= 50)

        # Energy zones for different levels
        energy_zones = {10: "green", 9: "green", 8: "green", 7: "green", 6: "yellow", 5: "yellow", 4: "red", 3: "red", 2: "red", 1: "red"}

        # Build metrics table
        metrics_table = [
            {"metric": "HRV", "current_value": hrv, "unit": "ms", "status": hrv_status, "green": ">62", "yellow": "58-62", "red": "<58"},
            {
                "metric": "Body Battery (start of day)",
                "current_value": body_battery_start,
                "unit": "points",
                "status": body_battery_status,
                "green": ">75",
                "yellow": "65-75",
                "red": "<65",

            },
            {
                "metric": "Body Battery (current)",
                "current_value": body_battery_current,
                "unit": "points",
                "status": None,  # Not used for calculation
                "green": "-",
                "yellow": "-",
                "red": "-",
            },
            {
                "metric": "Sleep Score",
                "current_value": sleep_score,
                "unit": "points",
                "status": sleep_score_status,
                "green": ">75",
                "yellow": "70-75",
                "red": "<70",
            },
            {"metric": "Resting HR", "current_value": resting_hr, "unit": "bpm", "status": resting_hr_status, "green": "<48", "yellow": "48-50", "red": ">50"},
        ]

        # Calculate overall status based on measurable metrics only
        status_scores = {
            "green": 2,
            "yellow": 1,
            "red": 0,
            "unknown": None,
        }

        statuses = [hrv_status, body_battery_status, sleep_score_status, resting_hr_status]
        scores = [status_scores[s] for s in statuses if s != "unknown"]

        if not scores:
            overall_status = "unknown"
            recommendation = "Insufficient data to determine readiness"
        else:
            avg_score = sum(scores) / len(scores)
            red_count = sum(1 for s in statuses if s == "red")

            if red_count >= 2 or avg_score < 1.0:
                overall_status = "red"
                recommendation = "Rest day recommended"
            elif avg_score >= 1.5:
                overall_status = "green"
                recommendation = "Training OK"
            else:
                overall_status = "yellow"
                recommendation = "Light activity only"

        # Energy level guidance (used in HTML rendering below)

        # Build HTML response
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Morning Check - {today}</title>
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    padding: 20px;
                }}
                .container {{
                    background: white;
                    border-radius: 20px;
                    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
                    max-width: 800px;
                    width: 100%;
                    padding: 40px;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .header h1 {{
                    font-size: 32px;
                    color: #2d3748;
                    margin-bottom: 10px;
                }}
                .header .date {{
                    font-size: 18px;
                    color: #718096;
                }}
                .status-banner {{
                    text-align: center;
                    padding: 20px;
                    border-radius: 12px;
                    margin-bottom: 30px;
                    font-size: 24px;
                    font-weight: bold;
                }}
                .status-green {{ background: #c6f6d5; color: #22543d; }}
                .status-yellow {{ background: #fefcbf; color: #744210; }}
                .status-red {{ background: #fed7d7; color: #742a2a; }}
                .status-unknown {{ background: #e2e8f0; color: #2d3748; }}
                .metrics-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-bottom: 30px;
                }}
                .metrics-table th {{
                    background: #f7fafc;
                    padding: 12px;
                    text-align: left;
                    font-weight: 600;
                    color: #2d3748;
                    border-bottom: 2px solid #e2e8f0;
                }}
                .metrics-table td {{
                    padding: 12px;
                    border-bottom: 1px solid #e2e8f0;
                }}
                .metrics-table tr:last-child td {{
                    border-bottom: none;
                }}
                .metric-name {{
                    font-weight: 500;
                    color: #2d3748;
                }}
                .metric-value {{
                    font-size: 18px;
                    font-weight: 600;
                }}
                .status-indicator {{
                    display: inline-block;
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    margin-right: 8px;
                }}
                .indicator-green {{ background: #48bb78; }}
                .indicator-yellow {{ background: #ecc94b; }}
                .indicator-red {{ background: #f56565; }}
                .indicator-none {{ background: #cbd5e0; }}
                .threshold {{
                    font-size: 12px;
                    color: #718096;
                }}
                .threshold-cell {{
                    text-align: center;
                    font-size: 11px;
                    color: #718096;
                }}
                .energy-guidance {{
                    background: #ebf8ff;
                    border-left: 4px solid #4299e1;
                    padding: 20px;
                    border-radius: 8px;
                    margin-top: 20px;
                }}
                .energy-guidance h3 {{
                    color: #2c5282;
                    margin-bottom: 12px;
                    font-size: 18px;
                }}
                .energy-guidance p {{
                    color: #2d3748;
                    margin-bottom: 8px;
                    line-height: 1.6;
                }}
                .energy-zones {{
                    display: flex;
                    gap: 15px;
                    margin-top: 15px;
                }}
                .zone {{
                    flex: 1;
                    padding: 10px;
                    border-radius: 8px;
                    text-align: center;
                    font-size: 14px;
                }}
                .zone-green {{ background: #c6f6d5; color: #22543d; }}
                .zone-yellow {{ background: #fefcbf; color: #744210; }}
                .zone-red {{ background: #fed7d7; color: #742a2a; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🌅 Morning Check</h1>
                    <div class="date">{today}</div>
                </div>

                <div class="status-banner status-{overall_status}">
                    {recommendation}
                </div>

                <table class="metrics-table">
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th>Current Value</th>
                            <th class="threshold-cell">🟢 Green</th>
                            <th class="threshold-cell">🟡 Yellow</th>
                            <th class="threshold-cell">🔴 Red</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        # Add metrics rows
        for metric in metrics_table:
            status_class = "none" if metric["status"] is None else metric["status"]
            indicator_class = f"indicator-{status_class}"
            value_display = f"{metric['current_value']} {metric['unit']}" if metric["current_value"] is not None else "N/A"

            html += f"""
                        <tr>
                            <td class="metric-name">
                                <span class="status-indicator {indicator_class}"></span>
                                {metric["metric"]}
                            </td>
                            <td class="metric-value">{value_display}</td>
                            <td class="threshold-cell">{metric["green"]}</td>
                            <td class="threshold-cell">{metric["yellow"]}</td>
                            <td class="threshold-cell">{metric["red"]}</td>
                        </tr>
            """

        html += """
                    </tbody>
                </table>
        """

        # Add energy guidance
        if subjective_energy is not None:
            energy_zone = energy_zones.get(subjective_energy, "red")
            zone_emoji = "🟢" if energy_zone == "green" else "🟡" if energy_zone == "yellow" else "🔴"
            html += f"""
                <div class="energy-guidance">
                    <h3>{zone_emoji} Energy Level Assessment</h3>
                    <p><strong>Your energy level:</strong> {subjective_energy}/10</p>
                    <p>With your energy level of {subjective_energy}/10, you are in the <strong>{energy_zone}</strong> zone.</p>
                </div>
            """
        else:
            html += """
                <div class="energy-guidance">
                    <h3>❓ What is your energy level today?</h3>
                    <p>Add your subjective energy level (1-10) to see your personalized recommendation:</p>
                    <div class="energy-zones">
                        <div class="zone zone-green">
                            <strong>🟢 Green</strong><br>
                            7-10/10
                        </div>
                        <div class="zone zone-yellow">
                            <strong>🟡 Yellow</strong><br>
                            5-6/10
                        </div>
                        <div class="zone zone-red">
                            <strong>🔴 Red</strong><br>
                            1-4/10
                        </div>
                    </div>
                    <p style="margin-top: 15px; font-size: 13px; color: #718096;">
                        Add <code>?energy=7</code> to the URL to include your energy level.
                    </p>
                </div>
            """

        html += """
            </div>
        </body>
        </html>
        """

        return html

    except Exception as e:
        print(f"Error fetching status from Garmin: {e}")
        return (
            f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: #f7fafc;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    padding: 20px;
                }}
                .error {{
                    background: white;
                    padding: 40px;
                    border-radius: 12px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    max-width: 500px;
                }}
                .error h1 {{
                    color: #e53e3e;
                    margin-bottom: 16px;
                }}
                .error p {{
                    color: #4a5568;
                }}
            </style>
        </head>
        <body>
            <div class="error">
                <h1>⚠️ Error</h1>
                <p>{str(e)}</p>
            </div>
        </body>
        </html>
        """,
            500,
        )


if __name__ == "__main__":
    print("Garmin Connect Log API")
    print("=" * 50)
    print("Starting Flask server on http://127.0.0.1:5000")
    print("API endpoints:")
    print("  /api/summary - Daily health summaries (JSON)")
    print("  /api/activities - Activities (JSON)")
    print("  /api/status - Training readiness status (HTML - open in browser)")
    print("Parameters:")
    print("  months=2 (default for summary/activities)")
    print("  energy=1-10 (optional for status)")
    print()
    app.run(debug=True, port=5000)
