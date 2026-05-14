"""aff-hub utils。"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "docs"  # GitHub Pages allows /docs (not /public)
DATA = ROOT / "data"
LOGS = ROOT / "logs"
JST = timezone(timedelta(hours=9))


def jst_today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def setup_logger(name: str) -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def load_monetization_ids() -> dict:
    p = Path.home() / "MONETIZATION_IDS.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
