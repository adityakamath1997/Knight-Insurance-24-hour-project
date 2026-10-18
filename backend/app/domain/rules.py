"""Deterministic R1-R5 evaluation. No model calls; semantics follow rules.json."""

from collections.abc import Mapping

from app.domain.models import (
    FieldName,
    FieldState,
    ReviewedField,
    RuleEvaluation,
    RuleInput,
    RuleResult,
    RuleStatus,
)

RADIUS_THRESHOLD_MILES = 150

Fields = Mapping[FieldName, ReviewedField]


def _inputs(fields: Fields, *names: FieldName) -> dict[str, RuleInput]:
    return {
        name.value: RuleInput(
            state=fields[name].state,
            value=fields[name].value,
            overridden=fields[name].override is not None,
        )
        for name in names
    }


def _describe(field: ReviewedField) -> str:
    if field.state == FieldState.KNOWN:
        return f"{field.name.value} = {field.value}"
    return f"{field.name.value} is {field.state.value}"


def _result(
    rule_id: str,
    name: str,
    status: RuleStatus,
    reason: str,
    fields: Fields,
    *names: FieldName,
) -> RuleResult:
    return RuleResult(
        id=rule_id,
        name=name,
        status=status,
        reason=reason,
        inputs=_inputs(fields, *names),
    )


def _r1(fields: Fields) -> RuleResult:
    names = (FieldName.BUSINESS_NAME, FieldName.REQUESTED_EFFECTIVE_DATE)
    missing = [n.value for n in names if fields[n].state == FieldState.MISSING]
    unresolved = [
        _describe(fields[n])
        for n in names
        if fields[n].state in (FieldState.INVALID, FieldState.CONFLICT)
    ]
    if missing:
        status, reason = "FLAG", f"Required field absent: {', '.join(missing)}."
    elif unresolved:
        status, reason = (
            "UNKNOWN",
            f"Required field unresolved: {'; '.join(unresolved)}.",
        )
    else:
        status, reason = (
            "PASS",
            "Business name and effective date are present and valid.",
        )
    return _result(
        "R1", "Required identity and effective date", status, reason, fields, *names
    )


def _r2(fields: Fields) -> RuleResult:
    declared = fields[FieldName.DECLARED_VEHICLE_COUNT]
    schedule = fields[FieldName.SCHEDULE_VEHICLE_COUNT]
    names = (FieldName.DECLARED_VEHICLE_COUNT, FieldName.SCHEDULE_VEHICLE_COUNT)
    unusable = [
        _describe(f) for f in (declared, schedule) if f.state != FieldState.KNOWN
    ]
    if unusable:
        status, reason = "UNKNOWN", f"Vehicle count not usable: {'; '.join(unusable)}."
    elif declared.value == schedule.value:
        status, reason = (
            "PASS",
            f"Declared count {declared.value} equals schedule count {schedule.value}.",
        )
    else:
        status, reason = (
            "FLAG",
            f"Declared count {declared.value} differs from schedule count {schedule.value}.",
        )
    return _result("R2", "Vehicle count reconciliation", status, reason, fields, *names)


def _r3(fields: Fields) -> RuleResult:
    radius = fields[FieldName.OPERATING_RADIUS_MILES]
    value = radius.value
    if radius.state != FieldState.KNOWN:
        status, reason = "UNKNOWN", f"Radius not usable: {_describe(radius)}."
    elif value <= RADIUS_THRESHOLD_MILES:
        status, reason = (
            "PASS",
            f"Radius {value} miles is within {RADIUS_THRESHOLD_MILES} miles.",
        )
    else:
        status, reason = (
            "FLAG",
            f"Radius {value} miles exceeds {RADIUS_THRESHOLD_MILES} miles.",
        )
    return _result(
        "R3",
        "Operating radius",
        status,
        reason,
        fields,
        FieldName.OPERATING_RADIUS_MILES,
    )


def _r4(fields: Fields) -> RuleResult:
    hazmat = fields[FieldName.HAZARDOUS_MATERIALS]
    if hazmat.state == FieldState.KNOWN and hazmat.value is False:
        status, reason = "PASS", "Hazardous materials explicitly No."
    elif hazmat.state == FieldState.KNOWN and hazmat.value is True:
        status, reason = "FLAG", "Hazardous materials explicitly Yes."
    else:
        status, reason = (
            "UNKNOWN",
            f"Hazardous materials answer not usable: {_describe(hazmat)}.",
        )
    return _result(
        "R4",
        "Hazardous materials",
        status,
        reason,
        fields,
        FieldName.HAZARDOUS_MATERIALS,
    )


def _r5(fields: Fields) -> RuleResult:
    loss_runs = fields[FieldName.LOSS_RUNS_PRESENT]
    if loss_runs.state == FieldState.KNOWN and loss_runs.value is True:
        status, reason = "PASS", "A readable loss runs/history report is attached."
    elif loss_runs.state == FieldState.KNOWN and loss_runs.value is False:
        status, reason = (
            "FLAG",
            "No loss runs/history report is attached; email statements do not count.",
        )
    else:
        status, reason = (
            "UNKNOWN",
            f"Loss runs attachment could not be determined: {_describe(loss_runs)}.",
        )
    return _result(
        "R5",
        "Loss runs attachment",
        status,
        reason,
        fields,
        FieldName.LOSS_RUNS_PRESENT,
    )


def evaluate_rules(fields: Fields) -> RuleEvaluation:
    rules = [_r1(fields), _r2(fields), _r3(fields), _r4(fields), _r5(fields)]
    overall = (
        "READY_FOR_REVIEW" if all(r.status == "PASS" for r in rules) else "NEEDS_REVIEW"
    )
    return RuleEvaluation(rules=rules, overall_status=overall)
