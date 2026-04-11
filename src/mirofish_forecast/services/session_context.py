"""Market session detection — knows when futures are trading and in what session.

Provides session classification, time-to-close, and temporal reference resolution
for natural language queries like "Monday" or "tomorrow".
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mirofish_forecast.config import constants
from mirofish_forecast.models.base import MiroFishBaseModel

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class SessionInfo(MiroFishBaseModel):
    """Current market session information."""

    session_type: str  # "rth", "overnight", "closed", "pre_market", "post_market"
    is_rth_open: bool
    is_tradeable: bool  # True for RTH + overnight (Globex is open)
    current_time_et: str  # Current time in ET as string
    current_date_et: str  # Current date in ET as string
    day_of_week: str  # "Monday", "Tuesday", etc.
    minutes_to_rth_open: int | None = None
    minutes_to_rth_close: int | None = None
    next_rth_open: str | None = None
    next_rth_close: str | None = None
    is_holiday: bool = False
    is_weekend: bool = False
    session_label: str = ""  # Human-readable: "RTH Open", etc.


def get_session_info(now: datetime | None = None) -> SessionInfo:
    """Determine the current market session.

    Args:
        now: Override current time (for testing). Must be tz-aware or naive UTconstants.

    Returns:
        SessionInfo with full session classification
    """
    if now is None:
        now = datetime.now(ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
    else:
        now = now.astimezone(ET)

    current_date_str = now.strftime("%Y-%m-%d")
    day_of_week = now.strftime("%A")
    is_weekend = now.weekday() >= 5
    is_holiday = current_date_str in constants.US_MARKET_HOLIDAYS_2026

    rth_open = now.replace(
        hour=constants.RTH_OPEN_HOUR,
        minute=constants.RTH_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    rth_close = now.replace(
        hour=constants.RTH_CLOSE_HOUR,
        minute=constants.RTH_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )

    # Determine session type
    if is_weekend or is_holiday:
        session_type = constants.SESSION_CLOSED
        is_rth_open = False
        # Globex opens Sunday 6 PM ET
        is_tradeable = not is_weekend or (now.weekday() == 6 and now.hour >= 18)
    elif rth_open <= now < rth_close:
        session_type = constants.SESSION_RTH
        is_rth_open = True
        is_tradeable = True
    elif now.hour >= 8 and now < rth_open:
        session_type = constants.SESSION_PRE_MARKET
        is_rth_open = False
        is_tradeable = True
    elif now >= rth_close and now.hour < 17:
        session_type = constants.SESSION_POST_MARKET
        is_rth_open = False
        is_tradeable = True
    elif now.hour >= 18 or now.hour < 8:
        session_type = constants.SESSION_OVERNIGHT
        is_rth_open = False
        is_tradeable = True
    else:
        # Daily halt: 5:00 PM – 6:00 PM ET
        session_type = constants.SESSION_CLOSED
        is_rth_open = False
        is_tradeable = False

    # Compute next RTH open/close
    next_open = _next_rth_open(now)
    if is_rth_open:
        next_close = rth_close
        minutes_to_close = int((rth_close - now).total_seconds() / 60)
        minutes_to_open = None
    else:
        next_close = None
        minutes_to_close = None
        minutes_to_open = int((next_open - now).total_seconds() / 60) if next_open else None

    # Session label
    labels: dict[str, str] = {
        constants.SESSION_RTH: "RTH Open",
        constants.SESSION_OVERNIGHT: "Overnight Session",
        constants.SESSION_PRE_MARKET: "Pre-Market",
        constants.SESSION_POST_MARKET: "Post-Market",
        constants.SESSION_CLOSED: "Daily Halt",
    }
    if is_weekend:
        labels[constants.SESSION_CLOSED] = "Weekend — Market Closed"
    if is_holiday:
        labels[constants.SESSION_CLOSED] = "Holiday — Market Closed"

    return SessionInfo(
        session_type=session_type,
        is_rth_open=is_rth_open,
        is_tradeable=is_tradeable,
        current_time_et=now.strftime("%I:%M %p ET"),
        current_date_et=current_date_str,
        day_of_week=day_of_week,
        minutes_to_rth_open=minutes_to_open,
        minutes_to_rth_close=minutes_to_close,
        next_rth_open=(next_open.strftime("%A %I:%M %p ET") if next_open else None),
        next_rth_close=(next_close.strftime("%I:%M %p ET") if next_close else None),
        is_holiday=is_holiday,
        is_weekend=is_weekend,
        session_label=labels.get(session_type, session_type),
    )


def _next_rth_open(now: datetime) -> datetime | None:
    """Find the next RTH open from the given time."""
    today_open = now.replace(
        hour=constants.RTH_OPEN_HOUR,
        minute=constants.RTH_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    if now < today_open and now.weekday() < 5:
        date_str = now.strftime("%Y-%m-%d")
        if date_str not in constants.US_MARKET_HOLIDAYS_2026:
            return today_open

    # Find the next business day
    candidate = now + timedelta(days=1)
    for _ in range(7):
        candidate = candidate.replace(
            hour=constants.RTH_OPEN_HOUR,
            minute=constants.RTH_OPEN_MINUTE,
            second=0,
            microsecond=0,
        )
        date_str = candidate.strftime("%Y-%m-%d")
        if candidate.weekday() < 5 and date_str not in constants.US_MARKET_HOLIDAYS_2026:
            return candidate
        candidate += timedelta(days=1)

    return None


def resolve_temporal_reference(
    reference: str,
    now: datetime | None = None,
) -> dict[str, int | str | None]:
    """Resolve natural language temporal references to forecast params.

    Args:
        reference: The raw query text (or extracted temporal phrase)
        now: Override current time for testing

    Returns:
        Dict with 'horizon_minutes', 'target_session', 'session_label',
        'target_date' keys.
    """
    if now is None:
        now = datetime.now(ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
    else:
        now = now.astimezone(ET)

    ref_lower = reference.lower()
    session = get_session_info(now)

    # Day-of-week references
    day_map: dict[str, int] = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "tues": 1,
        "thurs": 3,
    }

    for day_word, target_weekday in day_map.items():
        if day_word in ref_lower:
            target_date = _next_weekday(now, target_weekday)
            target_close = target_date.replace(
                hour=constants.RTH_CLOSE_HOUR,
                minute=constants.RTH_CLOSE_MINUTE,
                second=0,
                microsecond=0,
            )

            # If we're in the target day's RTH, horizon = remaining
            if now.date() == target_date.date() and session.is_rth_open:
                horizon = int((target_close - now).total_seconds() / 60)
            else:
                horizon = constants.RTH_DURATION_MINUTES

            day_name = target_date.strftime("%A")
            return {
                "horizon_minutes": horizon,
                "target_session": (f"{target_date.strftime('%A %b %d')} RTH"),
                "session_label": (f"{day_name}'s RTH session (9:30 AM – 4:00 PM ET)"),
                "target_date": target_date.strftime("%Y-%m-%d"),
            }

    # "end of day" / "close" / "by close"
    eod_phrases = (
        "end of day",
        "by close",
        "eod",
        "into the close",
    )
    if any(phrase in ref_lower for phrase in eod_phrases):
        if session.is_rth_open:
            rth_close = now.replace(
                hour=constants.RTH_CLOSE_HOUR,
                minute=constants.RTH_CLOSE_MINUTE,
                second=0,
            )
            horizon = int((rth_close - now).total_seconds() / 60)
            return {
                "horizon_minutes": max(horizon, 30),
                "target_session": "Today's close",
                "session_label": ("Into today's RTH close (4:00 PM ET)"),
                "target_date": now.strftime("%Y-%m-%d"),
            }
        else:
            next_open = _next_rth_open(now)
            day_label = next_open.strftime("%A") if next_open else "Unknown"
            return {
                "horizon_minutes": constants.RTH_DURATION_MINUTES,
                "target_session": "Next RTH close",
                "session_label": (f"Next RTH close ({day_label} 4:00 PM ET)"),
                "target_date": (next_open.strftime("%Y-%m-%d") if next_open else None),
            }

    # "today" reference
    if "today" in ref_lower:
        if session.is_rth_open:
            rth_close = now.replace(
                hour=constants.RTH_CLOSE_HOUR,
                minute=constants.RTH_CLOSE_MINUTE,
                second=0,
            )
            horizon = int((rth_close - now).total_seconds() / 60)
            return {
                "horizon_minutes": max(horizon, 30),
                "target_session": "Today's remaining RTH",
                "session_label": "Today's RTH (closes at 4:00 PM ET)",
                "target_date": now.strftime("%Y-%m-%d"),
            }
        else:
            return {
                "horizon_minutes": constants.RTH_DURATION_MINUTES,
                "target_session": ("Today's RTH" if now.weekday() < 5 else "Next RTH session"),
                "session_label": ("Today's RTH session (9:30 AM – 4:00 PM ET)"),
                "target_date": now.strftime("%Y-%m-%d"),
            }

    # "tomorrow" reference
    if "tomorrow" in ref_lower:
        tomorrow = now + timedelta(days=1)
        while tomorrow.weekday() >= 5:
            tomorrow += timedelta(days=1)
        day_name = tomorrow.strftime("%A")
        return {
            "horizon_minutes": constants.RTH_DURATION_MINUTES,
            "target_session": (f"{tomorrow.strftime('%A %b %d')} RTH"),
            "session_label": (f"Tomorrow's RTH session ({day_name}, 9:30 AM – 4:00 PM ET)"),
            "target_date": tomorrow.strftime("%Y-%m-%d"),
        }

    # "this week" reference
    if "this week" in ref_lower or "rest of the week" in ref_lower:
        days_left = 5 - now.weekday()
        if days_left <= 0:
            days_left = 5
        return {
            "horizon_minutes": constants.RTH_DURATION_MINUTES * max(days_left, 1),
            "target_session": (f"This week ({days_left} trading days remaining)"),
            "session_label": "Rest of this week's RTH sessions",
            "target_date": None,
        }

    # No temporal reference detected
    return {
        "horizon_minutes": None,
        "target_session": None,
        "session_label": None,
        "target_date": None,
    }


def _next_weekday(now: datetime, target_weekday: int) -> datetime:
    """Find the next occurrence of a given weekday (0=Mon, 4=Fri)."""
    days_ahead = target_weekday - now.weekday()
    if days_ahead <= 0:
        if days_ahead == 0:
            rth_close = now.replace(
                hour=constants.RTH_CLOSE_HOUR,
                minute=constants.RTH_CLOSE_MINUTE,
                second=0,
            )
            if now < rth_close:
                return now
        days_ahead += 7
    return now + timedelta(days=days_ahead)
