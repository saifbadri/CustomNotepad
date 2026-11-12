"""Settings, recent files, and session text under %APPDATA%\\PyNotepad\\."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_DIR_NAME = "PyNotepad"

DEFAULT_PAGE_SETUP: dict[str, Any] = {
    "page_size_id": None,
    "orientation": "portrait",
    "left": 12.7,
    "top": 12.7,
    "right": 12.7,
    "bottom": 12.7,
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "system",
    "font_family": "Consolas",
    "font_size": 11,
    "font_weight": 400,
    "font_italic": False,
    "word_wrap": True,
    "status_bar": True,
    "restore_session": True,
    "recent_files": [],
    "page_setup": dict(DEFAULT_PAGE_SETUP),
}


def app_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    path = root / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_dir() / "settings.json"


def session_path() -> Path:
    return app_dir() / "session.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {
        "theme": DEFAULT_SETTINGS["theme"],
        "font_family": DEFAULT_SETTINGS["font_family"],
        "font_size": DEFAULT_SETTINGS["font_size"],
        "font_weight": DEFAULT_SETTINGS["font_weight"],
        "font_italic": DEFAULT_SETTINGS["font_italic"],
        "word_wrap": DEFAULT_SETTINGS["word_wrap"],
        "status_bar": DEFAULT_SETTINGS["status_bar"],
        "restore_session": DEFAULT_SETTINGS["restore_session"],
        "recent_files": [],
        "page_setup": dict(DEFAULT_PAGE_SETUP),
    }
    stored = _read_json(settings_path())
    if not stored:
        return settings
    theme = stored.get("theme")
    if theme in ("system", "light", "dark"):
        settings["theme"] = theme
    family = stored.get("font_family")
    if isinstance(family, str) and family.strip():
        settings["font_family"] = family
    size = stored.get("font_size")
    if isinstance(size, (int, float)) and 1 <= float(size) <= 200:
        settings["font_size"] = int(size)
    weight = stored.get("font_weight")
    if isinstance(weight, int) and 1 <= weight <= 1000:
        settings["font_weight"] = weight
    if isinstance(stored.get("font_italic"), bool):
        settings["font_italic"] = stored["font_italic"]
    if isinstance(stored.get("word_wrap"), bool):
        settings["word_wrap"] = stored["word_wrap"]
    if isinstance(stored.get("status_bar"), bool):
        settings["status_bar"] = stored["status_bar"]
    if isinstance(stored.get("restore_session"), bool):
        settings["restore_session"] = stored["restore_session"]
    recent = stored.get("recent_files")
    if isinstance(recent, list):
        settings["recent_files"] = [item for item in recent if isinstance(item, str)][:10]
    page = stored.get("page_setup")
    if isinstance(page, dict):
        merged = dict(DEFAULT_PAGE_SETUP)
        orientation = page.get("orientation")
        if orientation in ("portrait", "landscape"):
            merged["orientation"] = orientation
        page_size_id = page.get("page_size_id")
        if isinstance(page_size_id, int):
            merged["page_size_id"] = page_size_id
        for edge in ("left", "top", "right", "bottom"):
            value = page.get(edge)
            if isinstance(value, (int, float)) and value >= 0:
                merged[edge] = float(value)
        settings["page_setup"] = merged
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    recent = [item for item in settings.get("recent_files", []) if isinstance(item, str)][:10]
    page = settings.get("page_setup")
    payload = {
        "theme": settings.get("theme", "system"),
        "font_family": settings.get("font_family", "Consolas"),
        "font_size": int(settings.get("font_size", 11)),
        "font_weight": int(settings.get("font_weight", 400)),
        "font_italic": bool(settings.get("font_italic", False)),
        "word_wrap": bool(settings.get("word_wrap", True)),
        "status_bar": bool(settings.get("status_bar", True)),
        "restore_session": bool(settings.get("restore_session", True)),
        "recent_files": recent,
        "page_setup": page if isinstance(page, dict) else dict(DEFAULT_PAGE_SETUP),
    }
    _write_json(settings_path(), payload)


def load_session() -> dict[str, Any] | None:
    data = _read_json(session_path())
    if not data or not isinstance(data.get("windows"), list):
        return None
    return data


def save_session(session: dict[str, Any]) -> None:
    try:
        _write_json(session_path(), session)
    except OSError:
        return
