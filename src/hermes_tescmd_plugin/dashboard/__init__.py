from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config import get_hermes_home

DASHBOARD_PLUGIN_NAME = "hermes-tescmd-plugin"


def source_dashboard_dir() -> Path:
    return Path(__file__).resolve().parent


def user_dashboard_dir() -> Path:
    return get_hermes_home() / "plugins" / DASHBOARD_PLUGIN_NAME / "dashboard"


def ensure_dashboard_installed() -> dict[str, Any]:
    """Install packaged dashboard assets into Hermes' dashboard plugin tree.

    The Hermes dashboard discovers drop-in extensions under
    ``HERMES_HOME/plugins/<name>/dashboard``. Pip entry-point plugins do not have
    a filesystem plugin directory there by default, so registration mirrors the
    packaged static assets into that user plugin slot. Files are tiny and
    deterministic; mutable Tesla config/state still stays in the plugin-owned
    state directory, not in the dashboard asset tree.
    """
    src = source_dashboard_dir()
    dst = user_dashboard_dir()
    if not src.exists():
        return {
            "ok": False,
            "installed": False,
            "reason": "packaged dashboard assets are missing",
            "path": str(dst),
        }
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name == "__pycache__":
            continue
        target = dst / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                child, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        else:
            shutil.copy2(child, target)
    return {"ok": True, "installed": True, "path": str(dst)}
