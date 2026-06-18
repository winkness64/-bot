from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
PLUGINS_DIR = SRC_DIR / "plugins"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main() -> None:
    load_dotenv(ROOT / ".env")
    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    nonebot.load_plugins(str(PLUGINS_DIR))
    nonebot.run()


if __name__ == "__main__":
    main()
