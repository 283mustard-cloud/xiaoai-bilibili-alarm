"""Local alarm dashboard and scheduler. Open http://127.0.0.1:58100/."""

import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from chinese_calendar import is_workday

from play_alarm import main as play_audio
from prepare_episode import main as prepare_audio

CONFIG_PATH = ROOT / "config.json"
RUN_PATH = ROOT / "runstate.json"
TZ = timezone(timedelta(hours=8))
LOCK = threading.RLock()
BUSY = set()


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default.copy()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def today():
    return datetime.now(TZ)


def eligible(day, config):
    iso = day.date().isoformat()
    if iso in config.get("exclude_dates", []):
        return False
    if iso in config.get("include_dates", []):
        return True
    mode = config.get("schedule_mode", "workdays")
    if mode == "workdays":
        return is_workday(day.date())
    if mode == "daily":
        return True
    if mode == "weekdays":
        return day.weekday() in config.get("weekdays", [])
    if mode == "dates":
        return False
    raise ValueError("Unknown schedule mode")


def next_schedule(now, config):
    """Return the next alarm and its automatic refresh time."""
    if not config.get("enabled", True):
        return None, None
    hour, minute = map(int, config.get("play_time", "07:30").split(":"))
    for offset in range(370):
        day = now + timedelta(days=offset)
        alarm_at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if alarm_at >= now and eligible(alarm_at, config):
            prepare_at = None if config.get("source_type") == "local" else alarm_at - timedelta(minutes=30)
            return alarm_at, prepare_at
    return None, None


def validate(config):
    match = re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", config.get("play_time", ""))
    if not match:
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
            if datetime.strptime(value, "%Y-%m-%d").date().isoformat() != value:
                raise ValueError("日期格式无效")
    source_type = config.get("source_type")
    if source_type == "latest":
        if not re.fullmatch(r"https://space\.bilibili\.com/\d+(?:/video)?/?", config.get("source_url", "")):
            raise ValueError("请填写 B 站账号投稿页链接")
        re.compile(config.get("title_pattern") or ".*")
    elif source_type == "video":
        if not re.fullmatch(r"https://www\.bilibili\.com/video/BV[a-zA-Z0-9]+/?(?:\?.*)?", config.get("video_url", "")):
            raise ValueError("请填写完整的 B 站 BV 视频链接")
    elif source_type != "local":
        raise ValueError("请选择播放内容类型")
    return config


def record(kind, result, message):
    with LOCK:
        state = read_json(RUN_PATH, {})
        state[kind] = {"at": today().isoformat(timespec="seconds"), "result": result, "message": str(message)[-500:]}
        write_json(RUN_PATH, state)


def run_job(kind, job):
    with LOCK:
        if kind in BUSY:
            return False
        BUSY.add(kind)

    def worker():
        try:
            config = read_json(CONFIG_PATH, {})
            job(config)
            record(kind, "ok", "完成")
        except Exception as exc:
            record(kind, "error", exc)
        finally:
            with LOCK:
                BUSY.discard(kind)

    threading.Thread(target=worker, daemon=True).start()
    return True


def scheduler():
    while True:
        try:
            now = today()
            config = read_json(CONFIG_PATH, {})
            if config.get("enabled", True) and eligible(now, config):
                hour, minute = map(int, config.get("play_time", "07:30").split(":"))
                alarm_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                prepare_at = alarm_at - timedelta(minutes=30)
                state = read_json(RUN_PATH, {})
                marker = now.date().isoformat() + "@" + config.get("play_time", "07:30")
                if (prepare_at.date() == now.date() and prepare_at <= now < alarm_at
                        and state.get("last_prepare_day") != marker):
                    state["last_prepare_day"] = marker
                    write_json(RUN_PATH, state)
                    run_job("prepare", prepare_audio)
                if now.hour == hour and now.minute == minute and state.get("last_play_day") != marker:
                    state["last_play_day"] = marker
                    write_json(RUN_PATH, state)
                    run_job("play", lambda c: play_audio(c, force=True))
        except Exception as exc:
            record("scheduler", "error", exc)
        time.sleep(5)


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
            body = (ROOT / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            config = read_json(CONFIG_PATH, {})
            state = read_json(RUN_PATH, {})
            next_play, next_prepare = next_schedule(today(), config)
            state["busy"] = bool(BUSY)
            state["episode"] = read_json(ROOT / "state.json", {})
            state["audio_ready"] = Path(config["output_mp3"]).is_file()
            state["auto_update"] = config.get("source_type") != "local"
            state["next_play"] = next_play.isoformat(timespec="minutes") if next_play else None
            state["next_prepare"] = next_prepare.isoformat(timespec="minutes") if next_prepare else None
            self.send_json(200, state)
        elif self.path == "/api/config":
            self.send_json(200, read_json(CONFIG_PATH, {}))
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if origin and origin not in ("http://127.0.0.1:58100", "http://localhost:58100"):
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
                    if config["source_type"] == "local" and read_json(ROOT / "state.json", {}).get("source") != "local":
                        raise ValueError("请先上传本地音频")
                    write_json(CONFIG_PATH, config)
                refreshing = changed and config["source_type"] != "local" and run_job("prepare", prepare_audio)
                self.send_json(200, {"ok": True, "refreshing": refreshing})
            elif self.path == "/api/prepare":
                self.send_json(202 if run_job("prepare", prepare_audio) else 409, {"ok": True})
            elif self.path == "/api/play":
                self.send_json(202 if run_job("play", lambda c: play_audio(c, force=True)) else 409, {"ok": True})
            elif self.path == "/api/stop":
                config = read_json(CONFIG_PATH, {})
                url = config["xiaomusic_url"].rstrip("/") + "/device/stop"
                data = json.dumps({"did": config["device_id"]}).encode("utf-8")
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
                music_dir = Path(config["output_mp3"]).parent
                target = music_dir / f"本地音频-{uuid.uuid4().hex[:12]}.mp3"
                temp = ROOT / "tmp" / "uploaded-audio"
                temp.parent.mkdir(parents=True, exist_ok=True)
                temp.write_bytes(body)
                import imageio_ffmpeg
                converted = target.with_name(target.stem + ".new.mp3")
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(temp),
                                "-vn", "-codec:a", "libmp3lame", "-qscale:a", "5", str(converted)],
                               capture_output=True, check=True, timeout=300)
                converted.replace(target)
                temp.unlink(missing_ok=True)
                url = config["xiaomusic_url"].rstrip("/") + "/cmd"
                payload = json.dumps({"did": config["device_id"], "cmd": "刷新列表"}, ensure_ascii=False).encode("utf-8")
                request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=20) as response:
                    result = json.load(response)
                if result.get("ret") != "OK":
                    raise RuntimeError(f"播放列表刷新失败: {result}")
                config["output_mp3"] = str(target)
                config["source_type"] = "local"
                write_json(CONFIG_PATH, config)
                write_json(ROOT / "state.json", {"title": unquote(self.headers.get("X-Filename", "本地音频")),
                                                      "source": "local", "prepared_at": today().isoformat()})
                self.send_json(200, {"ok": True})
            else:
                self.send_json(404, {"error": "Not found"})
        except Exception as exc:
            self.send_json(400, {"error": str(exc)[-500:]})

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 58100), Handler).serve_forever()
