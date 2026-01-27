#!/usr/bin/env python3
"""
Garmin Connect Log API
Flask app to fetch and analyze Garmin Connect health data for ME/CFS PEM threshold research
"""

import json
import os
import sqlite3
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
DB_PATH = os.path.join(CACHE_DIR, "data.db")
GARMIN_SESSION = os.getenv("GARMIN_SESSION")

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


def init_db():
    """Initialize SQLite database with schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Daily summaries table
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summaries (
            date TEXT PRIMARY KEY,
            resting_hr INTEGER,
            max_hr INTEGER,
            hrv REAL,
            body_battery_hourly TEXT,
            body_battery_min INTEGER,
            body_battery_max INTEGER,
            steps INTEGER,
            sleep_duration INTEGER,
            sleep_score INTEGER
        )
    """)

    # Activities table
    c.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            datetime TEXT PRIMARY KEY,
            activity_type TEXT,
            duration INTEGER,
            distance REAL,
            hr_zones TEXT,
            bb_impact INTEGER
        )
    """)

    conn.commit()
    conn.close()


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
        client.display_name = client.get_full_name() or "N/A"
    except Exception:
        # Fallback to getting display name from user summary
        try:
            profile = client.get_user_profile()
            client.display_name = profile.get('displayName') or profile.get('userName')
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
        "resting_hr": None,
        "max_hr": None,
        "hrv": None,
        "body_battery_hourly": None,
        "body_battery_min": None,
        "body_battery_max": None,
        "steps": None,
        "sleep_duration": None,
        "sleep_score": None,
    }

    try:
        # Get daily stats (resting HR, max HR, steps)
        stats = client.get_stats(date_str)
        if stats:
            summary["resting_hr"] = stats.get("restingHeartRate")
            summary["max_hr"] = stats.get("maxHeartRate")
            summary["steps"] = stats.get("totalSteps")
    except Exception as e:
        print(f"  Warning: Failed to get stats for {date_str}: {e}")

    try:
        # Get HRV data
        hrv_data = client.get_hrv_data(date_str)
        if hrv_data and "hrvSummary" in hrv_data:
            summary["hrv"] = hrv_data["hrvSummary"].get("lastNightAvg")
    except Exception as e:
        print(f"  Warning: Failed to get HRV for {date_str}: {e}")

    try:
        # Get Body Battery hourly data
        bb_data = client.get_body_battery(date_str)

        if bb_data:
            for entry in bb_data:
                values = [tup[-1] for tup in entry.get("bodyBatteryValuesArray", [])]

            if values:
                summary["body_battery_hourly"] = ",".join(map(str, values))
                summary["body_battery_max"] = max(values)
                summary["body_battery_min"] = min(values)
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


def save_daily_summary(summary):
    """Save daily summary to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        INSERT OR REPLACE INTO daily_summaries
        (date, resting_hr, max_hr, hrv, body_battery_hourly, body_battery_min, body_battery_max, steps, sleep_duration, sleep_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            summary["date"],
            summary["resting_hr"],
            summary["max_hr"],
            summary["hrv"],
            summary["body_battery_hourly"],
            summary["body_battery_min"],
            summary["body_battery_max"],
            summary["steps"],
            summary["sleep_duration"],
            summary["sleep_score"],
        ),
    )

    conn.commit()
    conn.close()


def save_activity(activity):
    """Save activity to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        INSERT OR REPLACE INTO activities
        (datetime, activity_type, duration, distance, hr_zones, bb_impact)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            activity["datetime"],
            activity["activity_type"],
            activity["duration"],
            activity["distance"],
            activity["hr_zones"],
            activity["bb_impact"],
        ),
    )

    conn.commit()
    conn.close()


def get_daily_summaries_from_db(start_date, end_date):
    """Retrieve daily summaries from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT date, resting_hr, max_hr, hrv, body_battery_hourly, body_battery_min, body_battery_max, steps, sleep_duration, sleep_score
        FROM daily_summaries
        WHERE date >= ? AND date <= ?
        ORDER BY date DESC
    """,
        (start_date, end_date),
    )

    rows = c.fetchall()
    conn.close()

    summaries = []
    for row in rows:
        summary = {
            "date": row[0],
            "resting_hr": row[1],
            "max_hr": row[2],
            "hrv": row[3],
            "body_battery_hourly": row[4],
            "body_battery_min": row[5],
            "body_battery_max": row[6],
            "steps": row[7],
            "sleep_duration": format_duration(row[8]),
            "sleep_score": row[9],
        }
        summaries.append(summary)

    return summaries


def get_activities_from_db(start_date, end_date):
    """Retrieve activities from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT datetime, activity_type, duration, distance, hr_zones, bb_impact
        FROM activities
        WHERE datetime >= ? AND datetime <= ?
        ORDER BY datetime DESC
    """,
        (start_date, end_date),
    )

    rows = c.fetchall()
    conn.close()

    activities = []
    for row in rows:
        activity = {
            "datetime": row[0],
            "activity_type": row[1],
            "duration": format_duration(row[2]),
            "distance": f"{row[3] / 1000:.2f}km" if row[3] is not None else None,
            "hr_zones": json.loads(row[4]) if row[4] else None,
            "bb_impact": row[5],
        }
        activities.append(activity)

    return activities


def get_dates_in_db(start_date, end_date):
    """Get set of dates that already have data in database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT DISTINCT date FROM daily_summaries
        WHERE date >= ? AND date <= ?
    """,
        (start_date, end_date),
    )

    dates = {row[0] for row in c.fetchall()}
    conn.close()

    return dates


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
                    "parameters": {"months": "Number of months to fetch (default: 1)"},
                    "description": "Get daily summaries and activities for specified period",
                }
            },
        }
    )


@app.route("/api/summary")
def api_summary():
    """Get daily summaries and activities for specified period."""
    # Get days parameter (default: 7 for last week)
    days = request.args.get("days", default=7, type=int)

    # Calculate date range - include today
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days - 1)  # -1 to include today

    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    print(f"Fetching data from {start_date_str} to {end_date_str}...")

    # Skip database caching during development - fetch directly from API
    try:
        client = get_garmin_client()

        # Generate all dates in range
        all_dates = []
        current = end_date
        while current >= start_date:
            all_dates.append(current.strftime("%Y-%m-%d"))
            current -= timedelta(days=1)

        # Fetch daily summaries
        print(f"Fetching {len(all_dates)} days from Garmin Connect...")
        daily_summaries = []
        for date_str in tqdm(all_dates, desc="Daily summaries", unit="day"):
            summary = fetch_daily_summary(client, date_str)
            # Format sleep duration for display
            if summary.get("sleep_duration"):
                summary["sleep_duration"] = format_sleep_duration(summary["sleep_duration"])
            daily_summaries.append(summary)

        # Fetch activities for entire date range
        print("Fetching activities...")
        activities = fetch_activities(client, start_date_str, end_date_str)

        # Format activity durations and distances for display
        for activity in activities:
            if activity.get("duration"):
                activity["duration"] = format_duration(activity["duration"])
            if activity.get("distance"):
                activity["distance"] = f"{activity['distance'] / 1000:.2f}km"

        print("✓ Data fetched successfully")
        return jsonify({
            "start_date": start_date_str,
            "end_date": end_date_str,
            "daily_summaries": daily_summaries,
            "activities": activities
        })

    except Exception as e:
        print(f"Error fetching data from Garmin: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Garmin Connect Log API")
    print("=" * 50)
    print("Starting Flask server on http://127.0.0.1:5000")
    print("API endpoint: http://127.0.0.1:5000/api/summary?days=7")
    print("(default: last 7 days including today)")
    print()
    app.run(debug=True, port=5000)
