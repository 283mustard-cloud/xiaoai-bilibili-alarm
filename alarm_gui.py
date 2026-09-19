"""Tray icon and native window for the alarm.

Runs the same scheduler and dashboard as alarm_app.py, but in one visible
process: a tray icon that shows the next alarm at a glance, plus a window with
a health self-check ("can it actually ring right now?") so a silent failure is
noticed before the alarm is missed.

Usage:
    python alarm_gui.py              # tray + window + scheduler + dashboard
    python alarm_gui.py --no-window  # start in the tray only
"""

import argparse
import json
import re
import socket
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import alarm_app as core  # noqa: E402
from schedule_rules import CATCH_UP_MINUTES, TZ, next_schedule, prepare_lead, previous_alarm  # noqa: E402

APP_TITLE = "小爱 B 站闹钟"
CHECK_INTERVAL_MS = 5000
ICON_SIZE = 64
GREEN, AMBER, RED, GREY = "#2e9e5b", "#d98324", "#c93a3a", "#8b95a3"


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def local_dt(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def countdown(target, prefix="还有"):
    """'还有 13 小时 22 分' for a future time, or a short past-tense note."""
    if target is None:
        return "未安排"
    delta = target - core.now()
    seconds = delta.total_seconds()
    if seconds < -CATCH_UP_MINUTES * 60:
        return "已过"
    if seconds <= 0:
        return "正在进行"
    minutes = int(seconds // 60) + (1 if seconds % 60 else 0)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{prefix} {hours} 小时 {mins} 分"
    return f"{prefix} {mins} 分"


def stamp(target):
    return target.strftime("%m-%d %H:%M") if target else "—"


def tail_lines(path, count=14):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-count:]


# --------------------------------------------------------------------------- #
# health self-check: would the alarm actually ring right now?
# --------------------------------------------------------------------------- #
def tcp_open(host, port, timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def xiaomusic_device_online(config):
    """Return True/False/None (None = could not tell) for the configured device."""
    device_id = str(config.get("device_id") or "")
    base = str(config.get("xiaomusic_url") or "").rstrip("/")
    if not device_id or not base:
        return None
    try:
        with urllib.request.urlopen(f"{base}/device_list", timeout=4) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - any failure means "could not tell"
        return None
    if device_id not in payload:
        return None
    # The payload is JSON whose shape varies between XiaoMusic versions; look
    # for the device object and read its status field loosely.
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    devices = data.get("data") if isinstance(data, dict) else None
    if isinstance(devices, dict):
        devices = devices.get("devices") or [devices]
    if not isinstance(devices, list):
        return None
    for device in devices:
        if isinstance(device, dict) and str(device.get("did") or device.get("deviceID") or "") == device_id:
            text = json.dumps(device, ensure_ascii=False)
            if re.search(r'"(?:status|hardware|presence)"\s*:\s*"(?:online|idle|1|true)"', text, re.I):
                return True
            if re.search(r'"(?:status|hardware|presence)"\s*:\s*"(?:offline|0|false)"', text, re.I):
                return False
            return None
    return None


def self_check(config=None):
    """[(ok, label, detail)] describing whether the alarm can ring."""
    config = config or core.read_json(core.CONFIG_PATH, {})
    checks = []

    # 1. config sanity
    try:
        core.validate(config)
        checks.append((True, "配置", "播放时间与内容来源有效"))
    except Exception as exc:  # noqa: BLE001
        checks.append((False, "配置", f"有问题：{exc}"))
        return checks

    # 2. scheduler liveness, measured from the runstate heartbeat
    state = core.read_json(core.RUN_PATH, {})
    seen = local_dt(state.get("last_seen"))
    if seen is None:
        checks.append((False, "调度器", "还没有心跳记录，刚启动或未运行"))
    else:
        age = (core.now() - seen).total_seconds()
        ok = age < 30
        checks.append((ok, "调度器", f"{'正常' if ok else '可能已停止'}（{int(age)} 秒前心跳）"))

    # 3. prepared audio file
    target = Path(str(config.get("output_mp3") or ""))
    if target.is_file():
        size_mb = target.stat().st_size / 1024 / 1024
        checks.append((True, "音频", f"{target.name}（{size_mb:.1f} MB）"))
    else:
        checks.append((False, "音频", f"文件不存在：{target}"))

    # 3b. network content needs a real Python for yt-dlp, which a packed exe
    # cannot provide by itself.
    if config.get("source_type", "latest") != "local":
        import prepare_episode
        try:
            interpreter = prepare_episode.python_exe()
            checks.append((True, "下载工具", f"yt-dlp 将使用 {interpreter}"))
        except Exception as exc:  # noqa: BLE001
            checks.append((False, "下载工具", str(exc)))

    # 4. XiaoMusic service
    base = str(config.get("xiaomusic_url") or "")
    port = 58090
    host = "127.0.0.1"
    try:
        parsed = urlparse(base)
        host = parsed.hostname or host
        port = parsed.port or port
    except ValueError:
        pass
    if tcp_open(host, port):
        checks.append((True, "XiaoMusic", f"{host}:{port} 可连接"))
        online = xiaomusic_device_online(config)
        if online is True:
            checks.append((True, "音箱", f"设备 {config.get('device_id')} 在线"))
        elif online is False:
            checks.append((False, "音箱", f"设备 {config.get('device_id')} 离线"))
        else:
            checks.append((None, "音箱", "无法确认在线状态（不影响定时播放尝试）"))
    else:
        checks.append((False, "XiaoMusic", f"{host}:{port} 连不上，播放会失败"))

    return checks


# --------------------------------------------------------------------------- #
# tray icon
# --------------------------------------------------------------------------- #
def make_icon(colour):
    """Build the tray icon.

    Must return a PIL Image: pystray calls image.save() when it hands the icon
    to the Windows shell, so passing a file path raises
    AttributeError: 'str' object has no attribute 'save' and the tray icon is
    never created (which left the app with no icon and a frozen window).
    """
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 6
    draw.ellipse((margin, margin, ICON_SIZE - margin, ICON_SIZE - margin), fill=colour)
    centre = ICON_SIZE // 2
    draw.line((centre, centre, centre, centre - 16), fill="white", width=4)
    draw.line((centre, centre, centre + 12, centre + 6), fill="white", width=4)
    return image


class TrayAlarm:
    def __init__(self, port, with_scheduler=True, start_hidden=False):
        self.port = port
        self.with_scheduler = with_scheduler
        self.window = None
        self.server = None
        self.icon = None
        self.icon_cache = {}
        self.hidden_notice_sent = False
        self._stop = threading.Event()

    # -- service --------------------------------------------------------- //
    def start_service(self):
        self.server = core.run_service(port=self.port, with_scheduler=self.with_scheduler,
                                       block=False)
        core.LOG.info("Dashboard on http://127.0.0.1:%s (tray mode)", self.port)

    # -- snapshot -------------------------------------------------------- //
    def snapshot(self):
        state = core.status_payload()
        config = core.read_json(core.CONFIG_PATH, {})
        current = core.now()
        alarm_at, prepare_at = next_schedule(current, config)
        return {"state": state, "config": config, "now": current,
                "alarm_at": alarm_at, "prepare_at": prepare_at,
                "last_alarm": previous_alarm(current, config)}

    def health(self, snapshot):
        """(colour, headline, detail) for the tray and the window header."""
        state, config = snapshot["state"], snapshot["config"]
        if not config.get("enabled", True):
            return GREY, "闹钟已关闭", "托盘里右键可以重新启用"
        if not state.get("audio_ready"):
            return RED, "没有可播放的音频", "打开控制台更新内容，或检查内容来源"
        if state.get("busy"):
            return AMBER, "正在处理（更新或播放中）", countdown(snapshot["alarm_at"], "距下次播放")
        if state.get("last_play_missed"):
            return RED, "上次计划播放未成功", "查看日志 logs/alarm.log"
        return GREEN, f"闹钟正常运行 · {countdown(snapshot['alarm_at'], '距下次播放')}", \
            f"下次播放 {stamp(snapshot['alarm_at'])}"

    # -- tray ------------------------------------------------------------ //
    def icon_for(self, colour):
        if colour not in self.icon_cache:
            self.icon_cache[colour] = make_icon(colour)
        return self.icon_cache[colour]

    def menu(self):
        import pystray
        snapshot = self.snapshot()
        colour, headline, detail = self.health(snapshot)
        state = snapshot["state"]
        episode = (state.get("episode") or {}).get("title") or "尚未准备内容"
        if len(episode) > 28:
            episode = episode[:28] + "…"
        enabled = snapshot["config"].get("enabled", True)
        return pystray.Menu(
            pystray.MenuItem(headline, None, enabled=False),
            pystray.MenuItem(f"下次播放 {stamp(snapshot['alarm_at'])}", None, enabled=False),
            pystray.MenuItem(f"内容：{episode}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开状态窗口", self.on_show, default=True),
            pystray.MenuItem("打开网页控制台", self.on_browser),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("试听当前内容（让音箱响一下）", self.on_test_ring),
            pystray.MenuItem("现在更新内容", self.on_prepare),
            pystray.MenuItem("停止播放", self.on_stop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("关闭闹钟（不再定时播放）" if enabled else "启用闹钟",
                             self.on_toggle_enabled),
            pystray.MenuItem("打开日志文件", self.on_logs),
            pystray.MenuItem("退出（闹钟将停止）", self.on_quit),
        )

    def refresh_icon(self):
        if self.icon is None:
            return
        try:
            snapshot = self.snapshot()
            colour, headline, detail = self.health(snapshot)
            self.icon.icon = self.icon_for(colour)
            self.icon.title = f"{APP_TITLE}\n{headline}"
            self.icon.menu = self.menu()
        except Exception:  # noqa: BLE001 - the tray must never crash the app
            core.LOG.exception("Tray refresh failed")

    def notify(self, message, title=APP_TITLE):
        if self.icon is None:
            return
        try:
            self.icon.notify(message, title)
        except Exception:  # noqa: BLE001 - notifications are best effort
            core.LOG.info("Notification unavailable: %s", message)

    # -- menu actions ---------------------------------------------------- //
    def on_show(self, *_):
        if self.window is None:
            self.window = AlarmWindow(self)
        self.window.show()

    def on_browser(self, *_):
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{self.port}/")

    def on_test_ring(self, *_):
        started = core.serve_job("play", core.play_job)[0]
        self.notify("已让音箱开始试听" if started else "正在忙，稍后再试")
        self.refresh_icon()

    def on_prepare(self, *_):
        started = core.serve_job("prepare", core.prepare_job)[0]
        self.notify("正在更新内容，完成后会显示在窗口里" if started else "正在忙，稍后再试")
        self.refresh_icon()

    def on_stop(self, *_):
        config = core.read_json(core.CONFIG_PATH, {})
        url = str(config.get("xiaomusic_url") or "").rstrip("/") + "/device/stop"
        data = json.dumps({"did": config.get("device_id")}).encode("utf-8")
        request = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15):
                self.notify("已停止播放")
        except Exception as exc:  # noqa: BLE001
            self.notify(f"停止失败：{exc}")

    def on_toggle_enabled(self, *_):
        config = core.read_json(core.CONFIG_PATH, {})
        now_enabled = core.set_enabled(not config.get("enabled", True))
        self.notify("闹钟已启用" if now_enabled else "闹钟已关闭，不会再定时播放")
        self.refresh_icon()

    def on_logs(self, *_):
        log_path = core.LOG_PATH
        if log_path.is_file():
            import os
            os.startfile(str(log_path))  # noqa: S606 - opening a log in Notepad is intended
        else:
            self.notify("还没有日志文件")

    def on_quit(self, *_):
        if self.icon is not None:
            self.icon.stop()

    # -- lifecycle ------------------------------------------------------- //
    def run(self, start_hidden=False):
        import pystray
        self.start_service()
        snapshot = self.snapshot()
        colour, _headline, _detail = self.health(snapshot)
        self.icon = pystray.Icon(APP_TITLE, icon=self.icon_for(colour), title=APP_TITLE,
                                 menu=self.menu())
        threading.Thread(target=self._background_refresh, daemon=True).start()
        if not start_hidden:
            self.on_show()
        core.LOG.info("Tray started")
        self.icon.run()

    def _background_refresh(self):
        while not self._stop.is_set():
            time.sleep(CHECK_INTERVAL_MS / 1000)
            self.refresh_icon()


# --------------------------------------------------------------------------- #
# native window
# --------------------------------------------------------------------------- #
class AlarmWindow:
    def __init__(self, app):
        import tkinter as tk
        self.tk = tk
        self.app = app
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("560x560")
        self.root.minsize(520, 480)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._build()
        self.check_running = False
        self.root.after(200, self.tick)

    def _build(self):
        tk = self.tk
        frame = tk.Frame(self.root, padx=16, pady=14)
        frame.pack(fill="both", expand=True)

        self.colour_bar = tk.Frame(frame, height=6, bg=GREY)
        self.colour_bar.pack(fill="x", pady=(0, 12))

        self.headline = tk.Label(frame, text="正在检查…", font=("Microsoft YaHei", 15, "bold"),
                                 anchor="w", justify="left")
        self.headline.pack(fill="x")
        self.detail = tk.Label(frame, text="", font=("Microsoft YaHei", 10), fg="#5b6675",
                               anchor="w", justify="left")
        self.detail.pack(fill="x", pady=(2, 12))

        self.next_label = tk.Label(frame, text="", font=("Consolas", 11), anchor="w",
                                   justify="left", fg="#24354b")
        self.next_label.pack(fill="x", pady=(0, 12))

        buttons = tk.Frame(frame)
        buttons.pack(fill="x", pady=(0, 12))
        for text, command in (("试听（让音箱响一下）", self.on_test_ring),
                              ("现在更新内容", self.on_prepare),
                              ("网页控制台", self.app.on_browser),
                              ("隐藏到托盘", self.hide)):
            tk.Button(buttons, text=text, command=command, padx=10, pady=6).pack(side="left", padx=(0, 8))

        tk.Label(frame, text="自检", font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(fill="x")
        self.checks = tk.Text(frame, height=8, wrap="word", relief="flat", bg="#f6f8fb",
                              font=("Microsoft YaHei", 9))
        self.checks.pack(fill="x", pady=(4, 12))
        self.checks.configure(state="disabled")

        tk.Label(frame, text="最近日志", font=("Microsoft YaHei", 11, "bold"), anchor="w").pack(fill="x")
        self.logs = tk.Text(frame, height=8, wrap="none", relief="flat", bg="#f6f8fb",
                            font=("Consolas", 8))
        self.logs.pack(fill="both", expand=True, pady=(4, 0))
        self.logs.configure(state="disabled")

    # -- helpers --------------------------------------------------------- //
    def set_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(400, lambda: self.root.attributes("-topmost", False))

    def hide(self):
        self.root.withdraw()
        if not self.app.hidden_notice_sent:
            self.app.hidden_notice_sent = True
            self.app.notify("已隐藏到托盘，闹钟仍在后台运行")

    # -- actions --------------------------------------------------------- //
    def on_test_ring(self):
        self.app.on_test_ring()
        self.refresh_now()

    def on_prepare(self):
        self.app.on_prepare()
        self.refresh_now()

    def refresh_now(self):
        self.root.after(50, self.tick)

    # -- periodic refresh ------------------------------------------------ //
    def tick(self):
        try:
            snapshot = self.app.snapshot()
            colour, headline, detail = self.app.health(snapshot)
            state = snapshot["state"]
            self.colour_bar.configure(bg=colour)
            self.headline.configure(text=headline, fg=colour)
            self.detail.configure(text=detail)
            episode = (state.get("episode") or {}).get("title") or "尚未准备内容"
            lines = [
                f"现在        {snapshot['now'].strftime('%m-%d %H:%M:%S')}",
                f"下次播放    {stamp(snapshot['alarm_at'])}   {countdown(snapshot['alarm_at'])}",
            ]
            if state.get("auto_update"):
                lines.append(f"下次更新    {stamp(snapshot['prepare_at'])}   {countdown(snapshot['prepare_at'])}")
            else:
                lines.append("下次更新    本地音频，无需更新")
            lines.append(f"当前内容    {episode}")
            last = snapshot["last_alarm"]
            result = "已播放" if state.get("last_play_ok") else ("未成功" if state.get("last_play_missed") else "未记录")
            lines.append(f"上次计划    {stamp(last)}   {result}")
            self.next_label.configure(text="\n".join(lines))
            self.set_text(self.logs, "\n".join(tail_lines(core.LOG_PATH)) or "（暂无日志）")
            if not self.check_running:
                self.check_running = True
                threading.Thread(target=self._run_checks, args=(snapshot["config"],), daemon=True).start()
        except Exception:  # noqa: BLE001 - keep the window alive
            core.LOG.exception("Window refresh failed")
        finally:
            self.root.after(CHECK_INTERVAL_MS, self.tick)

    def _run_checks(self, config):
        try:
            results = self_check(config)
        except Exception:  # noqa: BLE001
            results = [(False, "自检", "自检本身出错，详见日志")]
        self.root.after(0, lambda: self._show_checks(results))

    def _show_checks(self, results):
        mark = {True: "✔", False: "✘", None: "•"}
        text = "\n".join(f"{mark[ok]} {label}：{detail}" for ok, label, detail in results)
        self.set_text(self.checks, text)
        self.check_running = False


def gui_selftest():
    """Build the tray icon and the window for real, inside this process.

    This is the check that the first packaged build needed and did not have: a
    frozen app can start, serve HTTP and still be unusable because the tray
    icon or the window failed to construct. Run with --selftest-gui.
    """
    failures = []

    def report(label, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {label}{(': ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    icon = make_icon(GREEN)
    report("tray icon is a PIL Image", hasattr(icon, "save"),
           type(icon).__name__)
    import io
    stream = io.BytesIO()
    icon.save(stream, format="ICO")
    report("tray icon serializes as ICO", stream.tell() > 0, f"{stream.tell()} bytes")

    app = TrayAlarm(port=0, with_scheduler=False)
    menu = app.menu()
    report("tray menu builds", len(list(menu)) > 0, f"{len(list(menu))} items")

    try:
        import pystray
        tray = pystray.Icon(APP_TITLE, icon=icon, title=APP_TITLE, menu=menu)
        report("pystray accepts the icon", tray is not None)
    except Exception as exc:  # noqa: BLE001
        report("pystray accepts the icon", False, repr(exc))

    try:
        snapshot = app.snapshot()
        colour, headline, detail = app.health(snapshot)
        report("status snapshot readable", bool(headline), headline)
    except Exception as exc:  # noqa: BLE001
        report("status snapshot readable", False, repr(exc))

    try:
        checks = self_check()
        report("self-check runs", len(checks) > 0, f"{len(checks)} rows")
        for ok, label, detail in checks:
            print(f"      {'OK  ' if ok else ('WARN' if ok is None else 'FAIL')}  {label}: {detail}")
    except Exception as exc:  # noqa: BLE001
        report("self-check runs", False, repr(exc))

    window_ok = True
    try:
        window = AlarmWindow(app)
        window.root.withdraw()
        window.tick()
        window.root.update()
        window._show_checks([(True, "自检", "ok")])
        window.root.update()
        window.root.destroy()
    except Exception:  # noqa: BLE001
        window_ok = False
        traceback.print_exc()
    report("window builds and renders a frame", window_ok)

    print()
    if failures:
        print(f"{len(failures)} GUI check(s) failed: {failures}")
        return 1
    print("GUI self-test passed.")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="小爱 B 站闹钟（托盘 + 窗口）")
    parser.add_argument("--port", type=int, default=core.PORT)
    parser.add_argument("--no-scheduler", action="store_true",
                        help="只显示界面，不跑调度（排查问题用）")
    parser.add_argument("--no-window", action="store_true", help="只显示托盘，不弹出窗口")
    parser.add_argument("--self-check", action="store_true",
                        help="在控制台打印自检结果后退出")
    parser.add_argument("--selftest-gui", action="store_true",
                        help="实际构建托盘图标与窗口后退出（验证打包是否可用）")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    core.setup_logging()
    if args.selftest_gui:
        return gui_selftest()
    if args.self_check:
        labels = {True: "OK  ", False: "FAIL", None: "WARN"}
        for ok, label, detail in self_check():
            print(f"{labels[ok]} {label}: {detail}")
        return 0
    app = TrayAlarm(port=args.port, with_scheduler=not args.no_scheduler)
    try:
        app.run(start_hidden=args.no_window)
    except KeyboardInterrupt:
        pass
    except Exception:
        core.LOG.exception("Tray failed to start")
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
