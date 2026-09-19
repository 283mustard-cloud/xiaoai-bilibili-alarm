"""Play the prepared episode on the selected XiaoMusic speaker.

Run standalone it only plays inside the alarm minute and only on a day the
schedule selects; the dashboard passes force=True once it has already decided
that the alarm is due.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("XIAOAI_ALARM_ROOT") or Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from schedule_rules import eligible_on, now, play_time_of  # noqa: E402


class PlaybackSkipped(RuntimeError):
    """Raised when the alarm is not due now; not a failure."""


def main(config=None, force=False):
    config = config or json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if not force:
        current = now()
        hour, minute = play_time_of(config)
        if current.hour != hour or current.minute != minute:
            raise PlaybackSkipped("Outside the configured alarm minute")
        if not eligible_on(current, config):
            raise PlaybackSkipped(
                f"No playback: {current.date().isoformat()} is not selected by schedule_mode="
                f"{config.get('schedule_mode')}"
            )
    target = Path(str(config.get("output_mp3") or ""))
    if not target.is_file():
        raise RuntimeError("No prepared episode; keep the speaker's native alarm enabled")
    url = str(config.get("xiaomusic_url") or "").rstrip("/") + "/playmusic"
    payload = json.dumps({
        "did": config.get("device_id"),
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
    except PlaybackSkipped as exc:
        print(str(exc))
    except Exception as exc:
        print(f"Playback failed: {exc}", file=sys.stderr)
        sys.exit(1)
