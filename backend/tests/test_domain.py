import pytest

from app.domain.models import Candidate, Evidence, FieldName, FieldState, ReviewedField
from app.domain.normalization import (
    normalize_value,
    reconcile_candidates,
    validate_override,
)
from app.domain.rules import evaluate_rules

F = FieldName
S = FieldState


def ev(file: str = "broker_email.txt") -> list[Evidence]:
    return [
        Evidence(source_file=file, locator="email body", excerpt_or_observation="x")
    ]


def cand(
    field: FieldName, raw: str, source: str = "email", file: str = "broker_email.txt"
) -> Candidate:
    state, value = normalize_value(field, raw)
    return Candidate(
        source=source,
        source_file=file,
        raw_value=raw,
        state=state,
        value=value,
        evidence=ev(file),
    )


def known(name: FieldName, value) -> ReviewedField:
    return ReviewedField(name=name, state=S.KNOWN, value=value)


def state_only(name: FieldName, state: FieldState) -> ReviewedField:
    return ReviewedField(name=name, state=state, value=None)


def all_pass_fields(**overrides: ReviewedField) -> dict[FieldName, ReviewedField]:
    fields = {
        F.BUSINESS_NAME: known(F.BUSINESS_NAME, "Acme LLC"),
        F.REQUESTED_EFFECTIVE_DATE: known(F.REQUESTED_EFFECTIVE_DATE, "2026-11-01"),
        F.GARAGING_STATE: known(F.GARAGING_STATE, "CA"),
        F.OPERATIONS_DESCRIPTION: known(F.OPERATIONS_DESCRIPTION, "Local delivery"),
        F.DECLARED_VEHICLE_COUNT: known(F.DECLARED_VEHICLE_COUNT, 3),
        F.OPERATING_RADIUS_MILES: known(F.OPERATING_RADIUS_MILES, 150.0),
        F.HAZARDOUS_MATERIALS: known(F.HAZARDOUS_MATERIALS, False),
        F.LOSS_RUNS_PRESENT: known(F.LOSS_RUNS_PRESENT, True),
        F.SCHEDULE_VEHICLE_COUNT: known(F.SCHEDULE_VEHICLE_COUNT, 3),
    }
    for key, value in overrides.items():
        fields[FieldName(key)] = value
    return fields


def rule(fields: dict[FieldName, ReviewedField], rule_id: str) -> str:
    evaluation = evaluate_rules(fields)
    return next(r.status for r in evaluation.rules if r.id == rule_id)


# --- normalization ---


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        (F.GARAGING_STATE, "California", (S.KNOWN, "CA")),
        (F.GARAGING_STATE, "ca", (S.KNOWN, "CA")),
        (F.GARAGING_STATE, "Calif-ish", (S.INVALID, None)),
        (F.REQUESTED_EFFECTIVE_DATE, "2026-11-01", (S.KNOWN, "2026-11-01")),
        (F.REQUESTED_EFFECTIVE_DATE, "2001-01-01", (S.KNOWN, "2001-01-01")),
        (F.REQUESTED_EFFECTIVE_DATE, "2026-02-30", (S.INVALID, None)),
        (F.REQUESTED_EFFECTIVE_DATE, "Not provided", (S.MISSING, None)),
        (F.DECLARED_VEHICLE_COUNT, "3", (S.KNOWN, 3)),
        (F.DECLARED_VEHICLE_COUNT, "3.0", (S.KNOWN, 3)),
        (F.DECLARED_VEHICLE_COUNT, "0", (S.KNOWN, 0)),
        (F.DECLARED_VEHICLE_COUNT, "-1", (S.INVALID, None)),
        (F.DECLARED_VEHICLE_COUNT, "2.5", (S.INVALID, None)),
        (F.OPERATING_RADIUS_MILES, "150", (S.KNOWN, 150.0)),
        (F.OPERATING_RADIUS_MILES, "150.0", (S.KNOWN, 150.0)),
        (F.OPERATING_RADIUS_MILES, "about 150", (S.INVALID, None)),
        (F.OPERATING_RADIUS_MILES, "-5", (S.INVALID, None)),
        (F.OPERATING_RADIUS_MILES, "Not provided", (S.MISSING, None)),
        (F.HAZARDOUS_MATERIALS, "No", (S.KNOWN, False)),
        (F.HAZARDOUS_MATERIALS, "Yes", (S.KNOWN, True)),
        (F.HAZARDOUS_MATERIALS, "possibly", (S.INVALID, None)),
        (F.HAZARDOUS_MATERIALS, "Not provided", (S.MISSING, None)),
        (F.BUSINESS_NAME, "  Acme LLC ", (S.KNOWN, "Acme LLC")),
        (F.BUSINESS_NAME, "", (S.MISSING, None)),
    ],
)
def test_normalize_value(field, raw, expected):
    assert normalize_value(field, raw) == expected


def test_matching_values_across_sources_are_known():
    field = reconcile_candidates(
        F.OPERATIONS_DESCRIPTION,
        [
            cand(F.OPERATIONS_DESCRIPTION, "Local delivery of packaged retail goods."),
            cand(
                F.OPERATIONS_DESCRIPTION,
                "local delivery of packaged retail goods",
                "pdf",
                "application.pdf",
            ),
        ],
        inspected_sources=["broker_email.txt", "application.pdf"],
    )
    assert field.state == S.KNOWN
    assert field.value == "Local delivery of packaged retail goods."


def test_case_insensitive_business_name_and_state_name_match():
    name = reconcile_candidates(
        F.BUSINESS_NAME,
        [
            cand(F.BUSINESS_NAME, "Acme LLC"),
            cand(F.BUSINESS_NAME, "ACME llc", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    state = reconcile_candidates(
        F.GARAGING_STATE,
        [
            cand(F.GARAGING_STATE, "CA"),
            cand(F.GARAGING_STATE, "California", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    assert (name.state, state.state, state.value) == (S.KNOWN, S.KNOWN, "CA")


def test_source_conflict_keeps_both_alternatives_and_null_value():
    field = reconcile_candidates(
        F.OPERATING_RADIUS_MILES,
        [
            cand(F.OPERATING_RADIUS_MILES, "180"),
            cand(F.OPERATING_RADIUS_MILES, "80", "pdf", "application.pdf"),
        ],
        inspected_sources=["broker_email.txt", "application.pdf"],
    )
    assert field.state == S.CONFLICT
    assert field.value is None
    assert [c.value for c in field.candidates] == [180.0, 80.0]
    assert all(c.evidence for c in field.candidates)


def test_numeric_equivalence_is_not_a_conflict():
    field = reconcile_candidates(
        F.OPERATING_RADIUS_MILES,
        [
            cand(F.OPERATING_RADIUS_MILES, "150"),
            cand(F.OPERATING_RADIUS_MILES, "150.0", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    assert (field.state, field.value) == (S.KNOWN, 150.0)


def test_missing_mention_in_one_source_is_not_a_conflict():
    field = reconcile_candidates(
        F.HAZARDOUS_MATERIALS,
        [
            cand(F.HAZARDOUS_MATERIALS, "Not provided"),
            cand(F.HAZARDOUS_MATERIALS, "No", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    assert (field.state, field.value) == (S.KNOWN, False)


def test_missing_everywhere_lists_inspected_sources():
    field = reconcile_candidates(
        F.REQUESTED_EFFECTIVE_DATE,
        [cand(F.REQUESTED_EFFECTIVE_DATE, "Not provided")],
        inspected_sources=["broker_email.txt", "application.pdf"],
    )
    assert field.state == S.MISSING
    assert field.value is None
    assert field.inspected_sources == ["broker_email.txt", "application.pdf"]


def test_invalid_candidate_takes_precedence_over_conflict_and_known():
    field = reconcile_candidates(
        F.OPERATING_RADIUS_MILES,
        [
            cand(F.OPERATING_RADIUS_MILES, "100"),
            cand(F.OPERATING_RADIUS_MILES, "about 150", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    assert (field.state, field.value) == (S.INVALID, None)


def test_no_candidates_is_missing():
    field = reconcile_candidates(
        F.GARAGING_STATE, [], inspected_sources=["broker_email.txt"]
    )
    assert field.state == S.MISSING


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (F.DECLARED_VEHICLE_COUNT, 4, 4),
        (F.OPERATING_RADIUS_MILES, 150, 150.0),
        (F.REQUESTED_EFFECTIVE_DATE, "2026-11-01", "2026-11-01"),
        (F.GARAGING_STATE, "california", "CA"),
        (F.HAZARDOUS_MATERIALS, False, False),
        (F.BUSINESS_NAME, None, None),
    ],
)
def test_validate_override_accepts_contract_types(field, value, expected):
    assert validate_override(field, value) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (F.DECLARED_VEHICLE_COUNT, -1),
        (F.DECLARED_VEHICLE_COUNT, 2.5),
        (F.DECLARED_VEHICLE_COUNT, True),
        (F.OPERATING_RADIUS_MILES, "150"),
        (F.OPERATING_RADIUS_MILES, -1),
        (F.REQUESTED_EFFECTIVE_DATE, "2026-02-30"),
        (F.HAZARDOUS_MATERIALS, "No"),
        (F.GARAGING_STATE, "XX"),
        (F.BUSINESS_NAME, "   "),
    ],
)
def test_validate_override_rejects_wrong_types(field, value):
    with pytest.raises(ValueError):
        validate_override(field, value)


# --- rules ---


def test_all_pass_is_ready_for_review():
    evaluation = evaluate_rules(all_pass_fields())
    assert [r.status for r in evaluation.rules] == ["PASS"] * 5
    assert evaluation.overall_status == "READY_FOR_REVIEW"


def test_r1_missing_required_field_flags():
    fields = all_pass_fields(
        requested_effective_date=state_only(F.REQUESTED_EFFECTIVE_DATE, S.MISSING)
    )
    assert rule(fields, "R1") == "FLAG"
    assert evaluate_rules(fields).overall_status == "NEEDS_REVIEW"


def test_r1_missing_takes_precedence_over_conflict():
    fields = all_pass_fields(
        business_name=state_only(F.BUSINESS_NAME, S.CONFLICT),
        requested_effective_date=state_only(F.REQUESTED_EFFECTIVE_DATE, S.MISSING),
    )
    assert rule(fields, "R1") == "FLAG"


@pytest.mark.parametrize("state", [S.CONFLICT, S.INVALID])
def test_r1_conflict_or_invalid_without_missing_is_unknown(state):
    fields = all_pass_fields(business_name=state_only(F.BUSINESS_NAME, state))
    assert rule(fields, "R1") == "UNKNOWN"


@pytest.mark.parametrize(
    ("declared", "schedule", "expected"),
    [(3, 3, "PASS"), (4, 3, "FLAG"), (0, 0, "PASS"), (0, 1, "FLAG")],
)
def test_r2_vehicle_counts(declared, schedule, expected):
    fields = all_pass_fields(
        declared_vehicle_count=known(F.DECLARED_VEHICLE_COUNT, declared),
        schedule_vehicle_count=known(F.SCHEDULE_VEHICLE_COUNT, schedule),
    )
    assert rule(fields, "R2") == expected


@pytest.mark.parametrize("state", [S.MISSING, S.INVALID, S.CONFLICT])
def test_r2_unusable_count_is_unknown(state):
    fields = all_pass_fields(
        schedule_vehicle_count=state_only(F.SCHEDULE_VEHICLE_COUNT, state)
    )
    assert rule(fields, "R2") == "UNKNOWN"


@pytest.mark.parametrize(
    ("radius", "expected"),
    [(150, "PASS"), (150.0, "PASS"), (150.1, "FLAG"), (0, "PASS")],
)
def test_r3_150_mile_threshold(radius, expected):
    fields = all_pass_fields(
        operating_radius_miles=known(F.OPERATING_RADIUS_MILES, radius)
    )
    assert rule(fields, "R3") == expected


@pytest.mark.parametrize("state", [S.MISSING, S.INVALID, S.CONFLICT])
def test_r3_unusable_radius_is_unknown(state):
    fields = all_pass_fields(
        operating_radius_miles=state_only(F.OPERATING_RADIUS_MILES, state)
    )
    assert rule(fields, "R3") == "UNKNOWN"


def test_r3_conflict_is_unknown_even_if_all_alternatives_pass():
    conflict = reconcile_candidates(
        F.OPERATING_RADIUS_MILES,
        [
            cand(F.OPERATING_RADIUS_MILES, "100"),
            cand(F.OPERATING_RADIUS_MILES, "120", "pdf", "application.pdf"),
        ],
        inspected_sources=[],
    )
    assert rule(all_pass_fields(operating_radius_miles=conflict), "R3") == "UNKNOWN"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        (known(F.HAZARDOUS_MATERIALS, False), "PASS"),
        (known(F.HAZARDOUS_MATERIALS, True), "FLAG"),
        (state_only(F.HAZARDOUS_MATERIALS, S.MISSING), "UNKNOWN"),
        (state_only(F.HAZARDOUS_MATERIALS, S.INVALID), "UNKNOWN"),
        (state_only(F.HAZARDOUS_MATERIALS, S.CONFLICT), "UNKNOWN"),
    ],
)
def test_r4_hazardous_materials(field, expected):
    assert rule(all_pass_fields(hazardous_materials=field), "R4") == expected


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        (known(F.LOSS_RUNS_PRESENT, True), "PASS"),
        (known(F.LOSS_RUNS_PRESENT, False), "FLAG"),
        (state_only(F.LOSS_RUNS_PRESENT, S.INVALID), "UNKNOWN"),
    ],
)
def test_r5_loss_runs(field, expected):
    assert rule(all_pass_fields(loss_runs_present=field), "R5") == expected


def test_rule_results_expose_inputs_and_reason():
    evaluation = evaluate_rules(
        all_pass_fields(declared_vehicle_count=known(F.DECLARED_VEHICLE_COUNT, 4))
    )
    r2 = next(r for r in evaluation.rules if r.id == "R2")
    assert r2.inputs["declared_vehicle_count"].value == 4
    assert r2.inputs["schedule_vehicle_count"].value == 3
    assert "4" in r2.reason and "3" in r2.reason
