#!/usr/bin/env python3
"""
Garmin Connect Log MCP Server
MCP server to fetch and analyze Garmin Connect health data for ME/CFS PEM threshold research
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from garminconnect import Garmin

from credentials import KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE, GarminSessionStorageError, MissingGarminSessionError, load_garmin_session_token

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None


def log_warning(message):
    """Write warnings to stderr so stdout stays valid for MCP JSON transport."""
    print(message, file=sys.stderr, flush=True)


def log_info(message):
    """Write informational startup logs to stderr."""
    print(message, file=sys.stderr, flush=True)


def log_startup_configuration_sources():
    """Log where key startup configuration values are loaded from."""
    log_info("Configuration sources:")
    log_info(f"  GARMIN_SESSION: OS keychain ({KEYCHAIN_SERVICE}/{KEYCHAIN_ACCOUNT})")

    try:
        load_garmin_session_token()
        log_info("  GARMIN_SESSION availability: keychain token found")
    except MissingGarminSessionError:
        log_warning("  GARMIN_SESSION availability: no token found in keychain")
    except GarminSessionStorageError as exc:
        log_warning(f"  GARMIN_SESSION availability: keychain access error: {exc}")

    log_info(f"  HR profile overrides: {HR_PROFILES_PATH}")
    log_info(f"    file exists: {HR_PROFILES_PATH.exists()}")


def get_global_cache_dir():
    """Resolve an OS-specific per-user cache directory for connectlog."""
    if os.name == "nt":
        base_cache_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base_cache_dir / "connectlog" / "cache"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "connectlog"

    base_cache_dir = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base_cache_dir / "connectlog"


# Configuration
CACHE_DIR = get_global_cache_dir()
HR_PROFILES_PATH = Path(__file__).resolve().parent / "hr_profiles.json"

# Ensure cache directory exists
CACHE_DIR.mkdir(parents=True, exist_ok=True)

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

CACHE_FILENAME_PATTERN = re.compile(r"^(summary|activities)-(\d{4}-\d{2}-\d{2})-to-(\d{4}-\d{2}-\d{2})\.json$")


def parse_date_or_none(date_str, field_name):
    """Parse a YYYY-MM-DD string to a date or return None."""
    if date_str in (None, ""):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {date_str}. Expected YYYY-MM-DD.") from exc


def load_hr_profile_overrides():
    """Load HR profile overrides from hr_profiles.json if present, else fall back to defaults."""
    if not HR_PROFILES_PATH.exists():
        return []

    try:
        with HR_PROFILES_PATH.open() as f:
            raw_overrides = json.load(f)
    except Exception as exc:
        log_warning(f"Warning: Failed to load HR profile overrides: {exc}")
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


def get_cache_filename(data_type, start_date, end_date):
    """Get cache filename for specified data type and date range."""
    return CACHE_DIR / f"{data_type}-{start_date}-to-{end_date}.json"


def list_cache_files(data_type):
    """List cache files for a data type with parsed date ranges."""
    cache_files = []
    for cache_file in CACHE_DIR.glob(f"{data_type}-*-to-*.json"):
        match = CACHE_FILENAME_PATTERN.match(cache_file.name)
        if not match:
            continue

        matched_data_type, start_date_str, end_date_str = match.groups()
        if matched_data_type != data_type:
            continue

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if start_date > end_date:
            continue

        cache_files.append(
            {
                "path": cache_file,
                "start_date": start_date,
                "end_date": end_date,
                "start_date_str": start_date_str,
                "end_date_str": end_date_str,
            }
        )

    return cache_files


def ranges_overlap(start_date_a, end_date_a, start_date_b, end_date_b):
    """Return True if two inclusive date ranges overlap."""
    return start_date_a <= end_date_b and start_date_b <= end_date_a


def build_dates_in_range(start_date, end_date):
    """Build ascending date list for an inclusive range."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def build_descending_date_strings(start_date, end_date):
    """Build descending YYYY-MM-DD date strings for an inclusive range."""
    date_strings = []
    current = end_date
    while current >= start_date:
        date_strings.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)
    return date_strings


def dates_to_ranges(dates):
    """Convert sorted unique dates to contiguous inclusive ranges."""
    if not dates:
        return []

    sorted_dates = sorted(set(dates))
    ranges = []
    range_start = sorted_dates[0]
    range_end = sorted_dates[0]

    for day in sorted_dates[1:]:
        if day == range_end + timedelta(days=1):
            range_end = day
            continue

        ranges.append((range_start, range_end))
        range_start = day
        range_end = day

    ranges.append((range_start, range_end))
    return ranges


def get_uncovered_dates(start_date, end_date, cached_ranges):
    """Get dates in a request range not covered by any cached range."""
    requested_dates = build_dates_in_range(start_date, end_date)
    uncovered = []

    for date_value in requested_dates:
        covered = any(range_start <= date_value <= range_end for range_start, range_end in cached_ranges)
        if not covered:
            uncovered.append(date_value)

    return uncovered


def load_cached_summaries_map(start_date, end_date):
    """Load cached summaries for overlapping cache files mapped by date."""
    summary_by_date = {}

    for cache_info in list_cache_files("summary"):
        if not ranges_overlap(start_date, end_date, cache_info["start_date"], cache_info["end_date"]):
            continue

        payload = load_cache("summary", cache_info["start_date_str"], cache_info["end_date_str"])
        if not isinstance(payload, dict):
            continue

        summaries = payload.get("summaries")
        if not isinstance(summaries, list):
            continue

        for summary in summaries:
            if not isinstance(summary, dict):
                continue

            date_str = summary.get("date")
            if not isinstance(date_str, str):
                continue

            try:
                date_value = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if not (start_date <= date_value <= end_date):
                continue

            summary_by_date.setdefault(date_str, normalize_summary_field_names(summary))

    return summary_by_date


def get_activity_date(activity):
    """Extract activity date from activity payload."""
    datetime_str = activity.get("datetime", "") if isinstance(activity, dict) else ""
    if not datetime_str:
        return None

    date_part = datetime_str.split()[0] if " " in datetime_str else datetime_str[:10]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_cached_activities(start_date, end_date):
    """Load cached activities and covered ranges for overlapping cache files."""
    cached_activities = []
    covered_ranges = []
    seen_keys = set()

    for cache_info in list_cache_files("activities"):
        if not ranges_overlap(start_date, end_date, cache_info["start_date"], cache_info["end_date"]):
            continue

        overlap_start = max(start_date, cache_info["start_date"])
        overlap_end = min(end_date, cache_info["end_date"])
        covered_ranges.append((overlap_start, overlap_end))

        payload = load_cache("activities", cache_info["start_date_str"], cache_info["end_date_str"])
        if not isinstance(payload, dict):
            continue

        activities = payload.get("activities")
        if not isinstance(activities, list):
            continue

        for activity in activities:
            if not isinstance(activity, dict):
                continue

            activity_date = get_activity_date(activity)
            if activity_date is None or not (start_date <= activity_date <= end_date):
                continue

            key = (
                activity.get("datetime"),
                activity.get("activity_type"),
                activity.get("duration"),
                activity.get("distance"),
            )
            if key in seen_keys:
                continue

            seen_keys.add(key)
            cached_activities.append(activity)

    return cached_activities, covered_ranges


def load_cache(data_type, start_date, end_date):
    """Load cached data from JSON file."""
    cache_file = get_cache_filename(data_type, start_date, end_date)
    if cache_file.exists():
        try:
            with cache_file.open() as f:
                cached_data = json.load(f)

            if data_type == "summary":
                normalized_data = normalize_summary_cache_payload(cached_data)
                if normalized_data != cached_data:
                    save_cache(data_type, start_date, end_date, normalized_data)
                return normalized_data

            return cached_data
        except Exception as e:
            log_warning(f"Warning: Failed to load cache from {cache_file}: {e}")
    return None


def save_cache(data_type, start_date, end_date, data):
    """Save data to JSON cache file."""
    cache_file = get_cache_filename(data_type, start_date, end_date)
    try:
        with cache_file.open("w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_warning(f"Warning: Failed to save cache to {cache_file}: {e}")


def get_garmin_client():
    """Create and authenticate Garmin Connect client."""
    try:
        garmin_session = load_garmin_session_token()
    except MissingGarminSessionError as exc:
        raise Exception("GARMIN_SESSION not found in OS keychain. Run setup_oauth.py first.") from exc
    except GarminSessionStorageError as exc:
        raise Exception(f"Failed to load GARMIN_SESSION from OS keychain: {exc}") from exc

    client = Garmin()
    client.garth.loads(garmin_session)

    # garth.loads() restores tokens but skips login(), which is what normally
    # populates display_name/full_name; fetch the profile directly instead,
    # since per-user API paths 403 without a display_name.
    profile = client.garth.profile
    if isinstance(profile, dict):
        client.display_name = profile.get("displayName")
        client.full_name = profile.get("fullName")

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
        log_warning(f"  Warning: Failed to get stats for {date_str}: {e}")

    try:
        # Get HRV data
        hrv_data = client.get_hrv_data(date_str)
        if hrv_data and "hrvSummary" in hrv_data:
            summary["hrvLastNightAvg"] = hrv_data["hrvSummary"].get("lastNightAvg")
    except Exception as e:
        log_warning(f"  Warning: Failed to get HRV for {date_str}: {e}")

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
        log_warning(f"  Warning: Failed to get Body Battery for {date_str}: {e}")

    try:
        # Get sleep data
        sleep_data = client.get_sleep_data(date_str)
        if sleep_data and "dailySleepDTO" in sleep_data:
            sleep = sleep_data["dailySleepDTO"]
            summary["sleepDuration"] = sleep.get("sleepTimeSeconds")
            summary["sleepScore"] = sleep.get("sleepScores", {}).get("overall", {}).get("value")
    except Exception as e:
        log_warning(f"  Warning: Failed to get sleep data for {date_str}: {e}")

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
        log_warning(f"  Warning: Failed to get activities: {e}")

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
        cached_summaries = load_cached_summaries_map(parsed_date, parsed_date)
        cached_summary = cached_summaries.get(parsed_date.strftime("%Y-%m-%d"))
        if cached_summary:
            return cached_summary

        client = get_garmin_client()
        return fetch_daily_summary(client, parsed_date.strftime("%Y-%m-%d"))

    @mcp.tool(name="fetch_daily_summaries")
    def mcp_fetch_daily_summaries(start_date, end_date):
        """Fetch Garmin daily summaries for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format.
            end_date: End date in YYYY-MM-DD format.
        """
        parsed_start = parse_required_date(start_date, "start_date")
        parsed_end = parse_required_date(end_date, "end_date")
        if parsed_start > parsed_end:
            raise ValueError("start_date must be before or equal to end_date.")

        start_date_str = parsed_start.strftime("%Y-%m-%d")
        end_date_str = parsed_end.strftime("%Y-%m-%d")

        cached_data = load_cache("summary", start_date_str, end_date_str)
        if cached_data:
            return cached_data

        all_dates = build_descending_date_strings(parsed_start, parsed_end)
        cached_summaries = load_cached_summaries_map(parsed_start, parsed_end)
        missing_dates = [date_str for date_str in all_dates if date_str not in cached_summaries]

        fetched_summaries = {}
        if missing_dates:
            client = get_garmin_client()
            for date_str in missing_dates:
                fetched_summaries[date_str] = fetch_daily_summary(client, date_str)
        else:
            client = None

        daily_summaries = [cached_summaries.get(date_str) or fetched_summaries.get(date_str) for date_str in all_dates]
        daily_summaries = [summary for summary in daily_summaries if summary is not None]

        cached_activities, covered_ranges = load_cached_activities(parsed_start, parsed_end)
        missing_activity_dates = get_uncovered_dates(parsed_start, parsed_end, covered_ranges)

        fetched_activities = []
        if missing_activity_dates:
            if client is None:
                client = get_garmin_client()
            for range_start, range_end in dates_to_ranges(missing_activity_dates):
                fetched_activities.extend(
                    fetch_activities(
                        client=client,
                        start_date=range_start.strftime("%Y-%m-%d"),
                        end_date=range_end.strftime("%Y-%m-%d"),
                    )
                )

        combined_activities = cached_activities + fetched_activities
        deduped_activities = []
        seen_activity_keys = set()
        for activity in combined_activities:
            key = (
                activity.get("datetime"),
                activity.get("activity_type"),
                activity.get("duration"),
                activity.get("distance"),
            )
            if key in seen_activity_keys:
                continue
            seen_activity_keys.add(key)
            deduped_activities.append(activity)

        activities = deduped_activities
        activity_counts = count_activities_by_date(activities)

        for summary in daily_summaries:
            summary["numberOfActivities"] = activity_counts.get(summary["date"], 0)

        response_data = {"summaries": format_summaries_for_output(daily_summaries)}
        save_cache("summary", start_date_str, end_date_str, response_data)
        return response_data

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

        start_date_str = parsed_start.strftime("%Y-%m-%d")
        end_date_str = parsed_end.strftime("%Y-%m-%d")

        cached_data = load_cache("activities", start_date_str, end_date_str)
        if cached_data:
            return cached_data

        cached_activities, covered_ranges = load_cached_activities(parsed_start, parsed_end)
        missing_activity_dates = get_uncovered_dates(parsed_start, parsed_end, covered_ranges)

        fetched_activities = []
        if missing_activity_dates:
            client = get_garmin_client()
            for range_start, range_end in dates_to_ranges(missing_activity_dates):
                fetched_activities.extend(
                    fetch_activities(
                        client=client,
                        start_date=range_start.strftime("%Y-%m-%d"),
                        end_date=range_end.strftime("%Y-%m-%d"),
                    )
                )

        formatted_cached_activities = []
        for activity in cached_activities:
            if isinstance(activity.get("duration"), str) and isinstance(activity.get("distance"), str):
                formatted_cached_activities.append(activity)
            else:
                formatted_cached_activities.append(format_activities_for_output([activity])[0])

        formatted_fetched_activities = format_activities_for_output(fetched_activities)

        activities = []
        seen_activity_keys = set()
        for activity in formatted_cached_activities + formatted_fetched_activities:
            key = (
                activity.get("datetime"),
                activity.get("activity_type"),
                activity.get("duration"),
                activity.get("distance"),
            )
            if key in seen_activity_keys:
                continue
            seen_activity_keys.add(key)
            activities.append(activity)

        response_data = {
            "activities": activities,
            "hr_zone_percentages": {
                "garmin": GARMIN_ZONE_RANGES,
                "olympiatoppen": OLYMPIATOPPEN_ZONE_RANGES,
            },
        }
        save_cache("activities", start_date_str, end_date_str, response_data)
        return response_data

    return mcp


def run_mcp_server():
    """Run MCP server exposing Garmin fetch tools over stdio."""
    mcp_server = create_mcp_server()
    log_info("Garmin Connect Log MCP server")
    log_info("=" * 50)
    log_info("Starting MCP server over stdio")
    log_startup_configuration_sources()
    log_info("Tools:")
    log_info("  fetch_daily_summary(date)")
    log_info("  fetch_daily_summaries(start_date, end_date)")
    log_info("  fetch_activities(start_date, end_date)")
    mcp_server.run()


if __name__ == "__main__":
    run_mcp_server()
