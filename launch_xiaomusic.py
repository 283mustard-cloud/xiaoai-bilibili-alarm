"""Start the bundled XiaoMusic server without credentials on the command line."""

import sys
import json
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
CONFIG_PATH = ROOT / "xiaomusic-config.json"

# Choose the address of the active LAN route. UDP connect selects an interface
# without sending a packet; keep the saved address if the network is offline.
try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("223.5.5.5", 80))
        lan_ip = sock.getsockname()[0]
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("hostname") != lan_ip:
        config["hostname"] = lan_ip
        CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
except OSError:
    pass

sys.argv = [sys.argv[0], "--config", str(CONFIG_PATH), "--port", "58090"]

from xiaomusic.cli import main

main()
