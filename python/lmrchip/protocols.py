"""Persistent protocol model and validation for the Microfluidics editor."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .errors import CommandError


PROTOCOL_VERSION = 1
POSITION_COUNT = 12
STEP_COUNT = 16
COLORS = {"teal", "orange", "green", "violet", "blue", "red", "grey"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def empty_protocol(name: str = "New protocol") -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "id": str(uuid.uuid4()),
        "name": name,
        "samples": [],
        "positions": [{"sample_id": None, "color": "grey"} for _ in range(POSITION_COUNT)],
        "steps": [{"sample_id": None, "flow_rate": None, "duration_seconds": None} for _ in range(STEP_COUNT)],
    }


def validate_protocol(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandError("INVALID_PROTOCOL", "Protocol must be an object.")
    protocol = dict(value)
    if protocol.get("version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        raise CommandError("INVALID_PROTOCOL", f"Unsupported protocol version: {protocol.get('version')}.")
    protocol["version"] = PROTOCOL_VERSION
    protocol_id = protocol.get("id")
    if not isinstance(protocol_id, str) or not ID_PATTERN.fullmatch(protocol_id):
        raise CommandError("INVALID_PROTOCOL", "Protocol id must contain 1-64 letters, numbers, '_' or '-'.")
    name = protocol.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise CommandError("INVALID_PROTOCOL", "Protocol name is required and must be at most 120 characters.")
    protocol["name"] = name.strip()

    samples_value = protocol.get("samples")
    if not isinstance(samples_value, list) or len(samples_value) > 100:
        raise CommandError("INVALID_PROTOCOL", "Samples must be a list containing at most 100 items.")
    samples: list[dict[str, str]] = []
    ids: set[str] = set()
    names: set[str] = set()
    for item in samples_value:
        if not isinstance(item, dict):
            raise CommandError("INVALID_PROTOCOL", "Every sample must be an object.")
        sample_id = item.get("id")
        sample_name = item.get("name")
        if not isinstance(sample_id, str) or not ID_PATTERN.fullmatch(sample_id):
            raise CommandError("INVALID_PROTOCOL", "Sample ids must contain 1-64 letters, numbers, '_' or '-'.")
        if sample_id in ids:
            raise CommandError("INVALID_PROTOCOL", f"Duplicate sample id: {sample_id}.")
        if not isinstance(sample_name, str) or not sample_name.strip() or len(sample_name.strip()) > 48:
            raise CommandError("INVALID_PROTOCOL", "Every sample needs a name of at most 48 characters.")
        normalized_name = sample_name.strip()
        if normalized_name.casefold() in names:
            raise CommandError("INVALID_PROTOCOL", f"Duplicate sample name: {normalized_name}.")
        ids.add(sample_id)
        names.add(normalized_name.casefold())
        samples.append({
            "id": sample_id,
            "name": normalized_name,
            "concentration": _text(item.get("concentration", ""), 100, "concentration"),
            "notes": _text(item.get("notes", ""), 300, "notes"),
        })
    protocol["samples"] = samples

    positions_value = protocol.get("positions")
    if not isinstance(positions_value, list) or len(positions_value) != POSITION_COUNT:
        raise CommandError("INVALID_PROTOCOL", "Protocol must contain exactly 12 carousel positions.")
    positions = []
    for item in positions_value:
        if not isinstance(item, dict):
            raise CommandError("INVALID_PROTOCOL", "Every carousel position must be an object.")
        sample_id = item.get("sample_id")
        color = item.get("color", "grey")
        if sample_id is not None and sample_id not in ids:
            raise CommandError("INVALID_PROTOCOL", f"Carousel references unknown sample: {sample_id}.")
        if color not in COLORS:
            raise CommandError("INVALID_PROTOCOL", f"Unsupported carousel color: {color}.")
        positions.append({"sample_id": sample_id, "color": color})
    protocol["positions"] = positions

    steps_value = protocol.get("steps")
    if not isinstance(steps_value, list) or len(steps_value) != STEP_COUNT:
        raise CommandError("INVALID_PROTOCOL", "Protocol must contain exactly 16 execution steps.")
    assigned_ids = {item["sample_id"] for item in positions if item["sample_id"] is not None}
    steps = []
    for item in steps_value:
        if not isinstance(item, dict):
            raise CommandError("INVALID_PROTOCOL", "Every execution step must be an object.")
        sample_id = item.get("sample_id")
        flow = item.get("flow_rate")
        duration = item.get("duration_seconds")
        if sample_id is None:
            if flow is not None or duration is not None:
                raise CommandError("INVALID_PROTOCOL", "Empty steps cannot contain flow or duration.")
            steps.append({"sample_id": None, "flow_rate": None, "duration_seconds": None})
            continue
        if sample_id not in ids:
            raise CommandError("INVALID_PROTOCOL", f"Step references unknown sample: {sample_id}.")
        if sample_id not in assigned_ids:
            raise CommandError("INVALID_PROTOCOL", f"Step sample is not assigned to a carousel position: {sample_id}.")
        steps.append({"sample_id": sample_id, "flow_rate": _positive(flow, "flow_rate", 10000), "duration_seconds": _positive(duration, "duration_seconds", 86400)})
    protocol["steps"] = steps
    return protocol


class ProtocolStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        configured = directory or os.environ.get("LMRCHIP_PROTOCOL_DIR")
        self.directory = Path(configured) if configured else Path(tempfile.gettempdir()) / "lmrchip-protocols"
        self.directory.mkdir(parents=True, exist_ok=True)

    def new(self, name: str = "New protocol") -> dict[str, Any]:
        return empty_protocol(name)

    def validate(self, protocol: Any) -> dict[str, Any]:
        return validate_protocol(protocol)

    def save(self, protocol: Any) -> dict[str, Any]:
        normalized = validate_protocol(protocol)
        target = self._path(normalized["id"])
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return normalized

    def load(self, protocol_id: str) -> dict[str, Any]:
        if not isinstance(protocol_id, str) or not ID_PATTERN.fullmatch(protocol_id):
            raise CommandError("INVALID_PROTOCOL", "Invalid protocol id.")
        target = self._path(protocol_id)
        if not target.is_file():
            raise CommandError("PROTOCOL_NOT_FOUND", f"Protocol {protocol_id!r} was not found.")
        try:
            return validate_protocol(json.loads(target.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            raise CommandError("INVALID_PROTOCOL", "Stored protocol is not valid JSON.") from error

    def list(self) -> list[dict[str, str]]:
        result = []
        for target in sorted(self.directory.glob("protocol_*.json")):
            try:
                protocol = self.load(target.stem.removeprefix("protocol_"))
                result.append({"id": protocol["id"], "name": protocol["name"]})
            except CommandError:
                continue
        return result

    def _path(self, protocol_id: str) -> Path:
        return self.directory / f"protocol_{protocol_id}.json"


def _text(value: Any, maximum: int, field: str) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise CommandError("INVALID_PROTOCOL", f"{field} must be text of at most {maximum} characters.")
    return value.strip()


def _positive(value: Any, field: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 < float(value) <= maximum:
        raise CommandError("INVALID_PROTOCOL", f"{field} must be a finite number greater than 0 and at most {maximum}.")
    return float(value)
