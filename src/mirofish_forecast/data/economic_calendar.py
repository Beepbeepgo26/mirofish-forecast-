"""Economic calendar — FOMC, CPI, NFP, and other market-moving events.

Three data sources, layered:
1. Static FOMC schedule (JSON file, updated annually)
2. FRED releases/dates API (existing API key)
3. finvizfinance Calendar() (consensus estimates)
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import EconomicEvent

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class EconomicCalendarClient:
    """Fetches and assembles economic calendar events."""

    def __init__(self, settings: Settings, cache: CacheClient) -> None:
        self._settings = settings
        self._cache = cache
        self._fomc_schedule = self._load_fomc_schedule()

    def get_events_today(self) -> list[EconomicEvent]:
        """Get all economic events scheduled for today."""
        cache_key = "calendar:today"
        cached = self._cache.get(cache_key)
        if cached:
            try:
                return [EconomicEvent.model_validate(e) for e in json.loads(cached)]
            except Exception:
                pass

        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        events: list[EconomicEvent] = []

        # Check FOMC
        fomc_event = self._check_fomc(today_str, now)
        if fomc_event:
            events.append(fomc_event)

        # Check FRED releases
        fred_events = self._check_fred_releases(today_str, now)
        events.extend(fred_events)

        # Enrich with consensus
        events = self._enrich_with_consensus(events)

        # Mark all as today
        events = [e.model_copy(update={"is_today": True}) for e in events]

        self._cache.set(
            cache_key,
            json.dumps([e.model_dump() for e in events]),
            constants.CACHE_TTL_CALENDAR_TODAY,
        )
        return events

    def get_events_this_week(self) -> list[EconomicEvent]:
        """Get all economic events scheduled for Mon–Fri this week."""
        cache_key = "calendar:week"
        cached = self._cache.get(cache_key)
        if cached:
            try:
                return [EconomicEvent.model_validate(e) for e in json.loads(cached)]
            except Exception:
                pass

        now = datetime.now(ET)
        monday = now - timedelta(days=now.weekday())
        events: list[EconomicEvent] = []

        for day_offset in range(5):
            day = monday + timedelta(days=day_offset)
            day_str = day.strftime("%Y-%m-%d")

            fomc = self._check_fomc(day_str, now)
            if fomc:
                events.append(fomc)

            fred = self._check_fred_releases(day_str, now)
            events.extend(fred)

        today_str = now.strftime("%Y-%m-%d")
        updated: list[EconomicEvent] = []
        for e in events:
            updates: dict = {"is_this_week": True}
            if e.date == today_str:
                updates["is_today"] = True
            updated.append(e.model_copy(update=updates))

        updated = self._enrich_with_consensus(updated)
        updated.sort(key=lambda e: e.date)

        self._cache.set(
            cache_key,
            json.dumps([e.model_dump() for e in updated]),
            constants.CACHE_TTL_CALENDAR_WEEK,
        )
        return updated

    # ---------------------------------------------------------------
    # FOMC Schedule (static JSON)
    # ---------------------------------------------------------------

    def _load_fomc_schedule(self) -> list[dict]:
        """Load FOMC schedule from static JSON file."""
        try:
            json_path = os.path.join(
                os.path.dirname(__file__),
                "static",
                "fomc_schedule.json",
            )
            with open(json_path) as f:
                data = json.load(f)
            return data.get("meetings", [])
        except Exception:
            logger.warning("Could not load FOMC schedule JSON", exc_info=True)
            return [
                {
                    "statement_date": d,
                    "press_conference": True,
                    "sep": d in constants.FOMC_SEP_DATES_2026,
                }
                for d in constants.FOMC_DATES_2026
            ]

    def _check_fomc(self, date_str: str, now: datetime) -> EconomicEvent | None:
        """Check if the given date is an FOMC meeting day."""
        for meeting in self._fomc_schedule:
            if meeting.get("statement_date") == date_str:
                statement_time = datetime.strptime(f"{date_str} 14:00", "%Y-%m-%d %H:%M").replace(
                    tzinfo=ET
                )
                hours_until = (statement_time - now).total_seconds() / 3600
                sep_note = (
                    " + Summary of Economic Projections (dot plot)" if meeting.get("sep") else ""
                )
                return EconomicEvent(
                    name="FOMC",
                    full_name=f"FOMC Rate Decision{sep_note}",
                    date=date_str,
                    time="14:00 ET",
                    impact="critical",
                    hours_until=round(hours_until, 1),
                    has_press_conference=meeting.get("press_conference", True),
                    has_sep=meeting.get("sep", False),
                    note=meeting.get("note", ""),
                )

            meeting_dates = meeting.get("dates", [])
            if len(meeting_dates) > 1 and meeting_dates[0] == date_str:
                return EconomicEvent(
                    name="FOMC",
                    full_name="FOMC Meeting Day 1 (no statement today)",
                    date=date_str,
                    time=None,
                    impact="medium",
                    note="Two-day meeting — statement tomorrow",
                )

        return None

    # ---------------------------------------------------------------
    # FRED Releases API
    # ---------------------------------------------------------------

    def _check_fred_releases(self, date_str: str, now: datetime) -> list[EconomicEvent]:
        """Check FRED for scheduled releases on the given date."""
        events: list[EconomicEvent] = []

        for event_key, config in constants.FRED_RELEASE_IDS.items():
            try:
                resp = requests.get(
                    "https://api.stlouisfed.org/fred/release/dates",
                    params={
                        "api_key": self._settings.fred_api_key,
                        "file_type": "json",
                        "release_id": config["release_id"],
                        "realtime_start": date_str,
                        "realtime_end": date_str,
                        "include_release_dates_with_no_data": "true",
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                release_dates = data.get("release_dates", [])

                for rd in release_dates:
                    if rd.get("date") == date_str:
                        hour, minute = self._parse_time(config["typical_time"])
                        release_time = datetime.strptime(
                            f"{date_str} {hour}:{minute:02d}",
                            "%Y-%m-%d %H:%M",
                        ).replace(tzinfo=ET)
                        hours_until = (release_time - now).total_seconds() / 3600
                        events.append(
                            EconomicEvent(
                                name=event_key,
                                full_name=config["name"],
                                date=date_str,
                                time=config["typical_time"],
                                impact=config["impact"],
                                hours_until=round(hours_until, 1),
                            )
                        )
                        break
            except Exception:
                logger.debug(
                    f"FRED release check failed for {event_key}",
                    exc_info=True,
                )

        return events

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """Parse '08:30 ET' to (8, 30)."""
        parts = time_str.replace(" ET", "").split(":")
        return int(parts[0]), int(parts[1])

    # ---------------------------------------------------------------
    # Consensus Enrichment (finvizfinance)
    # ---------------------------------------------------------------

    def _enrich_with_consensus(self, events: list[EconomicEvent]) -> list[EconomicEvent]:
        """Try to add consensus and prior values from finvizfinance."""
        if not events:
            return events

        try:
            from finvizfinance.calendar import Calendar

            cal = Calendar()
            df = cal.calendar()

            if df is None or df.empty:
                return events

            name_matches: dict[str, list[str]] = {
                "CPI": ["Consumer Price Index", "CPI"],
                "NFP": ["Nonfarm Payrolls", "Employment"],
                "GDP": ["GDP", "Gross Domestic Product"],
                "PPI": ["Producer Price Index", "PPI"],
                "PCE": ["PCE", "Personal Consumption"],
                "RETAIL_SALES": ["Retail Sales"],
                "ISM_MFG": ["ISM Manufacturing", "ISM Mfg"],
            }

            enriched: list[EconomicEvent] = []
            for event in events:
                consensus = None
                prior = None
                search_terms = name_matches.get(event.name, [event.full_name])
                for _, row in df.iterrows():
                    release_name = str(row.get("Release", ""))
                    if any(t.lower() in release_name.lower() for t in search_terms):
                        c = str(row.get("Consensus", ""))
                        p = str(row.get("Prior", ""))
                        consensus = None if c in ("", "nan") else c
                        prior = None if p in ("", "nan") else p
                        break
                enriched.append(
                    event.model_copy(
                        update={
                            "consensus": consensus,
                            "prior": prior,
                        }
                    )
                )
            return enriched

        except Exception:
            logger.debug(
                "finvizfinance consensus enrichment failed",
                exc_info=True,
            )
            return events
