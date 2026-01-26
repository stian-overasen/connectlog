#!/usr/bin/env python3
"""
Garmin Connect Log API
Flask app to fetch and analyze Garmin Connect health data for ME/CFS PEM threshold research
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from garminconnect import Garmin
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

app = Flask(__name__)

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
            steps INTEGER,
            sleep_duration INTEGER,
            sleep_score INTEGER
        )
    """)
    
    # Activities table
    c.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            activity_id INTEGER PRIMARY KEY,
            date TEXT,
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
    return client


def fetch_daily_summary(client, date_str):
    """Fetch daily health summary for a specific date."""
    summary = {
        "date": date_str,
        "resting_hr": None,
        "max_hr": None,
        "hrv": None,
        "body_battery_hourly": None,
        "steps": None,
        "sleep_duration": None,
        "sleep_score": None
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
            summary["hrv"] = hrv_data["hrvSummary"].get("weeklyAvg")
    except Exception as e:
        print(f"  Warning: Failed to get HRV for {date_str}: {e}")
    
    try:
        # Get Body Battery hourly data
        next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        bb_data = client.get_body_battery(date_str, next_day)
        
        if bb_data:
            hourly_values = []
            for entry in bb_data:
                timestamp = entry.get("startTimestampLocal") or entry.get("startTimestampGMT")
                if timestamp:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    hour = dt.hour
                    value = entry.get("charged") or entry.get("drained") or entry.get("value")
                    if value is not None:
                        hourly_values.append({"hour": hour, "value": value})
            
            if hourly_values:
                summary["body_battery_hourly"] = json.dumps(hourly_values)
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
            activity_id = activity.get("activityId")
            if not activity_id:
                continue
            
            try:
                # Get detailed activity data
                details = client.get_activity(activity_id)
                
                # Extract HR zones
                hr_zones = None
                if "heartRateZones" in details:
                    zones = []
                    for zone in details["heartRateZones"]:
                        zones.append({
                            "zone": zone.get("zoneNumber"),
                            "time_seconds": zone.get("secsInZone")
                        })
                    hr_zones = json.dumps(zones)
                
                # Extract body battery impact
                bb_impact = None
                if "bodyBattery" in details:
                    bb_data = details["bodyBattery"]
                    start_val = bb_data.get("startValue")
                    end_val = bb_data.get("endValue")
                    if start_val is not None and end_val is not None:
                        bb_impact = end_val - start_val
                
                activities.append({
                    "activity_id": activity_id,
                    "date": activity.get("startTimeLocal", "").split()[0],
                    "activity_type": activity.get("activityType", {}).get("typeKey"),
                    "duration": activity.get("duration"),
                    "distance": activity.get("distance"),
                    "hr_zones": hr_zones,
                    "bb_impact": bb_impact
                })
                
            except Exception as e:
                print(f"  Warning: Failed to get details for activity {activity_id}: {e}")
                continue
    
    except Exception as e:
        print(f"  Warning: Failed to get activities: {e}")
    
    return activities


def save_daily_summary(summary):
    """Save daily summary to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        INSERT OR REPLACE INTO daily_summaries 
        (date, resting_hr, max_hr, hrv, body_battery_hourly, steps, sleep_duration, sleep_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        summary["date"],
        summary["resting_hr"],
        summary["max_hr"],
        summary["hrv"],
        summary["body_battery_hourly"],
        summary["steps"],
        summary["sleep_duration"],
        summary["sleep_score"]
    ))
    
    conn.commit()
    conn.close()


def save_activity(activity):
    """Save activity to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        INSERT OR REPLACE INTO activities
        (activity_id, date, activity_type, duration, distance, hr_zones, bb_impact)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        activity["activity_id"],
        activity["date"],
        activity["activity_type"],
        activity["duration"],
        activity["distance"],
        activity["hr_zones"],
        activity["bb_impact"]
    ))
    
    conn.commit()
    conn.close()


def get_daily_summaries_from_db(start_date, end_date):
    """Retrieve daily summaries from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT date, resting_hr, max_hr, hrv, body_battery_hourly, steps, sleep_duration, sleep_score
        FROM daily_summaries
        WHERE date >= ? AND date <= ?
        ORDER BY date
    """, (start_date, end_date))
    
    rows = c.fetchall()
    conn.close()
    
    summaries = []
    for row in rows:
        summary = {
            "date": row[0],
            "resting_hr": row[1],
            "max_hr": row[2],
            "hrv": row[3],
            "body_battery_hourly": json.loads(row[4]) if row[4] else None,
            "steps": row[5],
            "sleep_duration": row[6],
            "sleep_score": row[7]
        }
        summaries.append(summary)
    
    return summaries


def get_activities_from_db(start_date, end_date):
    """Retrieve activities from database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT activity_id, date, activity_type, duration, distance, hr_zones, bb_impact
        FROM activities
        WHERE date >= ? AND date <= ?
        ORDER BY date
    """, (start_date, end_date))
    
    rows = c.fetchall()
    conn.close()
    
    activities = []
    for row in rows:
        activity = {
            "activity_id": row[0],
            "date": row[1],
            "activity_type": row[2],
            "duration": row[3],
            "distance": row[4],
            "hr_zones": json.loads(row[5]) if row[5] else None,
            "bb_impact": row[6]
        }
        activities.append(activity)
    
    return activities


def get_dates_in_db(start_date, end_date):
    """Get set of dates that already have data in database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("""
        SELECT DISTINCT date FROM daily_summaries
        WHERE date >= ? AND date <= ?
    """, (start_date, end_date))
    
    dates = {row[0] for row in c.fetchall()}
    conn.close()
    
    return dates


@app.route("/")
def index():
    """API documentation endpoint."""
    return jsonify({
        "name": "Garmin Connect Log API",
        "description": "Fetch Garmin Connect health data for ME/CFS PEM threshold research",
        "endpoints": {
            "/api/summary": {
                "method": "GET",
                "parameters": {
                    "months": "Number of months to fetch (default: 3)"
                },
                "description": "Get daily summaries and activities for specified period"
            }
        }
    })


@app.route("/api/summary")
def api_summary():
    """Get daily summaries and activities for specified period."""
    # Get months parameter (default: 3)
    months = request.args.get("months", default=3, type=int)
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)
    
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    print(f"Fetching data from {start_date_str} to {end_date_str}...")
    
    # Initialize database
    init_db()
    
    # Check which dates are already in database
    existing_dates = get_dates_in_db(start_date_str, end_date_str)
    
    # Generate all dates in range
    all_dates = []
    current = start_date
    while current <= end_date:
        all_dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    
    # Find missing dates
    missing_dates = [d for d in all_dates if d not in existing_dates]
    
    if missing_dates:
        print(f"Fetching {len(missing_dates)} missing days from Garmin Connect...")
        
        try:
            client = get_garmin_client()
            
            # Fetch missing daily summaries
            for date_str in missing_dates:
                print(f"  Fetching {date_str}...")
                summary = fetch_daily_summary(client, date_str)
                save_daily_summary(summary)
            
            # Fetch activities for entire date range
            print(f"Fetching activities...")
            activities = fetch_activities(client, start_date_str, end_date_str)
            for activity in activities:
                save_activity(activity)
            
            print(f"✓ Data fetched and cached")
            
        except Exception as e:
            print(f"Error fetching data from Garmin: {e}")
            return jsonify({"error": str(e)}), 500
    else:
        print("All data already cached")
    
    # Retrieve data from database
    daily_summaries = get_daily_summaries_from_db(start_date_str, end_date_str)
    activities = get_activities_from_db(start_date_str, end_date_str)
    
    return jsonify({
        "start_date": start_date_str,
        "end_date": end_date_str,
        "daily_summaries": daily_summaries,
        "activities": activities
    })


if __name__ == "__main__":
    print("Garmin Connect Log API")
    print("=" * 50)
    print("Starting Flask server on http://127.0.0.1:5000")
    print("API endpoint: http://127.0.0.1:5000/api/summary?months=3")
    print()
    app.run(debug=True, port=5000)
