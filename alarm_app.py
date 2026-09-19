"""Local alarm dashboard and scheduler. Open http://127.0.0.1:58100/.

Timing rules live in schedule_rules.py. `decide()` is the whole scheduling
policy as a pure function (no I/O, no clock, no state mutation) so it can be
ticked over simulated times in tests; the loop and the HTTP server only carry
out what it asks for.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler
from urllib.parse import unquote
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

def project_dir():
    """The folder holding config.json, logs and the music cache.

    A normal script lives in it. A PyInstaller onefile exe does not: __file__
    points inside the temporary extraction folder, so there the exe's own
    location is the project root. An explicit XIAOAI_ALARM_ROOT wins, which the
    exe sets for the child processes it spawns.
    """
    explicit = os.environ.get("XIAOAI_ALARM_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = project_dir()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from schedule_rules import (  # noqa: E402  (needs the vendor path first)
    CATCH_UP_MINUTES,
    DEFAULT_PLAY_TIME,
    PREPARE_RETRY_MINUTES,
    TIME_PATTERN,
    TZ,
    next_schedule,
    now,
    previous_alarm,
)

from play_alarm import main as play_audio  # noqa: E402
from prepare_episode import main as prepare_audio  # noqa: E402
from dashboard_assets import DASHBOARD_HTML  # noqa: E402

CONFIG_PATH = ROOT / "config.json"
RUN_PATH = ROOT / "runstate.json"
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "logs" / "alarm.log"
TMP_DIR = ROOT / "tmp"

LOCK = threading.RLock()
BUSY = set()
BUSY_EVENTS = {}
# The dashboard port. Overridable so a second instance can be started for
# testing without disturbing the scheduled one.
PORT = int(os.environ.get("XIAOAI_ALARM_PORT") or os.environ.get("PORT") or 58100)
DASHBOARD_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

# How many prepared Bilibili episodes to keep on disk. Each episode is a new
# file (the speaker may hold the old one open), so old ones have to be pruned.
# Matched by the trailing BV id so any "<label>-BV<id>.mp3" naming works and
# unrelated music files are never touched.
KEEP_EPISODES = 3
EPISODE_GLOB = "*-BV*.mp3"
# Playback retries are spaced by this many minutes inside the catch-up window.
PLAY_RETRY_MINUTES = 1
# A first attempt fires almost immediately after the alarm minute, so the ring
# is not delayed by the retry spacing.
PLAY_FIRST_GRACE_SECONDS = 20
# An alarm is "on time" for this long after its minute; later is a catch-up.
ON_TIME_GRACE_SECONDS = 60
# How long after a closed catch-up window a failed alarm is still reported as
# missed (a failure at 07:30 should not still be announced at midnight).
MISS_REPORT_HOURS = 2
SCHEDULER_TICK_SECONDS = 5
LOG = logging.getLogger("alarm")


def setup_logging():
    """Log to logs/alarm.log; without this a failed 07:30 leaves no trace."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default.copy()
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        LOG.warning("Ignoring unreadable %s: %s", path.name, exc)
        return default.copy()


def write_json(path, value):
    """Atomically replace a JSON file, surviving transient Windows lock errors.

    The final os.replace() can collide with another writer or with a scanner
    holding a brief handle on the target, which surfaces as PermissionError.
    Losing runstate.json (or crashing the scheduler over it) would be worse
    than waiting a few milliseconds, so retry briefly before giving up.
    """
    body = json.dumps(value, ensure_ascii=False, indent=2)
    temp = path.with_suffix(path.suffix + ".tmp")
    last_error = None
    for attempt in range(5):
        try:
            temp.write_text(body, encoding="utf-8")
            temp.replace(path)
            return
        except PermissionError as exc:      # another writer or a scanner holds it
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
        except OSError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    raise last_error


def record(kind, result, message):
    with LOCK:
        state = read_json(RUN_PATH, {})
        state[kind] = {"at": now().isoformat(timespec="seconds"), "result": result,
                       "message": str(message)[-500:]}
        write_json(RUN_PATH, state)


def parse_dt(value):
    """Parse a runstate timestamp, always returning tz-aware Beijing time.

    Comparisons against `now()` would otherwise raise on the naive datetimes
    that datetime.fromisoformat() produces for a value without an offset.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TZ)
    return parsed


def occurred_at(state, kind, when, config):
    """Was the alarm due at `when` actually carried out successfully?

    Understands the current `last_<kind>_ok` marker as well as the older
    `last_<kind>_day` plus `<kind>.result` pair, so a runstate written by a
    previous version keeps reporting the truth instead of claiming a miss.
    """
    if when is None:
        return None
    current = f"{when.date().isoformat()}@{config.get('play_time')}"
    if state.get(f"last_{kind}_ok") is not None:
        return state.get(f"last_{kind}_ok") == current
    legacy_day = state.get(f"last_{kind}_day")
    if not isinstance(legacy_day, str):
        return False
    entry = state.get(kind)
    if not isinstance(entry, dict) or entry.get("result") != "ok":
        return False
    day, _, time_text = legacy_day.partition("@")
    # Older builds stored the configured time rather than the alarm time.
    return day == when.date().isoformat() and (
        not time_text or time_text in (config.get("play_time"), when.strftime("%H:%M")))


def decide(current, config, state):
    """What should happen right now.

    Returns a plan dict, or None when the alarm is switched off. The plan is
    pure data: `action` is one of prepare / play / retry / skip / wait, and
    `changes` are the runstate fields the caller must persist when it carries
    the action out.
    """
    if not config.get("enabled", True):
        return None
    alarm_at, prepare_at = next_schedule(current, config)
    configured_time = config.get("play_time") or DEFAULT_PLAY_TIME

    def marker_of(when):
        return f"{when.date().isoformat()}@{configured_time}"

    # --- content preparation -------------------------------------------------
    prepare = {"due": False, "marker": None, "next_attempt": None}
    if alarm_at is not None and prepare_at is not None and prepare_at <= current < alarm_at:
        marker = marker_of(alarm_at)
        retry_at = parse_dt(state.get("prep_retry_at"))
        if state.get("last_prepare_ok") == marker:
            prepare.update(marker=marker, next_attempt=None)
        elif retry_at is None or current >= retry_at:
            prepare.update(due=True, marker=marker,
                           next_attempt=current + timedelta(minutes=PREPARE_RETRY_MINUTES))
        else:
            prepare.update(marker=marker, next_attempt=retry_at)
    if alarm_at is not None:
        plan_alarm, plan_prepare = alarm_at, prepare_at
    else:
        plan_alarm, plan_prepare = None, None

    # --- playback ------------------------------------------------------------
    # Playback can target the upcoming alarm (its minute has arrived) or the
    # most recent one, which stays actionable inside the catch-up window while
    # next_schedule() has already moved on to tomorrow.
    recent = previous_alarm(current, config)
    upcoming = alarm_at if (alarm_at is not None and alarm_at <= current) else None
    target = upcoming if upcoming is not None else recent
    play = {"due": False, "marker": None, "next_attempt": None, "gave_up": False,
            "late_minutes": None}

    if target is not None and target <= current:
        marker = marker_of(target)
        window_end = target + timedelta(minutes=CATCH_UP_MINUTES)
        if current < window_end:
            # Ring (or retry) inside the window. A first attempt fires at the
            # alarm minute; a retry is spaced by PLAY_RETRY_MINUTES.
            already_attempted = state.get("last_play_day") == marker
            last_attempt = parse_dt(state.get("last_play_at"))
            on_time = current - target < timedelta(seconds=ON_TIME_GRACE_SECONDS)
            if already_attempted and last_attempt is not None:
                due_at = last_attempt + timedelta(minutes=PLAY_RETRY_MINUTES)
            elif on_time:
                # The alarm minute just arrived: ring without extra delay.
                due_at = target
            else:
                # Woke up late: a short grace keeps the ring off the very edge.
                due_at = target + timedelta(seconds=PLAY_FIRST_GRACE_SECONDS)
            late_minutes = None
            if not on_time:
                late_minutes = round((current - target).total_seconds() / 60, 1)
            if state.get("last_play_ok") == marker:
                play.update(marker=marker)
            elif current >= due_at:
                play.update(due=True, marker=marker, late_minutes=late_minutes,
                            next_attempt=current + timedelta(minutes=PLAY_RETRY_MINUTES))
            else:
                play.update(marker=marker, late_minutes=late_minutes, next_attempt=due_at)
        elif (current <= window_end + timedelta(hours=MISS_REPORT_HOURS)
                and state.get("last_play_ok") != marker
                and state.get("last_missed_logged") != marker):
            # The window is over without a success. Say so once, so a failed
            # 07:30 is visible in logs and on the dashboard instead of silent.
            play.update(marker=marker, gave_up=True, late_minutes=round(
                (current - target).total_seconds() / 60, 1))

    if prepare["due"]:
        action = "prepare"
    elif play["due"]:
        action = "play"
    elif play["gave_up"]:
        action = "skip"
    else:
        action = "wait"

    changes = {}
    if prepare["due"]:
        # Values are the same JSON-safe strings that get written to runstate,
        # so an in-memory state behaves exactly like a reloaded one.
        changes.update(last_prepare_day=prepare["marker"],
                       prep_retry_at=prepare["next_attempt"].isoformat() if prepare["next_attempt"] else None)
    if play["due"]:
        changes.update(last_play_day=play["marker"], last_play_at=current.isoformat())
    if play["gave_up"]:
        # Only a marker, so the miss is logged once instead of every tick.
        changes.update(last_missed_logged=play["marker"])

    return {
        "at": current.isoformat(timespec="seconds"),
        "action": action,
        "alarm_at": plan_alarm.isoformat(timespec="minutes") if plan_alarm else None,
        "prepare_at": plan_prepare.isoformat(timespec="minutes") if plan_prepare else None,
        "marker": play["marker"] or prepare["marker"],
        "late_minutes": play["late_minutes"],
        "next_attempt": (prepare["next_attempt"] or play["next_attempt"]).isoformat()
                        if (prepare["next_attempt"] or play["next_attempt"]) else None,
        "prepare_due": prepare["due"],
        "play_due": play["due"],
        "changes": changes,
    }


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("配置格式无效，应为 JSON 对象")
    if not TIME_PATTERN.fullmatch(str(config.get("play_time", ""))):
        raise ValueError("播放时间需为 HH:MM")
    if config.get("schedule_mode") not in {"workdays", "daily", "weekdays", "dates"}:
        raise ValueError("请选择有效的日期方式")
    weekdays = config.get("weekdays", [])
    if not isinstance(weekdays, list) or any(type(x) is not int or x not in range(7) for x in weekdays):
        raise ValueError("星期选择无效")
    for key in ("include_dates", "exclude_dates"):
        dates = config.get(key, [])
        if not isinstance(dates, list):
            raise ValueError("日期列表无效")
        for value in dates:
            if not isinstance(value, str):
                raise ValueError("日期格式无效")
            if datetime.strptime(value, "%Y-%m-%d").date().isoformat() != value:
                raise ValueError("日期格式无效")
    pattern = config.get("title_pattern") or ".*"
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"标题筛选正则无效: {exc}")
    if config.get("source_type") == "latest":
        if not re.fullmatch(r"https://space\.bilibili\.com/\d+(?:/video)?/?", config.get("source_url", "")):
            raise ValueError("请填写 B 站账号投稿页链接")
    elif config.get("source_type") == "video":
        if not re.fullmatch(r"https://www\.bilibili\.com/video/BV[a-zA-Z0-9]+/?(?:\?.*)?", config.get("video_url", "")):
            raise ValueError("请填写完整的 B 站 BV 视频链接")
    elif config.get("source_type") != "local":
        raise ValueError("请选择播放内容类型")
    for key in ("xiaomusic_url", "device_id", "output_mp3"):
        if not str(config.get(key) or "").strip():
            raise ValueError(f"配置缺少 {key}，请检查 config.json")
    return config


def run_job(kind, job, wait=False):
    """Run one job kind in a worker thread.

    Returns (started, ok): `started` is False when the same kind is already
    running. With `wait=True` the call blocks until this job finishes and `ok`
    reports its real result, so the scheduler never drops a playback attempt
    just because a slow download was still running.
    """
    with LOCK:
        if kind in BUSY:
            return False, False
        BUSY.add(kind)
        event = threading.Event()
        BUSY_EVENTS[kind] = event
    outcome = {"ok": False}

    def worker():
        try:
            config = read_json(CONFIG_PATH, {})
            job(config)
            outcome["ok"] = True
            record(kind, "ok", "完成")
        except Exception as exc:
            LOG.exception("%s job failed", kind)
            record(kind, "error", exc)
        finally:
            with LOCK:
                BUSY.discard(kind)
                BUSY_EVENTS.pop(kind, None)
            event.set()

    threading.Thread(target=worker, daemon=True).start()
    if wait:
        event.wait()
        return True, outcome["ok"]
    return True, False


def status_payload():
    """Everything the dashboard, the tray and the GUI know about the run.

    Single source of truth so the tray tooltip, the native window and
    /api/status can never disagree.
    """
    config = read_json(CONFIG_PATH, {})
    state = read_json(RUN_PATH, {})
    current = now()
    next_play, next_prepare = next_schedule(current, config)
    output = str(config.get("output_mp3") or "")
    last_due = previous_alarm(current, config)
    planned = f"{config.get('play_time')}"
    last_marker = state.get("last_play_day")
    state["busy"] = bool(BUSY)
    state["episode"] = read_json(STATE_PATH, {})
    state["audio_ready"] = bool(output) and Path(output).is_file()
    state["auto_update"] = config.get("source_type", "latest") != "local"
    state["catch_up_minutes"] = CATCH_UP_MINUTES
    state["last_alarm"] = last_due.isoformat(timespec="minutes") if last_due else None
    state["last_play_ok"] = occurred_at(state, "play", last_due, config)
    # Missed = the most recent attempt was for a real alarm and it failed.
    state["last_play_missed"] = bool(
        last_due and isinstance(last_marker, str) and last_marker.endswith(f"@{planned}")
        and state.get("last_play_ok") is not True
    )
    state["next_play"] = next_play.isoformat(timespec="minutes") if next_play else None
    state["next_prepare"] = next_prepare.isoformat(timespec="minutes") if next_prepare else None
    state["enabled"] = bool(config.get("enabled", True))
    return state


def set_enabled(enabled):
    """Turn the alarm on or off from outside the dashboard."""
    with LOCK:
        config = read_json(CONFIG_PATH, {})
        config["enabled"] = bool(enabled)
        validate(config)
        write_json(CONFIG_PATH, config)
        return config["enabled"]


def serve_job(kind, job, wait=False):
    """Public wrapper so the GUI can trigger jobs like the dashboard does."""
    return run_job(kind, job, wait)


def http_server(port=None):
    """Build (but do not start) the dashboard server."""
    return ThreadingHTTPServer(("127.0.0.1", port or PORT), Handler)


def prepare_job(config):
    """Fetch/convert the configured content. Raises when it is not usable."""
    if config.get("source_type") == "local":
        target = Path(str(config.get("output_mp3") or ""))
        if not target.is_file():
            raise RuntimeError("本地音频文件不存在，请重新上传")
        return
    prepare_audio(config)


def play_job(config):
    play_audio(config, force=True)


def prune_episodes(music_dir, current):
    """Keep only the newest KEEP_EPISODES downloaded episodes.

    Never deletes the active file, and tolerates locked files (the speaker may
    still have an old MP3 open) by trying again next time.
    """
    try:
        if not music_dir.is_dir():
            return
        files = sorted(music_dir.glob(EPISODE_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError as exc:
        LOG.warning("Could not list %s: %s", music_dir, exc)
        return
    active = Path(current).name if current else ""
    for stale in files[KEEP_EPISODES:]:
        if stale.name == active:
            continue
        try:
            stale.unlink()
            LOG.info("Removed old episode %s", stale.name)
        except OSError as exc:
            LOG.info("Kept old episode %s: %s", stale.name, exc)


def merge_state(changes):
    """Re-read runstate.json and apply `changes` on top of the current content.

    A job (prepare/play) runs in a worker thread and writes its own "last
    result" record through record() while this thread waits for it. Writing
    back a snapshot taken before the job would erase that record, which is
    exactly what made the dashboard claim a job had never run.
    """
    with LOCK:
        merged = read_json(RUN_PATH, {})
        merged.update(changes)
        write_json(RUN_PATH, merged)
        return merged


def run_scheduler_tick(config, state, current=None):
    """One scheduler iteration, separated from the loop so it can be tested."""
    current = current or now()
    plan = decide(current, config, state)
    if plan is None:
        return None
    state.update(plan["changes"])
    # Evidence that this runner was alive right now, used to tell a genuinely
    # missed alarm from one the machine slept through.
    updates = dict(plan["changes"])
    updates["last_seen"] = plan["at"]

    handled = None
    if plan["prepare_due"]:
        LOG.info("Preparing content for %s", plan["marker"])
        handled = "prepare"
        if run_job("prepare", prepare_job, wait=True)[1]:
            updates["last_prepare_ok"] = plan["marker"]
            updates["prep_retry_at"] = None
            prune_episodes(Path(str(config.get("output_mp3") or ROOT)).parent,
                           config.get("output_mp3"))
    elif plan["play_due"]:
        if plan["late_minutes"]:
            LOG.info("Playing for %s (late by %s min)", plan["marker"], plan["late_minutes"])
        else:
            LOG.info("Playing for %s", plan["marker"])
        handled = "play"
        if run_job("play", play_job, wait=True)[1]:
            updates["last_play_ok"] = plan["marker"]
    elif plan["action"] == "skip":
        LOG.error("Gave up on %s: no successful playback within %s minutes",
                  plan["marker"], CATCH_UP_MINUTES)

    snapshot = {k: v for k, v in plan.items() if k != "changes"}
    if handled:
        snapshot["handled"] = handled
    updates["plan"] = snapshot
    state.update({k: v for k, v in updates.items() if k != "last_seen"})
    return merge_state(updates)


def scheduler():
    LOG.info("Scheduler started; tick=%ss, catch-up=%smin, play retry=%smin",
             SCHEDULER_TICK_SECONDS, CATCH_UP_MINUTES, PLAY_RETRY_MINUTES)
    while True:
        try:
            config = read_json(CONFIG_PATH, {})
            state = read_json(RUN_PATH, {})
            run_scheduler_tick(config, state)
        except Exception:
            LOG.exception("Scheduler tick failed")
        time.sleep(SCHEDULER_TICK_SECONDS)



class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            # Prefer the embedded copy (a frozen exe ships no data files), but
            # fall back to the file so editing dashboard.html still works.
            body = DASHBOARD_HTML.encode("utf-8")
            html_path = ROOT / "dashboard.html"
            if html_path.is_file():
                body = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self.send_json(200, status_payload())
        elif self.path == "/api/config":
            self.send_json(200, read_json(CONFIG_PATH, {}))
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if origin and origin not in DASHBOARD_ORIGINS:
            self.send_json(403, {"error": "Wrong origin"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 100 * 1024 * 1024:
                raise ValueError("文件超过 100 MB")
            body = self.rfile.read(length)
            if self.path == "/api/config":
                incoming = json.loads(body)
                with LOCK:
                    config = read_json(CONFIG_PATH, {})
                    allowed = {"enabled", "schedule_mode", "weekdays", "include_dates", "exclude_dates",
                               "play_time", "source_type", "source_url", "title_pattern", "video_url"}
                    content_keys = {"source_type", "source_url", "title_pattern", "video_url"}
                    changed = any(k in incoming and incoming[k] != config.get(k) for k in content_keys)
                    config.update({k: v for k, v in incoming.items() if k in allowed})
                    validate(config)
                    if config.get("source_type") == "local" and read_json(STATE_PATH, {}).get("source") != "local":
                        raise ValueError("请先上传本地音频")
                    write_json(CONFIG_PATH, config)
                started = False
                if changed and config.get("source_type") != "local":
                    started = run_job("prepare", prepare_job)[0]
                self.send_json(200, {"ok": True, "refreshing": started})
            elif self.path == "/api/prepare":
                started = run_job("prepare", prepare_job)[0]
                self.send_json(202 if started else 409, {"ok": started})
            elif self.path == "/api/play":
                started = run_job("play", play_job)[0]
                self.send_json(202 if started else 409, {"ok": started})
            elif self.path == "/api/stop":
                config = read_json(CONFIG_PATH, {})
                url = str(config.get("xiaomusic_url") or "").rstrip("/") + "/device/stop"
                data = json.dumps({"did": config.get("device_id")}).encode("utf-8")
                request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=15) as response:
                    result = json.load(response)
                self.send_json(200, result)
            elif self.path == "/api/upload":
                if not body:
                    raise ValueError("请先选择音频文件")
                if "prepare" in BUSY:
                    raise RuntimeError("正在更新网络内容，请稍后上传")
                config = read_json(CONFIG_PATH, {})
                music_dir = Path(str(config.get("output_mp3") or (ROOT / "music" / "alarm.mp3"))).parent
                music_dir.mkdir(parents=True, exist_ok=True)
                target = music_dir / f"本地音频-{uuid.uuid4().hex[:12]}.mp3"
                temp = ROOT / "tmp" / "uploaded-audio"
                temp.parent.mkdir(parents=True, exist_ok=True)
                temp.write_bytes(body)
                converted = target.with_name(target.stem + ".new.mp3")
                try:
                    import imageio_ffmpeg
                    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(temp),
                                    "-vn", "-codec:a", "libmp3lame", "-qscale:a", "5", str(converted)],
                                   capture_output=True, check=True, timeout=300)
                    converted.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
                    converted.unlink(missing_ok=True)
                url = str(config.get("xiaomusic_url") or "").rstrip("/") + "/cmd"
                payload = json.dumps({"did": config.get("device_id"), "cmd": "刷新列表"}, ensure_ascii=False).encode("utf-8")
                request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=20) as response:
                    result = json.load(response)
                if result.get("ret") != "OK":
                    raise RuntimeError(f"播放列表刷新失败: {result}")
                config["output_mp3"] = str(target)
                config["source_type"] = "local"
                write_json(CONFIG_PATH, config)
                write_json(STATE_PATH, {"title": unquote(self.headers.get("X-Filename", "本地音频")),
                                        "source": "local", "prepared_at": now().isoformat()})
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "Not found"})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)[-500:]})

    def log_message(self, format, *args):
        pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="小爱 B 站闹钟：网页控制台与调度器")
    parser.add_argument("--port", type=int, default=PORT,
                        help=f"控制台端口，默认 {PORT}（也可用环境变量 XIAOAI_ALARM_PORT）")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="只启动网页控制台，不跑调度（用于排查问题）")
    parser.add_argument("--tray", action="store_true",
                        help="同时显示托盘图标和本机窗口（打包后的 exe 默认开启）")
    return parser.parse_args(argv)


def run_service(port=None, with_scheduler=True, block=True):
    """Start the scheduler thread and the dashboard; return the HTTP server."""
    target_port = port or PORT
    if with_scheduler:
        threading.Thread(target=scheduler, daemon=True).start()
    else:
        LOG.warning("Scheduler disabled by --no-scheduler; the alarm will not ring")
    server = ThreadingHTTPServer(("127.0.0.1", target_port), Handler)
    if block:
        server.serve_forever()
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv=None):
    args = parse_args(argv)
    setup_logging()
    run_service(port=args.port, with_scheduler=not args.no_scheduler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
