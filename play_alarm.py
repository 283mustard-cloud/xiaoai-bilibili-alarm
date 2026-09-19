"""Play the prepared episode on the selected XiaoMusic speaker."""

import json
import urllib.request
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
def main(config=None, force=False):
    config = config or json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    now = datetime.now(timezone(timedelta(hours=8)))
    if not force:
        from chinese_calendar import is_workday
        hour, minute = map(int, config.get("play_time", "07:30").split(":"))
        if now.hour != hour or now.minute != minute:
            raise RuntimeError("Outside the configured alarm minute")
        if not is_workday(now.date()):
            print("No playback: statutory day off", now.date())
            return
    target = Path(config["output_mp3"])
    if not target.is_file():
        raise RuntimeError("No prepared episode; keep the speaker's native alarm enabled")
    url = config["xiaomusic_url"].rstrip("/") + "/playmusic"
    payload = json.dumps({
        "did": config["device_id"],
        "musicname": target.stem,
    }).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
    }, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if result.get("ret") != "OK":
        raise RuntimeError(f"XiaoMusic rejected playback: {result}")
    print("Playback requested:", target.stem)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Playback failed: {exc}", file=sys.stderr)
        sys.exit(1)
