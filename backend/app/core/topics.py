"""MQTT topic definitions.

Kept in one place because these strings are a contract shared with the
firmware and the vision service — a change here breaks both.
"""

import re

BADGE_SCAN = "access/{gate_code}/badge/scan"
VISION_REQUEST = "vision/{gate_code}/request"
VISION_RESULT = "vision/{gate_code}/result"
ACCESS_DECISION = "access/{gate_code}/decision"
GATE_STATUS = "access/{gate_code}/status"

# Wildcard forms the backend subscribes to: one gate or a hundred, the
# subscription does not change.
BADGE_SCAN_SUB = "access/+/badge/scan"
VISION_RESULT_SUB = "vision/+/result"
GATE_STATUS_SUB = "access/+/status"

_GATE_FROM_TOPIC = re.compile(r"^[^/]+/(?P<gate_code>[^/]+)/")


def badge_scan(gate_code: str) -> str:
    return BADGE_SCAN.format(gate_code=gate_code)


def vision_request(gate_code: str) -> str:
    return VISION_REQUEST.format(gate_code=gate_code)


def vision_result(gate_code: str) -> str:
    return VISION_RESULT.format(gate_code=gate_code)


def access_decision(gate_code: str) -> str:
    return ACCESS_DECISION.format(gate_code=gate_code)


def gate_status(gate_code: str) -> str:
    return GATE_STATUS.format(gate_code=gate_code)


def extract_gate_code(topic: str) -> str | None:
    """Pull the gate identifier out of a concrete topic string."""
    match = _GATE_FROM_TOPIC.match(topic)
    return match.group("gate_code") if match else None
