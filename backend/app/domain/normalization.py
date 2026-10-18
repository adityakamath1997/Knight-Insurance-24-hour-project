import re
from collections.abc import Sequence
from datetime import date, datetime

from app.domain.models import (
    Candidate,
    FieldName,
    FieldState,
    FieldValue,
    ReviewedField,
)

PLACEHOLDERS = frozenset({"", "not provided"})
# Upper bound so numbers stay finite and storable.
MAX_NUMBER = 10**15

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
_STATE_BY_NAME = {name.casefold(): code for code, name in US_STATES.items()}

_COUNT = re.compile(r"^([0-9]{1,15})(?:\.0+)?$")
_RADIUS = re.compile(r"^[0-9]{1,15}(?:\.[0-9]{1,15})?$")
_YES = frozenset({"yes", "true"})
_NO = frozenset({"no", "false"})

_TEXT_FIELDS = (FieldName.BUSINESS_NAME, FieldName.OPERATIONS_DESCRIPTION)
_COUNT_FIELDS = (FieldName.DECLARED_VEHICLE_COUNT, FieldName.SCHEDULE_VEHICLE_COUNT)
_BOOL_FIELDS = (FieldName.HAZARDOUS_MATERIALS, FieldName.LOSS_RUNS_PRESENT)

Normalized = tuple[FieldState, FieldValue]
_INVALID: Normalized = (FieldState.INVALID, None)


def _state_code(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned.upper() in US_STATES:
        return cleaned.upper()
    return _STATE_BY_NAME.get(cleaned.casefold())


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_value(field: FieldName, raw: str | None) -> Normalized:
    """Convert verbatim source text to the contract type; never guess."""
    text = (raw or "").strip()
    if text.casefold() in PLACEHOLDERS:
        return FieldState.MISSING, None

    if field in _TEXT_FIELDS:
        return FieldState.KNOWN, text
    if field == FieldName.GARAGING_STATE:
        code = _state_code(text)
        return (FieldState.KNOWN, code) if code else _INVALID
    if field == FieldName.REQUESTED_EFFECTIVE_DATE:
        parsed = _parse_date(text)
        return (FieldState.KNOWN, parsed.isoformat()) if parsed else _INVALID
    if field in _COUNT_FIELDS:
        match = _COUNT.match(text)
        return (FieldState.KNOWN, int(match.group(1))) if match else _INVALID
    if field == FieldName.OPERATING_RADIUS_MILES:
        return (FieldState.KNOWN, float(text)) if _RADIUS.match(text) else _INVALID
    if field in _BOOL_FIELDS:
        lowered = text.casefold()
        if lowered in _YES:
            return FieldState.KNOWN, True
        if lowered in _NO:
            return FieldState.KNOWN, False
        return _INVALID
    raise ValueError(f"Unknown field {field}")


def validate_override(field: FieldName, value: object) -> FieldValue:
    """Validate a reviewer-supplied typed value; raise ValueError when it breaks the contract."""
    if value is None:
        return None
    if field in _TEXT_FIELDS:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(f"{field} must be a non-empty string")
    if field == FieldName.GARAGING_STATE:
        code = _state_code(value) if isinstance(value, str) else None
        if code:
            return code
        raise ValueError(f"{field} must be a US state code or name")
    if field == FieldName.REQUESTED_EFFECTIVE_DATE:
        parsed = _parse_date(value.strip()) if isinstance(value, str) else None
        if parsed:
            return parsed.isoformat()
        raise ValueError(f"{field} must be a valid date")
    if field in _COUNT_FIELDS:
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_NUMBER
        ):
            return value
        raise ValueError(f"{field} must be a nonnegative integer")
    if field == FieldName.OPERATING_RADIUS_MILES:
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_NUMBER
        ):
            return float(value)
        raise ValueError(f"{field} must be a nonnegative number")
    if field in _BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        raise ValueError(f"{field} must be true or false")
    raise ValueError(f"Unknown field {field}")


def comparison_key(field: FieldName, value: FieldValue) -> object:
    """Key under which harmless differences compare equal: case for text, and a
    trailing period for the free-text operations description."""
    if field == FieldName.BUSINESS_NAME and isinstance(value, str):
        return value.casefold()
    if field == FieldName.OPERATIONS_DESCRIPTION and isinstance(value, str):
        return value.casefold().rstrip(".")
    return value


def reconcile_candidates(
    field: FieldName, candidates: Sequence[Candidate], inspected_sources: Sequence[str]
) -> ReviewedField:
    """Precedence: any INVALID > distinct values (CONFLICT) > one value (KNOWN) > MISSING."""
    reviewed = ReviewedField(
        name=field,
        state=FieldState.MISSING,
        candidates=list(candidates),
        inspected_sources=list(inspected_sources),
    )
    if any(c.state == FieldState.INVALID for c in candidates):
        reviewed.state = FieldState.INVALID
        return reviewed

    known = [c for c in candidates if c.state == FieldState.KNOWN]
    distinct = {comparison_key(field, c.value) for c in known}
    if len(distinct) > 1:
        reviewed.state = FieldState.CONFLICT
    elif known:
        reviewed.state = FieldState.KNOWN
        reviewed.value = known[0].value
    return reviewed
