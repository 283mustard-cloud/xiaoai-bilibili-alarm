"""Offline regression tests for the alarm timing rules.

    python tests/test_alarm_schedule.py

No network, no XiaoMusic, no real config/runstate files. The two job modules
are stubbed, then `alarm_app.decide()` - the real scheduling policy - is ticked
over simulated Beijing times, carrying out the plan the way `scheduler()` does.
This covers the cases that used to fail: pre-dawn alarms, a late wake-up, a
failed prepare, and a failed playback.
"""

import importlib.util
import json
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

# --- stub the job modules so importing the app needs no dependencies --------
prepared = {"ok": True}
play_state = {"ok": True}
play_calls = []


def _prepare_stub(config):
    if not prepared["ok"]:
        raise RuntimeError("prepare failed")


def _play_stub(config, force=False):
    if not play_state["ok"]:
        raise RuntimeError("playback failed")
    play_calls.append(config["play_time"])


sys.modules["prepare_episode"] = types.SimpleNamespace(main=_prepare_stub)
sys.modules["play_alarm"] = types.SimpleNamespace(main=_play_stub)

spec = importlib.util.spec_from_file_location("alarm_app_under_test", ROOT / "alarm_app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

# Never read or write the real config.json / runstate.json.
config_holder = {"value": {}}
app.read_json = lambda path, default: config_holder["value"] if path == app.CONFIG_PATH else default.copy()
app.record = lambda *args, **kwargs: None

from schedule_rules import TZ, eligible_on, workday  # noqa: E402

FAILURES = []
MONDAY = datetime(2026, 9, 21, tzinfo=TZ)       # statutory workday
# 2026-09-25..27 is the Mid-Autumn holiday; 09-26 is a Saturday inside it.
HOLIDAY = datetime(2026, 9, 26, tzinfo=TZ)
# 2026-09-20 is a Sunday but a 调休 make-up workday, so it must still ring.
MAKEUP_DAY = datetime(2026, 9, 20, tzinfo=TZ)


def check(label, actual, expected):
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n        expected {expected!r}\n        actual   {actual!r}")
        FAILURES.append(label)


def reset(ok=True, play_ok=True):
    """Reset the shared stubs so tests cannot leak state into each other."""
    prepared["ok"] = ok
    play_state["ok"] = play_ok
    play_calls.clear()


def base_config(**overrides):
    config = {
        "enabled": True,
        "play_time": "07:30",
        "schedule_mode": "workdays",
        "weekdays": [0, 1, 2, 3, 4],
        "include_dates": [],
        "exclude_dates": [],
        "source_type": "latest",
        "source_url": "https://space.bilibili.com/1/video",
        "title_pattern": ".*",
        "output_mp3": "C:/tmp/alarm/B站闹钟-BV1.mp3",
        "xiaomusic_url": "http://127.0.0.1:58090",
        "device_id": "did",
        "_play_ok": True,
    }
    config.update(overrides)
    return config


def run(clock_start, minutes, state, config, step=5, prep_ok=None):
    """Tick decide() every `step` seconds for `minutes`."""
    config_holder["value"] = config
    actions = []
    for offset in range(0, int(minutes * 60), step):
        current = clock_start + timedelta(seconds=offset)
        plan = app.decide(current, config, state)
        if plan is None:
            continue
        state["last_seen"] = plan["at"]      # what scheduler() records each tick
        state.update(plan["changes"])
        if plan["prepare_due"]:
            if prep_ok is not None:
                prepared["ok"] = prep_ok
            if app.run_job("prepare", lambda c: _prepare_stub(c), wait=True)[1]:
                state["last_prepare_ok"] = plan["marker"]
                state["prep_retry_at"] = None
            actions.append(("prepare", current, plan))
        elif plan["play_due"]:
            if app.run_job("play", lambda c: _play_stub(c), wait=True)[1]:
                state["last_play_ok"] = plan["marker"]
            actions.append(("play", current, plan))
        elif plan["action"] == "skip":
            actions.append(("skip", current, plan))
    return actions


def labels(actions):
    return [action for action, _, _ in actions]


def test_normal_morning():
    print("1) 07:30 on a workday, machine running since 06:00")
    reset()
    config = base_config()
    state = {}
    actions = run(MONDAY.replace(hour=6), 120, state, config, prep_ok=True)
    check("prepare then play once", labels(actions), ["prepare", "play"])
    check("prepare fires at 07:00", actions[0][1].strftime("%H:%M"), "07:00")
    check("play fires at 07:30", actions[1][1].strftime("%H:%M"), "07:30")
    check("on-time playback is not flagged late", actions[1][2]["late_minutes"], None)


def test_pre_dawn_alarm():
    print("2) 00:10 alarm - the prepare window opens the previous evening")
    reset()
    config = base_config(play_time="00:10")
    state = {}
    first = run(datetime(2026, 9, 20, 23, 30, tzinfo=TZ), 15, state, config, prep_ok=True)
    check("prepare fires at 23:40", labels(first), ["prepare"])
    check("prepare time", first[0][1].strftime("%m-%d %H:%M"), "09-20 23:40")
    check("nothing plays before midnight", len(play_calls), 0)
    second = run(datetime(2026, 9, 21, 0, 0), 15, state, config)
    check("play fires at 00:10", labels(second), ["play"])
    check("play time", second[0][1].strftime("%m-%d %H:%M"), "09-21 00:10")


def test_pre_dawn_after_restart():
    print("3) 00:10 alarm, app only starts at 00:00 on the alarm day")
    reset()
    config = base_config(play_time="00:10")
    state = {}
    actions = run(datetime(2026, 9, 21, 0, 0, tzinfo=TZ), 20, state, config, prep_ok=True)
    check("prepare and play both still happen", labels(actions), ["prepare", "play"])


def test_late_wake_up():
    print("4) machine wakes at 07:41, 11 minutes late")
    reset()
    config = base_config()
    state = {}
    actions = run(MONDAY.replace(hour=7, minute=41), 5, state, config)
    check("catch-up playback", labels(actions), ["play"])
    check("reported lateness", actions[0][2]["late_minutes"], 11.0)
    check("played exactly once", len(play_calls), 1)


def test_too_late():
    print("5) machine wakes at 08:10, past the 15 minute catch-up window")
    reset()
    config = base_config()
    state = {}
    actions = run(MONDAY.replace(hour=8, minute=10), 5, state, config)
    check("reports the miss instead of playing", labels(actions), ["skip"])
    check("nothing was played", play_calls, [])
    check("miss logged once", labels(run(MONDAY.replace(hour=8, minute=20), 5, state, config)), [])
    check("no retry later", labels(run(MONDAY.replace(hour=9), 5, state, config)), [])


def test_prepare_retry():
    print("6) prepare fails, then succeeds on a retry inside the window")
    reset(ok=False)
    config = base_config()
    state = {}
    first = run(MONDAY.replace(hour=7), 5, state, config, prep_ok=False)
    check("first attempt at 07:00", labels(first), ["prepare"])
    check("no success marker", state.get("last_prepare_ok"), None)
    throttled = run(MONDAY.replace(hour=7, minute=5), 5, state, config, prep_ok=False)
    check("retry throttled until 07:10", labels(throttled), [])
    retry = run(MONDAY.replace(hour=7, minute=11), 5, state, config, prep_ok=True)
    check("retry succeeds at 07:11", labels(retry), ["prepare"])
    check("success marker recorded for today's alarm",
          state.get("last_prepare_ok"), "2026-09-21@07:30")


def test_playback_retry():
    print("7) playback fails at 07:30 and recovers on a retry")
    reset(play_ok=False)
    config = base_config()
    state = {}
    fail = run(MONDAY.replace(hour=7, minute=30), 1, state, config)
    check("first attempt at 07:30", labels(fail), ["play"])
    check("no success marker yet", state.get("last_play_ok"), None)
    throttle = run(MONDAY.replace(hour=7, minute=30, second=30), 0.5, state, config)
    check("retry throttled for the first minute", labels(throttle), [])
    retry = run(MONDAY.replace(hour=7, minute=31), 1, state, config)
    check("retry attempted after one minute", labels(retry), ["play"])
    play_state["ok"] = True
    recover = run(MONDAY.replace(hour=7, minute=32), 1, state, config)
    check("later retry plays", labels(recover), ["play"])
    check("success marker recorded", state.get("last_play_ok"), "2026-09-21@07:30")
    check("no playback after success", labels(run(MONDAY.replace(hour=7, minute=33), 5, state, config)), [])
    check("exactly one successful playback", len(play_calls), 1)


def test_playback_never_succeeds():
    print("8) playback keeps failing until the catch-up window closes")
    reset(play_ok=False)
    config = base_config()
    state = {}
    actions = run(MONDAY.replace(hour=7, minute=30), 16, state, config)
    attempts = labels(actions).count("play")
    check("retried more than once", attempts >= 2, True)
    check("retries stay inside the window", attempts <= 16, True)
    check("never marked successful", state.get("last_play_ok"), None)
    check("miss is reported after the window", "skip" in labels(actions), True)


def test_not_selected_day():
    print("9) Mid-Autumn holiday with the workday rule")
    reset()
    config = base_config()
    state = {}
    check("2026-09-26 is not a workday", eligible_on(HOLIDAY, config), False)
    actions = run(HOLIDAY.replace(hour=7), 45, state, config)
    check("nothing happens", labels(actions), [])
    check("nothing played", play_calls, [])


def test_makeup_workday_rings():
    print("10) 调休 make-up workday (Sunday 2026-09-20) still rings")
    reset()
    config = base_config()
    check("make-up day counts as a workday", eligible_on(MAKEUP_DAY, config), True)
    actions = run(MAKEUP_DAY.replace(hour=7), 40, {}, config, prep_ok=True)
    check("prepare and play", labels(actions), ["prepare", "play"])


def test_include_and_exclude_dates():
    print("11) extra play date and skip date")
    reset()
    holiday_extra = base_config(include_dates=["2026-09-26"])
    actions = run(HOLIDAY.replace(hour=7), 40, {}, holiday_extra, prep_ok=True)
    check("include_dates adds the day", labels(actions), ["prepare", "play"])

    reset()
    monday_off = base_config(exclude_dates=["2026-09-21"])
    actions2 = run(MONDAY.replace(hour=7), 40, {}, monday_off, prep_ok=True)
    check("exclude_dates wins", labels(actions2), [])


def test_calendar_fallback():
    print("11) calendar data exhausted (2027) falls back instead of crashing")
    future = datetime(2027, 1, 1, 7, 30, tzinfo=TZ)          # a Friday
    try:
        result = eligible_on(future, base_config())
    except Exception as exc:  # noqa: BLE001 - the point of the test
        check("no exception on 2027-01-01", repr(exc), "no exception")
        return
    check("returns a bool on 2027-01-01", isinstance(result, bool), True)
    check("weekday fallback: Friday selected", result, True)
    check("weekday fallback: Saturday skipped",
          eligible_on(datetime(2027, 1, 2, 7, 30, tzinfo=TZ), base_config()), False)
    check("workday() itself does not raise", workday(future.date()), True)
    plan = app.decide(datetime(2027, 1, 1, 7, 0, tzinfo=TZ),
                      base_config(include_dates=["2027-01-01"]), {})
    check("scheduler still produces a plan", plan["action"], "prepare")
    check("next alarm found across the boundary", plan["alarm_at"] is not None, True)
    check("prepare window works past the calendar limit", plan["prepare_due"], True)


def test_next_schedule_edges():
    print("13) next_schedule edge cases")
    disabled = base_config(enabled=False)
    check("disabled -> no plan", app.decide(MONDAY.replace(hour=6), disabled, {}), None)
    check("next_schedule disabled",
          app.next_schedule(MONDAY.replace(hour=6), disabled), (None, None))

    local = base_config(source_type="local")
    _, prepare_at = app.next_schedule(MONDAY.replace(hour=6), local)
    check("local source has no prepare time", prepare_at, None)

    current_minute = MONDAY.replace(hour=7, minute=30)
    alarm_at, _ = app.next_schedule(current_minute, base_config())
    check("alarm minute itself is usable", alarm_at, MONDAY.replace(hour=7, minute=30))

    late = MONDAY.replace(hour=7, minute=30, second=20)
    alarm_at, _ = app.next_schedule(late, base_config())
    check("next_schedule moves on after the minute",
          alarm_at.date().isoformat(), "2026-09-22")

    custom_lead = base_config(prepare_lead_minutes=90)
    _, prepare_at = app.next_schedule(MONDAY.replace(hour=6), custom_lead)
    check("configurable prepare lead", prepare_at.strftime("%H:%M"), "06:00")

    check("previous_alarm finds a just-fired alarm",
          app.previous_alarm(MONDAY.replace(hour=7, minute=31), base_config()),
          MONDAY.replace(hour=7, minute=30))
    check("previous_alarm finds the latest occurrence",
          app.previous_alarm(MONDAY.replace(hour=8), base_config()),
          MONDAY.replace(hour=7, minute=30))
    check("previous_alarm skips a day whose alarm is still ahead",
          app.previous_alarm(MONDAY.replace(hour=6), base_config()),
          MAKEUP_DAY.replace(hour=7, minute=30))


def test_config_validation():
    print("13) config problems produce explicit Chinese errors")
    cases = [
        ("bad play_time", base_config(play_time="7:30")),
        ("bad schedule_mode", base_config(schedule_mode="monthly")),
        ("bad weekday entry", base_config(weekdays=[7])),
        ("bad weekday type", base_config(weekdays=[True])),
        ("bad date", base_config(include_dates=["2026/09/21"])),
        ("bad regex", base_config(title_pattern="([")),
        ("bad space url", base_config(source_url="https://example.com/x")),
        ("missing device", base_config(device_id="")),
        ("missing output", base_config(output_mp3="")),
        ("not a dict", ["not", "a", "dict"]),
    ]
    for label, config in cases:
        try:
            app.validate(config)
            check(label, "accepted", "rejected")
        except ValueError as exc:
            check(f"{label} ({exc})", "rejected", "rejected")


def test_atomic_state_write():
    print("14) runstate writes are atomic and a corrupt file is tolerated")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "runstate.json"
        app.write_json(path, {"last_play_ok": "x"})
        check("round trip", json.loads(path.read_text(encoding="utf-8"))["last_play_ok"], "x")
        check("no .tmp left behind", list(Path(tmp).glob("*.tmp")), [])
        path.write_text("{not json", encoding="utf-8")
        check("corrupt file tolerated", app.read_json(path, {}), {})
        check("missing file tolerated", app.read_json(Path(tmp) / "nope.json", {}), {})


def test_long_run_is_stable():
    print("16) a full week of ticks stays consistent (no double playback)")
    reset()
    config = base_config()
    state = {}
    week = [MONDAY + timedelta(days=i) for i in range(7)]
    expected = sum(1 for day in week if eligible_on(day.replace(hour=7), config))
    for day in week:
        run(day.replace(hour=0, minute=0), 24 * 60, state, config, step=300, prep_ok=True)
    check(f"played on exactly the {expected} selected day(s)", len(play_calls), expected)
    check("no missed alarms", state.get("last_play_missed"), None)
    check("no leftover retry timestamp", state.get("prep_retry_at"), None)


def main():
    print("Alarm schedule regression tests\n")
    for test in (
        test_normal_morning,
        test_pre_dawn_alarm,
        test_pre_dawn_after_restart,
        test_late_wake_up,
        test_too_late,
        test_prepare_retry,
        test_playback_retry,
        test_playback_never_succeeds,
        test_not_selected_day,
        test_makeup_workday_rings,
        test_include_and_exclude_dates,
        test_calendar_fallback,
        test_next_schedule_edges,
        test_config_validation,
        test_atomic_state_write,
        test_long_run_is_stable,
    ):
        test()
        print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
