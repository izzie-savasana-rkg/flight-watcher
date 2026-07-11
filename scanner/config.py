"""Load and validate the JSON config files under data/."""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FW_DATA_DIR", REPO_ROOT / "data"))


def load_json(name: str, default=None):
    path = DATA_DIR / name
    if not path.exists():
        return default if default is not None else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(name: str, payload) -> None:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def load_settings() -> dict:
    return load_json("settings.json")


def load_watches() -> list:
    watches = load_json("watches.json", {"watches": []})["watches"]
    return [w for w in watches if w.get("enabled", True)]
