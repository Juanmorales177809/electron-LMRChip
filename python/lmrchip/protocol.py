"""JSON Lines protocol shared by the LMRChip service transports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class Request:
    request_id: str
    command: str
    payload: dict[str, Any]


class ProtocolError(ValueError):
    """A recoverable error caused by an invalid client message."""

    def __init__(self, code: str, message: str, request_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def parse_request(line: str) -> Request:
    """Parse and validate one protocol request."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise ProtocolError("INVALID_JSON", f"Invalid JSON: {error.msg}.") from error

    if not isinstance(message, dict):
        raise ProtocolError("INVALID_MESSAGE", "Message must be a JSON object.")

    request_id = message.get("id")
    error_request_id = request_id if isinstance(request_id, str) else None

    version = message.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProtocolError(
            "INVALID_MESSAGE",
            "Field 'version' must be an integer.",
            error_request_id,
        )
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            "UNSUPPORTED_VERSION",
            f"Protocol version {version} is not supported.",
            error_request_id,
        )

    if not isinstance(request_id, str) or not request_id.strip():
        raise ProtocolError(
            "INVALID_MESSAGE",
            "Field 'id' must be a non-empty string.",
            error_request_id,
        )

    command = message.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ProtocolError(
            "INVALID_MESSAGE",
            "Field 'command' must be a non-empty string.",
            request_id,
        )

    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise ProtocolError(
            "INVALID_MESSAGE",
            "Field 'payload' must be a JSON object.",
            request_id,
        )

    return Request(request_id=request_id, command=command, payload=payload)


def success_response(request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "id": request_id,
        "type": "response",
        "ok": True,
        "data": data,
    }


def error_response(
    request_id: str | None,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "id": request_id,
        "type": "response",
        "ok": False,
        "error": {"code": code, "message": message},
    }


def event_message(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build an asynchronous event that is not tied to a request id."""
    if not event.strip():
        raise ValueError("Event name must not be empty.")
    return {
        "version": PROTOCOL_VERSION,
        "type": "event",
        "event": event,
        "data": data,
    }


def encode_message(message: dict[str, Any]) -> str:
    """Encode one compact JSON message without the JSON Lines delimiter."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
