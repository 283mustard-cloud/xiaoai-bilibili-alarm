"""Tests for the tray/GUI diagnostics.

Runs without opening a window or using the real config:

    python tests/test_alarm_gui.py

Covers the parts that decide what the tray says, because a wrong "all good"
is worse than no indicator at all.
"""

import importlib.util
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import alarm_app as core  # noqa: E402
import alarm_gui as gui  # noqa: E402
from schedule_rules import TZ  # noqa: E402

FAILURES = []


def check(label, actual, expected):
    if actual == expected:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n        expected {expected!r}\n        actual   {actual!r}")
        FAILURES.append(label)


def base_config(tmp, **overrides):
    audio = Path(tmp) / "B站闹钟-BVTEST.mp3"
    audio.write_bytes(b"\x00" * 200_000)
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
        "output_mp3": str(audio),
        # Point at a port nothing listens on so the check is deterministic.
        "xiaomusic_url": "http://127.0.0.1:59998",
        "device_id": "test-device",
    }
    config.update(overrides)
    return config


def write_runstate(tmp, **fields):
    state = {"last_seen": core.now().isoformat(), "last_play_ok": None, "last_play_day": None}
    state.update(fields)
    path = Path(tmp) / "runstate.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def with_fake_project(tmp, config):
    """Redirect the app's file paths at a temp project directory.

    Returns the config it wrote, so callers pass that to self_check() rather
    than the temp path.
    """
    tmp = Path(tmp)
    core.CONFIG_PATH = tmp / "config.json"
    core.RUN_PATH = tmp / "runstate.json"
    core.STATE_PATH = tmp / "state.json"
    core.LOG_PATH = tmp / "logs" / "alarm.log"
    core.TMP_DIR = tmp / "tmp"
    core.CONFIG_PATH.write_text(json.dumps(config), encoding="utf-8")
    return config


def test_countdown_formatting():
    print("1) countdown wording")
    now = core.now()
    check("no target", gui.countdown(None), "未安排")
    check("past the catch-up window", gui.countdown(now - timedelta(hours=2)), "已过")
    check("inside the catch-up window", gui.countdown(now - timedelta(minutes=2)), "正在进行")
    check("hours and minutes", gui.countdown(now + timedelta(hours=2, minutes=5)), "还有 2 小时 5 分")
    check("minutes only", gui.countdown(now + timedelta(minutes=25)), "还有 25 分")
    check("under a minute still counts as 1", gui.countdown(now + timedelta(seconds=20)), "还有 1 分")


def test_stamp():
    print("2) timestamp formatting")
    check("formats as month-day hour:minute",
          gui.stamp(core.now().replace(month=9, day=20, hour=7, minute=30)), "09-20 07:30")
    check("none is a dash", gui.stamp(None), "—")


def test_health_states():
    print("3) tray headline reflects the real state")
    with tempfile.TemporaryDirectory() as tmp:
        config = with_fake_project(tmp, base_config(tmp))
        write_runstate(tmp)

        class FakeApp(gui.TrayAlarm):
            def __init__(self):
                pass

            def snapshot(self):
                return self._snap

        app = FakeApp()
        app._snap = {
            "state": {"audio_ready": True, "busy": False, "last_play_missed": False},
            "config": {"enabled": True},
            "alarm_at": core.now() + timedelta(hours=5),
        }
        colour, headline, _ = app.health(app._snap)
        check("healthy is green", colour, gui.GREEN)
        check("headline mentions normal operation", "正常运行" in headline, True)

        app._snap["config"]["enabled"] = False
        check("disabled is grey", app.health(app._snap)[0], gui.GREY)

        app._snap["config"]["enabled"] = True
        app._snap["state"]["audio_ready"] = False
        colour, headline, _ = app.health(app._snap)
        check("missing audio is red", colour, gui.RED)
        check("missing audio is explained", "没有可播放的音频" in headline, True)

        app._snap["state"]["audio_ready"] = True
        app._snap["state"]["busy"] = True
        check("busy is amber", app.health(app._snap)[0], gui.AMBER)

        app._snap["state"]["busy"] = False
        app._snap["state"]["last_play_missed"] = True
        colour, headline, _ = app.health(app._snap)
        check("missed alarm is red", colour, gui.RED)
        check("missed alarm is explained", "上次计划播放未成功" in headline, True)


def test_self_check_reports_problems():
    print("4) self-check flags what would stop the alarm")
    with tempfile.TemporaryDirectory() as tmp:
        config = with_fake_project(tmp, base_config(tmp))
        write_runstate(tmp)
        # self_check validates the config first, so anything it reads must be
        # present; index-based lookups keep this test independent of wording.
        # Row order: 0 config, 1 scheduler, 2 audio, 3 downloader, 4 XiaoMusic, 5 speaker
        results = gui.self_check(config)
        check("one row per check", len(results) >= 5, True)
        check("config row passes", results[0][0], True)
        check("scheduler row passes with a fresh heartbeat", results[1][0], True)
        check("audio row passes", results[2][0], True)
        check("downloader row passes", results[3][0], True)
        check("xiaomusic row fails (nothing on that port)", results[4][0], False)

        # local audio needs no downloader row at all
        local = base_config(tmp, source_type="local")
        local_rows = gui.self_check(local)
        check("local source has no downloader row",
              any("下载" in row[1] for row in local_rows), False)

        # a stale heartbeat means the scheduler died
        Path(core.RUN_PATH).write_text(json.dumps(
            {"last_seen": (core.now() - timedelta(minutes=5)).isoformat()}), encoding="utf-8")
        results = gui.self_check(config)
        check("stale heartbeat is flagged", results[1][0], False)
        check("stale heartbeat is explained", "停止" in results[1][2], True)

        # a missing audio file must be flagged before the alarm time
        missing = base_config(tmp, output_mp3=str(Path(tmp) / "nope.mp3"))
        results = gui.self_check(missing)
        check("missing audio is flagged", results[2][0], False)
        # broken config returns early with a single failing row
        broken = base_config(tmp, play_time="7:30")
        rows = gui.self_check(broken)
        check("broken config is the only row", len(rows), 1)
        check("broken config fails", rows[0][0], False)


def test_tcp_and_device_probe_are_safe():
    print("5) network probes never raise")
    check("closed port returns False", gui.tcp_open("127.0.0.1", 59998), False)
    check("unreachable device returns None", gui.xiaomusic_device_online(
        {"device_id": "x", "xiaomusic_url": "http://127.0.0.1:59998"}), None)
    check("empty config returns None", gui.xiaomusic_device_online({}), None)


def test_tail_lines():
    print("6) log tail is resilient")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "alarm.log"
        check("missing file gives no lines", gui.tail_lines(path), [])
        path.write_text("\n".join(f"line {i}" for i in range(30)), encoding="utf-8")
        lines = gui.tail_lines(path, 5)
        check("returns the requested tail", lines, ["line 25", "line 26", "line 27", "line 28", "line 29"])


def test_window_and_tray_actually_build():
    """Build the real tray icon and the real window.

    The first packaged build passed my smoke test (port open, HTTP 200) while
    the tray icon silently failed: pystray needs a PIL Image, and a file path
    raised AttributeError inside pystray's setup thread, leaving no icon and a
    frozen window. This test exercises exactly those code paths.
    """
    print("7) tray icon and window build for real")

    # 1. the icon must be a PIL object pystray can serialize to the shell
    from PIL import Image, ImageDraw
    icon = gui.make_icon(gui.GREEN)
    check("make_icon returns a PIL Image", isinstance(icon, Image.Image), True)
    check("icon has the expected size", icon.size, (gui.ICON_SIZE, gui.ICON_SIZE))

    stream = None
    drawn = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    try:
        for method in ("save", "__enter__", "__exit__"):
            check(f"icon supports {method}()", hasattr(icon, method), True)
    except Exception as exc:  # noqa: BLE001
        check("icon attribute probe", repr(exc), "no exception")
    try:
        import io
        stream = io.BytesIO()
        icon.save(stream, format="ICO")
        check("icon serializes as ICO", stream.tell() > 0, True)
    except Exception as exc:  # noqa: BLE001
        check("icon serializes as ICO", repr(exc), "no exception")

    # 2. the tray menu must build from a real snapshot
    with tempfile.TemporaryDirectory() as tmp:
        config = with_fake_project(tmp, base_config(tmp))
        write_runstate(tmp)
        app = gui.TrayAlarm(port=58199, with_scheduler=False)
        app.icon = FakeIcon()                      # capture notify() safely
        try:
            menu = app.menu()
            check("tray menu builds", menu is not None, True)
            check("tray menu has items", len(list(menu)) >= 8, True)
        except Exception as exc:  # noqa: BLE001
            check("tray menu builds", repr(exc), "no exception")

        # 3. the window must construct, render a tick and close cleanly
        try:
            import tkinter
            available = True
        except ImportError:
            available = False
        if not available:
            print("  SKIP  tkinter unavailable; window test skipped")
            return
        window = gui.AlarmWindow(app)
        try:
            window.root.withdraw()                 # never steal focus while testing
            window.tick()                          # render one frame
            window.root.update()
            headline = window.headline.cget("text")
            body = window.next_label.cget("text")
            check("window headline is filled in", bool(headline.strip()), True)
            check("window body shows the next alarm", "下次播放" in body, True)
            check("window body shows the episode", "当前内容" in body, True)
            window._show_checks([(True, "自检", "ok"), (False, "音箱", "离线")])
            window.root.update()
            checks_text = window.checks.get("1.0", "end")
            check("self-check rows render", "自检：ok" in checks_text, True)
            check("failing row renders with a cross", "✘" in checks_text, True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            check("window tick runs without error", traceback.format_exc(limit=2), "no exception")
        finally:
            try:
                window.root.destroy()
            except Exception:  # noqa: BLE001
                pass


class FakeIcon:
    """Stands in for pystray.Icon so tests never touch the real tray."""

    def __init__(self):
        self.icon = None
        self.title = None
        self.menu = None
        self.notifications = []

    def notify(self, message, title=None):
        self.notifications.append((title, message))

    def stop(self):
        pass


def main():
    print("Tray/GUI diagnostics tests\n")
    original = (core.CONFIG_PATH, core.RUN_PATH, core.STATE_PATH, core.LOG_PATH, core.TMP_DIR)
    try:
        for test in (test_countdown_formatting, test_stamp, test_health_states,
                     test_self_check_reports_problems, test_tcp_and_device_probe_are_safe,
                     test_tail_lines, test_window_and_tray_actually_build):
            test()
            print()
    finally:
        core.CONFIG_PATH, core.RUN_PATH, core.STATE_PATH, core.LOG_PATH, core.TMP_DIR = original
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
