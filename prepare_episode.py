"""Prepare the chosen Bilibili audio for XiaoMusic."""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
TZ = timezone(timedelta(hours=8))


def ytdlp(*args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "vendor") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp", *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, env=env,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")
    return result.stdout


def main(config=None):
    config = config or json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    source_type = config.get("source_type", "latest")
    if source_type == "local":
        target = Path(config["output_mp3"])
        if not target.is_file():
            raise RuntimeError("No local audio has been uploaded")
        return
    source = config["source_url"] if source_type == "latest" else config["video_url"]
    pattern = re.compile(config.get("title_pattern") or ".*", re.IGNORECASE)
    music_dir = Path(config["output_mp3"]).expanduser().resolve().parent
    music_dir.mkdir(parents=True, exist_ok=True)
    state_path = ROOT / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    if source_type == "latest":
        listing = json.loads(ytdlp("--flat-playlist", "--playlist-end", "20", "-J", source))
        entries = listing.get("entries") or []
        if pattern.pattern in (".*", ""):
            entries = entries[:1]
    elif source_type == "video":
        entries = [{"url": source}]
    else:
        raise ValueError("Unsupported source type")
    candidates = []
    for item in entries:
        if not item:
            continue
        url = item.get("webpage_url") or item.get("url")
        if not url:
            continue
        if not url.startswith("http"):
            url = "https://www.bilibili.com/video/" + url
        try:
            info = json.loads(ytdlp("-J", "--no-playlist", url))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if source_type == "latest" and not pattern.search(info.get("title") or ""):
            continue
        timestamp = info.get("release_timestamp") or info.get("timestamp")
        if not timestamp and info.get("upload_date"):
            timestamp = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=TZ).timestamp()
        if timestamp:
            candidates.append((timestamp, info))

    if not candidates:
        raise RuntimeError("No matching episode found in the newest 20 uploads")
    _, episode = max(candidates, key=lambda pair: pair[0])
    episode_id = episode.get("id")
    if not re.fullmatch(r"[a-zA-Z0-9]+", episode_id or ""):
        raise RuntimeError("Unexpected video ID")
    target = music_dir / f"B站闹钟-{episode_id}.mp3"

    video_url = episode.get("webpage_url") or f"https://www.bilibili.com/video/{episode_id}"
    if not target.exists() or target.stat().st_size < 100_000:
        temporary = target.with_name(target.stem + ".new.mp3")
        temporary.unlink(missing_ok=True)
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ROOT / "vendor") + os.pathsep + env.get("PYTHONPATH", "")
            env["PYTHONIOENCODING"] = "utf-8"
            import imageio_ffmpeg
            subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--no-playlist", "-x", "--audio-format", "mp3",
                 "--audio-quality", "5", "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
                 "-o", str(temporary), video_url],
                check=True, timeout=1800, env=env,
            )
            if not temporary.exists() or temporary.stat().st_size < 100_000:
                raise RuntimeError("Audio preparation produced no usable MP3")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    # Each episode gets its own filename; the speaker may keep the old file open.
    config_path = ROOT / "config.json"
    latest_config = json.loads(config_path.read_text(encoding="utf-8"))
    active_source = latest_config["source_url"] if source_type == "latest" else latest_config["video_url"]
    if latest_config.get("source_type", "latest") != source_type or active_source != source:
        raise RuntimeError("Content source changed while preparing; kept the previous selection")
    url = latest_config["xiaomusic_url"].rstrip("/") + "/cmd"
    request = urllib.request.Request(url, data=json.dumps({
        "did": latest_config["device_id"], "cmd": "刷新列表"
    }, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("ret") != "OK":
        raise RuntimeError(f"XiaoMusic could not refresh its library: {result}")
    latest_config["output_mp3"] = str(target)
    config_tmp = config_path.with_suffix(".json.tmp")
    config_tmp.write_text(json.dumps(latest_config, ensure_ascii=False, indent=2), encoding="utf-8")
    config_tmp.replace(config_path)
    state_path.write_text(json.dumps({
        "episode_id": episode_id,
        "title": episode.get("title"),
        "url": video_url,
        "source": source,
        "prepared_at": datetime.now(TZ).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Prepared:", episode.get("title"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
