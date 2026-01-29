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

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


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
            bb_impact = activity.get("differenceBodyBattery")

            # Combine date and time into single datetime string
            start_time_local = activity.get("startTimeLocal", "")

            activities.append(
                {
                    "datetime": start_time_local,
                    "activity_type": activity.get("activityType", {}).get("typeKey"),
                    "duration": activity.get("duration"),
                    "distance": activity.get("distance"),
                    "hr_zones": hr_zones,
                    "bb_impact": bb_impact,
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
        }

        # Save to cache
        save_cache("activities", months, response_data)
        print(f"✓ Activities cached to activities-last-{months}-months.json")

        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching activities from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Garmin Connect Log API")
    print("=" * 50)
    print("Starting Flask server on http://127.0.0.1:5000")
    print("API endpoints:")
    print("  /api/summary - Daily health summaries")
    print("  /api/activities - Activities")
    print("Parameters: months=2 (default)")
    print()
    app.run(debug=True, port=5000)
