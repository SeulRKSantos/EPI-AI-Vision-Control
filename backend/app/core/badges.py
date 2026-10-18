"""Badge identifier format.

The gate reports a card's UID as uppercase hex ("769F8205"). Identifiers are
normalized to that form wherever they enter the system — typed in the panel
or published by a gate — so a badge registered as "769f8205 " still matches
the reader.
"""


def normalize_badge(value: object) -> object:
    """Trims and uppercases a badge id; leaves anything else to validation."""
    if isinstance(value, str):
        return value.strip().upper()
    return value
