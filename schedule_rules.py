"""Shared date/time rules for the alarm.

Kept separate from alarm_app.py so play_alarm.py can apply exactly the same
rules when it is run standalone, and so the timing logic can be regression
tested without starting the web server.

All datetimes handled here are timezone-aware Beijing time (UTC+8), matching
the default of the `time` values shown in the dashboard.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

LOGGER = logging.getLogger("alarm.rules")

TZ = timezone(timedelta(hours=8))

# A scheduled playback may still run this long after its configured minute, so
# that a late wake-up, a stalled prepare or a finished retry still rings.
CATCH_UP_MINUTES = 15

# After a failed prepare, wait this long before trying again inside the window.
PREPARE_RETRY_MINUTES = 10

# How far ahead next_schedule() looks for a matching day (~1 year).
LOOKAHEAD_DAYS = 370

DEFAULT_PLAY_TIME = "07:30"
TIME_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

_CALENDAR_WARNING_YEAR = None


def now():
    """Current Beijing time."""
    return datetime.now(TZ)


def play_time_of(config):
    """Return (hour, minute) from config, falling back to the default."""
    value = config.get("play_time") or DEFAULT_PLAY_TIME
    if not TIME_PATTERN.fullmatch(str(value)):
        value = DEFAULT_PLAY_TIME
    hour, minute = str(value).split(":")
    return int(hour), int(minute)


def prepare_lead(config):
    """How long before the alarm remote content is fetched and converted."""
    try:
        minutes = int(config.get("prepare_lead_minutes", 30))
    except (TypeError, ValueError):
        minutes = 30
    return max(0, min(minutes, 12 * 60))


def workday(day):
    """is_workday() with its data-coverage limit handled.

    chinesecalendar only ships data between 2004 and the last published year
    (2026 while this was written) and raises NotImplementedError beyond that.
    Crashing there would stop the scheduler and break the status API for good,
    so fall back to a plain Monday-Friday rule and say so in the log.
    """
    global _CALENDAR_WARNING_YEAR
    from chinese_calendar import is_workday  # imported late: heavy module
    try:
        return is_workday(day)
    except NotImplementedError:
        if _CALENDAR_WARNING_YEAR != day.year:
            _CALENDAR_WARNING_YEAR = day.year
            LOGGER.warning(
                "%s: no statutory holiday data for %s, falling back to Mon-Fri "
                "(update the chinesecalendar dependency)",
                day.isoformat(), day.year,
            )
        return day.weekday() < 5


def eligible_on(day, config):
    """True when an alarm is scheduled on the calendar day of `day`."""
    iso = day.date().isoformat()
    if iso in (config.get("exclude_dates") or []):
        return False
    if iso in (config.get("include_dates") or []):
        return True
    mode = config.get("schedule_mode", "workdays")
    if mode == "workdays":
        return workday(day.date())
    if mode == "daily":
        return True
    if mode == "weekdays":
        return day.weekday() in (config.get("weekdays") or [])
    if mode == "dates":
        return False
    raise ValueError(f"Unknown schedule mode: {mode}")


def next_schedule(from_dt, config):
    """Return (alarm_at, prepare_at) for the next scheduled alarm.

    `prepare_at` is None for local files, which need no download step.
    """
    if not config.get("enabled", True):
        return None, None
    hour, minute = play_time_of(config)
    for offset in range(LOOKAHEAD_DAYS):
        day = from_dt + timedelta(days=offset)
        alarm_at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # >= keeps the current minute usable, so a retry inside the same minute works.
        if alarm_at >= from_dt and eligible_on(alarm_at, config):
            prepare_at = None
            if config.get("source_type", "latest") != "local":
                prepare_at = alarm_at - timedelta(minutes=prepare_lead(config))
            return alarm_at, prepare_at
    return None, None


def previous_alarm(from_dt, config):
    """Return the latest alarm at or before `from_dt`, or None.

    Scans backwards and only considers alarms whose time has already arrived,
    so this is a genuine "most recent occurrence" lookup rather than "the
    nearest eligible day". None means alarms are disabled or the latest
    occurrence is more than LOOKAHEAD_DAYS old, which callers use to tell a
    just-fired alarm from a stale one.
    """
    if not config.get("enabled", True):
        return None
    hour, minute = play_time_of(config)
    for offset in range(LOOKAHEAD_DAYS):
        day = from_dt - timedelta(days=offset)
        if not eligible_on(day, config):
            continue
        alarm_at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if alarm_at <= from_dt:
            return alarm_at
        # Eligible day whose alarm time is still ahead (offset == 0): the latest
        # occurrence therefore belongs to an earlier day, so keep scanning.
    return None
