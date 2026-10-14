from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import schedule


class ScheduleTests(unittest.TestCase):
    zone = ZoneInfo("America/Denver")

    def now(self, value):
        return datetime.fromisoformat(value).replace(tzinfo=self.zone)

    def fixed(self, start="07:00", end="20:00"):
        return schedule.validate_schedule({"start": {"mode": "fixed", "time": start},
                                           "end": {"mode": "fixed", "time": end}})

    def test_default_84105_solar_window_and_exact_boundaries(self):
        settings = schedule.validate_schedule({})
        now = self.now("2026-10-14T12:00:00")
        state = schedule.schedule_state(settings, now)
        self.assertTrue(state["active"])
        self.assertEqual(state["sleep_seconds"], 0)
        rise = datetime.fromisoformat(state["sunrise"])
        setting = datetime.fromisoformat(state["sunset"])
        self.assertTrue(7 <= rise.hour <= 8)
        self.assertTrue(18 <= setting.hour <= 19)
        end = setting + timedelta(hours=1)
        self.assertEqual(datetime.fromisoformat(state["next_change"]), end)
        self.assertTrue(schedule.schedule_state(settings, rise)["active"])
        self.assertFalse(schedule.schedule_state(settings, rise - timedelta(microseconds=1))["active"])
        self.assertTrue(schedule.schedule_state(settings, end - timedelta(microseconds=1))["active"])
        asleep = schedule.schedule_state(settings, end)
        self.assertFalse(asleep["active"])
        resume = datetime.fromisoformat(asleep["resume_at"])
        self.assertEqual(resume.date(), now.date() + timedelta(days=1))
        self.assertTrue(0 < asleep["sleep_seconds"] <= 86400)

    def test_fixed_window_crosses_midnight(self):
        settings = self.fixed("22:00", "06:00")
        for clock, expected in (("00:30", True), ("05:59", True), ("06:00", False),
                                ("12:00", False), ("21:59", False), ("22:00", True)):
            with self.subTest(clock=clock):
                state = schedule.schedule_state(settings, self.now(f"2026-10-14T{clock}:00"))
                self.assertEqual(state["active"], expected)
        asleep = schedule.schedule_state(settings, self.now("2026-10-14T12:00:00"))
        self.assertEqual(asleep["sleep_seconds"], 10 * 3600)
        self.assertEqual(datetime.fromisoformat(asleep["resume_at"]).hour, 22)

    def test_previous_date_offset_and_next_date_end(self):
        # Synthetic early sunrise makes a -180 minute offset land yesterday.
        def early_sun(latitude, longitude, day, timezone_name):
            zone = ZoneInfo(timezone_name)
            return {"sunrise": datetime(day.year, day.month, day.day, 1, tzinfo=zone),
                    "sunset": datetime(day.year, day.month, day.day, 23, tzinfo=zone)}
        settings = schedule.validate_schedule({"start": {"offset_minutes": -180},
                                              "end": {"mode": "fixed", "time": "02:00"}})
        with patch.object(schedule, "solar_times", side_effect=early_sun):
            self.assertTrue(schedule.schedule_state(settings, self.now("2026-10-14T00:30:00"))["active"])
            asleep = schedule.schedule_state(settings, self.now("2026-10-14T02:00:00"))
            self.assertFalse(asleep["active"])
            self.assertEqual(datetime.fromisoformat(asleep["resume_at"]), self.now("2026-10-14T22:00:00"))
            settings = schedule.validate_schedule({"start": {"mode": "fixed", "time": "10:00"},
                                                  "end": {"mode": "sunset", "offset_minutes": 180}})
            self.assertTrue(schedule.schedule_state(settings, self.now("2026-10-14T01:00:00"))["active"])
            self.assertFalse(schedule.schedule_state(settings, self.now("2026-10-14T02:00:00"))["active"])

    def test_dst_uses_elapsed_seconds_not_wall_clock_subtraction(self):
        settings = self.fixed("07:00", "20:00")
        spring = schedule.schedule_state(settings, self.now("2026-03-08T01:00:00"))
        self.assertEqual(spring["sleep_seconds"], 5 * 3600)
        autumn = schedule.schedule_state(settings, self.now("2026-11-01T00:00:00"))
        self.assertEqual(autumn["sleep_seconds"], 8 * 3600)
        # Nonexistent fixed times advance through the gap; ambiguous autumn
        # boundaries use the first occurrence without re-entering the window.
        missing = self.fixed("02:30", "20:00")
        state = schedule.schedule_state(missing, self.now("2026-03-08T01:00:00"))
        self.assertEqual(datetime.fromisoformat(state["resume_at"]).hour, 3)
        repeated = self.fixed("00:00", "01:30")
        now = self.now("2026-11-01T01:15:00").replace(fold=1)
        self.assertFalse(schedule.schedule_state(repeated, now)["active"])

    def test_polar_fallback_uses_configured_clock_without_solar_offset(self):
        settings = schedule.validate_schedule({"latitude": 89.0, "longitude": 0,
                                              "timezone": "UTC"})
        state = schedule.schedule_state(settings, datetime(2026, 6, 21, 12, tzinfo=timezone.utc))
        self.assertTrue(state["active"])
        self.assertIsNone(state["sunrise"])
        self.assertIsNone(state["sunset"])
        self.assertEqual(datetime.fromisoformat(state["next_change"]).hour, 20)
        self.assertIn("fallback", state["description"])
        asleep = schedule.schedule_state(settings, datetime(2026, 12, 21, 21, tzinfo=timezone.utc))
        self.assertFalse(asleep["active"])
        self.assertEqual(datetime.fromisoformat(asleep["resume_at"]).hour, 7)

    def test_disabled_and_equal_boundaries_are_all_day(self):
        for settings in (schedule.validate_schedule({"enabled": False}), self.fixed("07:00", "07:00")):
            for hour in (0, 7, 12, 23):
                state = schedule.schedule_state(settings, datetime(2026, 10, 14, hour, tzinfo=self.zone))
                self.assertTrue(state["active"])
                self.assertEqual(state["sleep_seconds"], 0)
                self.assertIsNone(state["next_change"])
                self.assertIsNone(state["resume_at"])

    def test_timezone_conversion_and_subsecond_hold_rounds_up(self):
        settings = self.fixed("07:00", "20:00")
        state = schedule.schedule_state(settings, datetime(2026, 10, 14, 12, 59, 59, 500000, tzinfo=timezone.utc))
        self.assertFalse(state["active"])
        self.assertEqual(state["sleep_seconds"], 1)
        self.assertTrue(schedule.schedule_state(settings, self.now("2026-10-14T07:00:00"))["active"])
        with self.assertRaises(ValueError):
            schedule.schedule_state(settings, datetime(2026, 10, 14, 12))

    def test_validation_and_nested_merge_do_not_mutate_defaults(self):
        original = deepcopy(schedule.DEFAULT_SCHEDULE)
        current = schedule.validate_schedule({"start": {"offset_minutes": -20}})
        updated = schedule.validate_schedule({"end": {"offset_minutes": 90}}, current)
        self.assertEqual(updated["start"]["offset_minutes"], -20)
        updated["start"]["time"] = "06:00"
        self.assertEqual(current["start"]["time"], "07:00")
        self.assertEqual(schedule.DEFAULT_SCHEDULE, original)
        invalid = [None, [], {"extra": 1}, {"enabled": 1}, {"latitude": True},
                   {"latitude": float("nan")}, {"longitude": float("inf")},
                   {"latitude": 91}, {"latitude": 10**1000}, {"longitude": -181}, {"timezone": "Invalid/Zone"},
                   {"start": None}, {"start": {"extra": 1}}, {"end": {"mode": "dawn"}},
                   {"start": {"offset_minutes": True}}, {"end": {"offset_minutes": 181}},
                   {"start": {"time": "7:00"}}, {"start": {"time": "24:00"}},
                   {"end": {"time": "12:60"}}, {"timezone": "/etc/passwd"}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                schedule.validate_schedule(value)


if __name__ == "__main__":
    unittest.main()
