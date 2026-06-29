from __future__ import annotations

import json
import math
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write(payload)
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def clean_text(value: Any, null_strings: set[str] | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if null_strings and text.casefold() in null_strings:
        return None
    return text


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def normalized_text(value: Any) -> str:
    text = clean_text(value) or ""
    decomposed = unicodedata.normalize("NFD", text)
    without_accents = "".join(
        char for char in decomposed
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.casefold().replace("-", " ").split())


def same_text(left: Any, right: Any) -> bool:
    return normalized_text(left) == normalized_text(right)


def add_alias(record: dict[str, Any], alias: Any) -> None:
    text = clean_text(alias)
    if not text or same_text(text, record.get("name")):
        return
    aliases = record.setdefault("aliases", [])
    if not any(same_text(text, current) for current in aliases):
        aliases.append(text)


def haversine_km(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371.0088
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
