"""Local-time update windows, with solar times calculated offline by Astral.

ZIP 84105 approximate coordinates: https://api.zippopotam.us/us/84105
Astral reference: https://astral.readthedocs.io/en/latest/
Sunrise/sunset assume an unobstructed horizon, not local mountain shadows.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astral import Observer
from astral.sun import sunrise, sunset

DEFAULT_SCHEDULE = {
    "enabled": True,
    "timezone": "America/Denver",
    "latitude": 40.7372,
    "longitude": -111.8581,
    "start": {"mode": "sunrise", "offset_minutes": 0, "time": "07:00"},
    "end": {"mode": "sunset", "offset_minutes": 60, "time": "20:00"},
}
UTC = timezone.utc


def validate_schedule(patch, current=None):
    """Merge a partial schedule without mutating defaults or caller settings."""
    result = deepcopy(DEFAULT_SCHEDULE)
    for update in (current or {}, patch):
        if not isinstance(update, dict) or set(update) - set(DEFAULT_SCHEDULE):
            raise ValueError("Unknown update schedule setting")
        for key, value in update.items():
            if key in ("start", "end"):
                if not isinstance(value, dict) or set(value) - {"mode", "offset_minutes", "time"}:
                    raise ValueError("Unknown schedule boundary setting")
                result[key].update(value)
            else:
                result[key] = value
    if type(result["enabled"]) is not bool:
        raise ValueError("Schedule enabled must be true or false")
    for key, limit in (("latitude", 90), ("longitude", 180)):
        value = result[key]
        if type(value) not in (int, float) or not -limit <= value <= limit or not math.isfinite(value):
            raise ValueError(f"Invalid schedule {key}")
        result[key] = float(value)
    zone = result["timezone"]
    if not isinstance(zone, str) or not zone or len(zone) > 100:
        raise ValueError("Choose an IANA timezone")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown schedule timezone") from exc
    for key in ("start", "end"):
        boundary = result[key]
        if boundary["mode"] not in ("sunrise", "sunset", "fixed"):
            raise ValueError("Choose sunrise, sunset, or a fixed time")
        offset = boundary["offset_minutes"]
        if type(offset) is not int or not -180 <= offset <= 180:
            raise ValueError("Solar offsets must be whole minutes between -180 and 180")
        clock = boundary["time"]
        if not isinstance(clock, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
            raise ValueError("Clock times must use HH:MM in 24-hour time")
    return result


@lru_cache(maxsize=4096)
def solar_times(latitude, longitude, local_date, timezone_name):
    """Return each event independently; polar days/nights may lack either."""
    observer = Observer(latitude=latitude, longitude=longitude)
    zone = ZoneInfo(timezone_name)
    result = {}
    for name, calculate in (("sunrise", sunrise), ("sunset", sunset)):
        try:
            result[name] = calculate(observer, date=local_date, tzinfo=zone)
        except ValueError:
            result[name] = None
    return result


def fixed_time(local_date, clock, zone):
    # fold=0 selects the first occurrence of an ambiguous autumn time.
    # The UTC round-trip moves a nonexistent spring time forward across the
    # DST gap (02:30 becomes 03:30), never inventing a nonexistent instant.
    candidate = datetime.combine(local_date, time.fromisoformat(clock), tzinfo=zone)
    return candidate.astimezone(UTC).astimezone(zone)


def boundary_time(boundary, local_date, sun, zone):
    event = sun.get(boundary["mode"])
    if boundary["mode"] == "fixed" or event is None:
        # The clock field is a complete fallback, not another solar offset.
        return fixed_time(local_date, boundary["time"], zone)
    # An offset is elapsed time, including when it crosses a DST transition.
    return (event.astimezone(UTC) + timedelta(minutes=boundary["offset_minutes"])).astimezone(zone)


def _boundary_description(boundary):
    if boundary["mode"] == "fixed":
        return boundary["time"]
    offset = boundary["offset_minutes"]
    if not offset:
        return boundary["mode"]
    return f'{abs(offset)} min {"after" if offset > 0 else "before"} {boundary["mode"]}'


def schedule_state(settings_schedule, now):
    """Return the current window and its next transition as ISO timestamps.

    Start is inclusive, end exclusive. Event ordering naturally supports
    windows crossing midnight and offsets landing on the previous/next date.
    Equal boundaries mean all-day updates. A disabled schedule is always active.
    Inactive sleep_seconds is rounded up and capped at one day; active is zero.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Schedule time must include a timezone")
    settings = validate_schedule(settings_schedule)
    zone = ZoneInfo(settings["timezone"])
    local_now = now.astimezone(zone)
    today = local_now.date()

    def sun_for(day):
        return solar_times(settings["latitude"], settings["longitude"], day, settings["timezone"])

    today_sun = sun_for(today)
    result = dict(active=True, next_change=None,
                  sunrise=today_sun["sunrise"].isoformat() if today_sun["sunrise"] else None,
                  sunset=today_sun["sunset"].isoformat() if today_sun["sunset"] else None,
                  resume_at=None, sleep_seconds=0)
    if not settings["enabled"]:
        return {**result, "description": "Updates all day; overnight pause is off."}

    # Include previous dates because a solar offset may cross midnight. Each
    # event sets a state; no naive same-day comparison or fixed 24-hour shifts.
    # Six days covers the next daily start/end plus all allowed +/-3h offsets.
    events = {}
    for delta in range(-2, 4):
        day = today + timedelta(days=delta)
        sun = sun_for(day)
        for key, active in (("end", False), ("start", True)):
            event = boundary_time(settings[key], day, sun, zone)
            # Start wins coincident boundaries: equality represents all day.
            stamp = event.timestamp()
            if stamp not in events or active:
                events[stamp] = (event, active)
    ordered = sorted(events.items())
    now_stamp = now.timestamp()
    past = [(stamp, event, active) for stamp, (event, active) in ordered if stamp <= now_stamp]
    active = past[-1][2]
    upcoming = [(stamp, event, state) for stamp, (event, state) in ordered
                if stamp > now_stamp and state != active]
    next_event = upcoming[0][1] if upcoming else None
    result["active"] = active
    result["next_change"] = next_event.isoformat() if next_event else None
    if not active and next_event:
        result["resume_at"] = next_event.isoformat()
        result["sleep_seconds"] = min(86400, max(1, math.ceil(next_event.timestamp() - now_stamp)))
    description = f'Updates from {_boundary_description(settings["start"])} to {_boundary_description(settings["end"])}.'
    if not upcoming and active:
        description = "Updates all day; the start and end currently coincide."
    unavailable = [key for key in ("start", "end")
                   if settings[key]["mode"] != "fixed" and today_sun[settings[key]["mode"]] is None]
    if unavailable:
        clocks = ", ".join(f'{key} {settings[key]["time"]}' for key in unavailable)
        description += f" Solar event unavailable; using fixed fallback: {clocks}."
    result["description"] = description
    return result
