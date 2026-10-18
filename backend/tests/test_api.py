import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.schemas import NarrativeOutput
from app.domain.models import Candidate, Evidence, FieldName, FieldState
from app.main import create_app
from app.services.documents import PreparedDocument, PreparedPacket
from app.services.review import SourceRun
from app.settings import Settings

F = FieldName
SAMPLES = Path(__file__).parents[2] / (
    "Knight_Insurance_24_Hour_Project/candidate_materials/sample_submissions"
)
# (email label, application form label) as they appear in the sample packets.
LABELS = {
    F.BUSINESS_NAME: ("Business name", "Business name"),
    F.REQUESTED_EFFECTIVE_DATE: (
        "Requested effective date",
        "Requested effective date",
    ),
    F.GARAGING_STATE: ("Garaging state", "Garaging state"),
    F.OPERATIONS_DESCRIPTION: ("Operations", "Operations description"),
    F.DECLARED_VEHICLE_COUNT: ("Declared vehicle count", "Declared vehicle count"),
    F.OPERATING_RADIUS_MILES: ("Operating radius miles", "Operating radius miles"),
    F.HAZARDOUS_MATERIALS: ("Hazardous materials", "Hazardous materials"),
}
CSV = "vehicle_id,vin,year,make,model\r\nA,V1,2022,M,X\r\n"


def candidate(source: str, file: str, raw: str, locator: str) -> Candidate:
    return Candidate(
        source=source,
        source_file=file,
        raw_value=raw,
        state=FieldState.KNOWN,
        evidence=[
            Evidence(source_file=file, locator=locator, excerpt_or_observation=raw)
        ],
    )


def label_run(source: str, docs: list[PreparedDocument]) -> SourceRun:
    """Stands in for an extraction agent: verbatim values read from the packet itself."""
    found: dict[FieldName, list[Candidate]] = {}
    for doc in docs:
        for field, (email_label, form_label) in LABELS.items():
            pattern = (
                rf"^{email_label}: (.+)$"
                if source == "email"
                else rf"^{form_label}\n(.+)$"
            )
            if match := re.search(pattern, doc.text or "", re.MULTILINE):
                found.setdefault(field, []).append(
                    candidate(source, doc.file_name, match.group(1).strip(), form_label)
                )
    return SourceRun(source=source, status="SUCCEEDED", attempts=1, candidates=found)


def attachment_run(packet: PreparedPacket) -> SourceRun:
    report = next(
        (d for d in packet.attachments if "Loss runs report" in (d.text or "")), None
    )
    found = (
        candidate("attachments", report.file_name, "Yes", "page 1")
        if report
        else Candidate(
            source="attachments",
            source_file="attachment inventory",
            raw_value="No",
            state=FieldState.KNOWN,
            evidence=[
                Evidence(
                    source_file="attachment inventory",
                    locator="all attachments",
                    excerpt_or_observation="; ".join(packet.attachment_inventory),
                )
            ],
        )
    )
    return SourceRun(
        source="attachments",
        status="SUCCEEDED",
        attempts=1,
        candidates={F.LOSS_RUNS_PRESENT: [found]},
    )


def sample_extractor(packet: PreparedPacket, progress=None) -> list[SourceRun]:
    pdfs = [d for d in packet.attachments if d.kind == "pdf"]
    forms = [d for d in pdfs if "Commercial auto application" in (d.text or "")]
    return [
        label_run("email", [packet.email])
        if packet.email
        else SourceRun(source="email", status="SKIPPED"),
        label_run("pdf", forms) if pdfs else SourceRun(source="pdf", status="SKIPPED"),
        attachment_run(packet)
        if packet.attachments
        else SourceRun(source="attachments", status="SKIPPED"),
    ]


def failing_extractor(packet: PreparedPacket, progress=None) -> list[SourceRun]:
    return [
        SourceRun(source=source, status="MODEL_FAILED", attempts=1, error="timeout")
        for source in ("email", "pdf", "attachments")
    ]


def writer(report: dict, draft: str, progress=None) -> NarrativeOutput:
    return NarrativeOutput(
        summary=f"Status {report['overall_status']}",
        draft_email=f"Please send {len(report['items_to_request'])} items",
    )


def failing_writer(report: dict, draft: str, progress=None) -> NarrativeOutput:
    raise ConnectionError("model unavailable")


def client(tmp_path: Path, extractor=sample_extractor, narrative=writer) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path), extractor, narrative))


def sample_files(name: str) -> list[tuple[str, tuple[str, bytes]]]:
    return [
        ("files", (path.name, path.read_bytes()))
        for path in sorted((SAMPLES / name).iterdir())
    ]


def submit(api: TestClient, name: str) -> dict:
    response = api.post("/submissions", files=sample_files(name))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("packet", "statuses", "overall"),
    [
        ("SUB-A", ["PASS"] * 5, "READY_FOR_REVIEW"),
        ("SUB-B", ["FLAG", "PASS", "UNKNOWN", "UNKNOWN", "FLAG"], "NEEDS_REVIEW"),
        ("SUB-C", ["PASS", "FLAG", "UNKNOWN", "UNKNOWN", "FLAG"], "NEEDS_REVIEW"),
    ],
)
def test_sample_packets_produce_expected_rule_outcomes(
    tmp_path: Path, packet: str, statuses: list[str], overall: str
) -> None:
    detail = submit(client(tmp_path), packet)
    assert [rule["status"] for rule in detail["rules"]] == statuses
    assert detail["overall_status"] == overall
    assert detail["narrative"]["summary"] == f"Status {overall}"


def test_sample_conflicts_and_missing_values_keep_evidence(tmp_path: Path) -> None:
    api = client(tmp_path)
    c = submit(api, "SUB-C")["fields"]
    radius = c[F.OPERATING_RADIUS_MILES]
    assert (radius["state"], radius["value"]) == ("CONFLICT", None)
    assert [x["value"] for x in radius["candidates"]] == [180.0, 80.0]
    assert c[F.HAZARDOUS_MATERIALS]["state"] == "CONFLICT"
    assert (
        c[F.SCHEDULE_VEHICLE_COUNT]["value"],
        c[F.DECLARED_VEHICLE_COUNT]["value"],
    ) == (3, 4)

    b = submit(api, "SUB-B")["fields"]
    date = b[F.REQUESTED_EFFECTIVE_DATE]
    assert (date["state"], date["value"]) == ("MISSING", None)
    assert date["inspected_sources"]
    loss = b[F.LOSS_RUNS_PRESENT]
    assert (loss["state"], loss["value"]) == ("KNOWN", False)


def test_switching_packets_does_not_leak_data(tmp_path: Path) -> None:
    api = client(tmp_path)
    c = submit(api, "SUB-C")
    a = submit(api, "SUB-A")

    assert a["id"] != c["id"]
    assert (
        a["fields"][F.BUSINESS_NAME]["value"] == "Pacific Harbor Delivery Example LLC"
    )
    assert "Metro Route" not in str(a)
    assert api.get(f"/submissions/{c['id']}").json() == c


@pytest.mark.parametrize(
    ("data", "files"),
    [
        ({}, []),
        ({"email_text": "  "}, []),
        ({"email_text": "Hi"}, [("files", ("broker_email.txt", b"Hi"))]),
        ({}, [("files", ("a.pdf", b"x")), ("files", ("A.pdf", b"y"))]),
        ({}, [("files", ("manifest.txt", b"Hi"))]),
    ],
)
def test_invalid_packets_are_rejected(tmp_path: Path, data: dict, files: list) -> None:
    response = client(tmp_path).post("/submissions", data=data, files=files)
    assert response.status_code == 400


def test_email_only_and_file_only_packets_are_accepted(tmp_path: Path) -> None:
    api = client(tmp_path)
    email_only = api.post("/submissions", data={"email_text": "Hello"})
    assert email_only.status_code == 201
    assert [r["status"] for r in email_only.json()["source_runs"]] == [
        "SUCCEEDED",
        "SKIPPED",
        "SKIPPED",
    ]
    loss = email_only.json()["fields"][F.LOSS_RUNS_PRESENT]
    assert (loss["state"], loss["value"]) == ("KNOWN", False)
    assert email_only.json()["rules"][4]["status"] == "FLAG"

    file_only = api.post(
        "/submissions",
        files=[("files", ("C:\\temp\\vehicles.csv", CSV.encode()))],
    )
    assert file_only.status_code == 201
    detail = file_only.json()
    assert detail["fields"][F.SCHEDULE_VEHICLE_COUNT]["value"] == 1
    assert [d["file_name"] for d in detail["documents"]] == ["vehicles.csv"]


def test_api_starts_without_a_model_and_records_the_failure(tmp_path: Path) -> None:
    api = TestClient(create_app(Settings(data_dir=tmp_path, llm_model=None)))
    detail = submit(api, "SUB-A")

    assert {r["status"] for r in detail["source_runs"]} == {"MODEL_FAILED"}
    assert "LLM_MODEL" in detail["source_runs"][0]["error"]
    assert detail["narrative"]["status"] == "FAILED"
    assert detail["fields"][F.SCHEDULE_VEHICLE_COUNT]["value"] == 3


def test_uploaded_txt_with_attachments_is_the_email(tmp_path: Path) -> None:
    detail = submit(client(tmp_path), "SUB-A")
    email = detail["documents"][0]
    assert (email["file_name"], email["kind"]) == ("broker_email.txt", "email")


def test_model_failures_are_recorded_not_5xx(tmp_path: Path) -> None:
    api = client(tmp_path, failing_extractor, failing_writer)
    response = api.post("/submissions", files=sample_files("SUB-A"))

    assert response.status_code == 201
    detail = response.json()
    assert {r["status"] for r in detail["source_runs"]} == {"MODEL_FAILED"}
    assert detail["fields"][F.BUSINESS_NAME]["state"] == "INVALID"
    assert detail["fields"][F.SCHEDULE_VEHICLE_COUNT]["value"] == 3
    assert detail["rules"][1]["status"] == "UNKNOWN"
    narrative = detail["narrative"]
    assert (narrative["status"], narrative["summary"], narrative["draft"]["body"]) == (
        "FAILED",
        None,
        "",
    )
    assert "model unavailable" in narrative["error"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("PATCH", "/fields/business_name", {"value": "X"}),
        ("PATCH", "/draft", {"body": "x"}),
        ("POST", "/narrative/regenerate", None),
    ],
)
def test_unknown_submission_is_404(
    tmp_path: Path, method: str, path: str, body: dict | None
) -> None:
    response = client(tmp_path).request(method, f"/submissions/nope{path}", json=body)
    assert response.status_code == 404


def test_override_reruns_rules_and_rejects_read_only_or_wrong_input(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)
    sid = submit(api, "SUB-C")["id"]
    url = f"/submissions/{sid}/fields"

    detail = api.patch(
        f"{url}/schedule_vehicle_count", json={"value": 4, "note": "Broker sent 4th"}
    ).json()
    count = detail["fields"][F.SCHEDULE_VEHICLE_COUNT]
    assert (count["value"], count["override"]["original_value"]) == (4, 3)
    assert detail["rules"][1]["status"] == "PASS"
    assert [s["trigger"] for s in detail["snapshots"]] == [
        "initial",
        "override:schedule_vehicle_count",
    ]

    assert (
        api.patch(f"{url}/declared_vehicle_count", json={"value": "three"}).status_code
        == 422
    )
    assert api.patch(f"{url}/not_a_field", json={"value": 1}).status_code == 422
    infinite = api.patch(
        f"{url}/operating_radius_miles",
        content='{"value": 1e999}',
        headers={"content-type": "application/json"},
    )
    assert infinite.status_code == 422
    assert (
        api.patch(f"{url}/business_name", json={"note": "no value"}).status_code == 422
    )
    assert (
        api.patch(
            f"{url}/business_name", json={"value": "X", "evidence": []}
        ).status_code
        == 422
    )
    assert (
        api.patch(f"/submissions/{sid}/rules/R1", json={"status": "PASS"}).status_code
        == 404
    )

    assert client(tmp_path).get(f"/submissions/{sid}").json() == detail


def test_draft_edit_and_regenerate_persist(tmp_path: Path) -> None:
    api = client(tmp_path)
    sid = submit(api, "SUB-B")["id"]

    edited = api.patch(f"/submissions/{sid}/draft", json={"body": "My draft"}).json()
    assert edited["narrative"]["draft"] == {
        "body": "My draft",
        "edited": True,
        "stale": False,
    }
    assert client(tmp_path).get(f"/submissions/{sid}").json() == edited

    regenerated = api.post(f"/submissions/{sid}/narrative/regenerate").json()
    assert regenerated["narrative"]["draft"]["edited"] is False
    assert regenerated["narrative"]["draft"]["body"].startswith("Please send")


def test_cors_allows_only_the_frontend_origin(tmp_path: Path) -> None:
    api = client(tmp_path)
    headers = {"Access-Control-Request-Method": "POST"}
    allowed = api.options(
        "/submissions", headers=headers | {"Origin": "http://localhost:3000"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = api.options(
        "/submissions", headers=headers | {"Origin": "http://evil.example"}
    )
    assert "access-control-allow-origin" not in denied.headers


def stream(api: TestClient, **kwargs) -> list[tuple[str, dict]]:
    """POST /submissions/stream and parse the SSE body into (event, data) pairs."""
    import json

    with api.stream("POST", "/submissions/stream", **kwargs) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_stream_reports_progress_then_one_result(tmp_path: Path) -> None:
    api = client(tmp_path)
    events = stream(api, files=sample_files("SUB-A"))

    kinds = [name for name, _ in events]
    assert kinds[-1] == "result"
    assert kinds.count("result") == 1 and "error" not in kinds
    assert set(kinds[:-1]) == {"progress"}
    assert [d["stage"] for n, d in events[:-1] if d["kind"] == "stage_started"] == [
        "prepare",
        "rules",
        "narrative",
    ]
    detail = events[-1][1]
    assert api.get(f"/submissions/{detail['id']}").json() == detail


def test_stream_forwards_events_emitted_by_the_extractor(tmp_path: Path) -> None:
    from app.progress import ProgressEvent

    def noisy(packet: PreparedPacket, progress=None) -> list[SourceRun]:
        progress(
            ProgressEvent(
                kind="tool_call",
                stage="extraction",
                source="email",
                label="Reading pasted broker email",
            )
        )
        return sample_extractor(packet)

    events = stream(client(tmp_path, noisy), files=sample_files("SUB-A"))

    assert ("progress", "Reading pasted broker email") in [
        (n, d["label"]) for n, d in events if n == "progress"
    ]


def test_stream_reports_invalid_packet_as_a_single_error(tmp_path: Path) -> None:
    events = stream(client(tmp_path))

    names = [name for name, _ in events]
    assert names[-1] == "error" and names.count("error") == 1
    assert set(names[:-1]) <= {"progress"}
    assert isinstance(events[-1][1]["detail"], str) and events[-1][1]["detail"]


def test_stream_ends_with_result_when_the_model_fails(tmp_path: Path) -> None:
    events = stream(
        client(tmp_path, failing_extractor, failing_writer),
        data={"email_text": "Business name: X"},
    )

    assert events[-1][0] == "result"
    assert {r["status"] for r in events[-1][1]["source_runs"]} == {"MODEL_FAILED"}


def test_stream_forwards_agent_message_and_tool_content(tmp_path: Path) -> None:
    from app.progress import ProgressEvent

    def noisy(packet: PreparedPacket, progress=None) -> list[SourceRun]:
        progress(
            ProgressEvent(
                kind="tool_result",
                stage="extraction",
                source="email",
                label="Read ok",
                tool="read_file",
                detail="Business name: Secret Hauling Co",
            )
        )
        return sample_extractor(packet)

    events = stream(client(tmp_path, noisy), data={"email_text": "Hi"})

    [forwarded] = [d for n, d in events if n == "progress" and d.get("tool")]
    assert forwarded["detail"] == "Business name: Secret Hauling Co"
    assert forwarded["truncated"] is False


def listing(api: TestClient, **params) -> list[dict]:
    response = api.get("/submissions", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_list_defaults_to_newest_first_with_summary_fields(tmp_path: Path) -> None:
    api = client(tmp_path)
    a, b = submit(api, "SUB-A"), submit(api, "SUB-B")

    items = listing(api)

    assert [i["id"] for i in items] == [b["id"], a["id"]]
    newest = items[1]
    assert newest["business_name"] == "Pacific Harbor Delivery Example LLC"
    assert newest["overall_status"] == "READY_FOR_REVIEW"
    assert newest["document_count"] == len(a["documents"])
    assert newest["created_at"] == a["created_at"]


def test_list_sorts_by_id_and_status_and_business_name(tmp_path: Path) -> None:
    api = client(tmp_path)
    ids = [submit(api, name)["id"] for name in ("SUB-A", "SUB-B", "SUB-C")]

    assert [i["id"] for i in listing(api, sort="id", order="asc")] == sorted(ids)
    assert [i["id"] for i in listing(api, sort="id", order="desc")] == sorted(
        ids, reverse=True
    )
    statuses = [i["overall_status"] for i in listing(api, sort="status", order="asc")]
    assert statuses == sorted(statuses)
    names = [
        i["business_name"] for i in listing(api, sort="business_name", order="asc")
    ]
    assert names == sorted(names, key=str.lower)
    assert listing(api, sort="created_at", order="asc")[0]["id"] == ids[0]


def test_list_filters_by_id_or_business_name_literally(tmp_path: Path) -> None:
    api = client(tmp_path)
    a = submit(api, "SUB-A")
    submit(api, "SUB-B")

    assert [i["id"] for i in listing(api, q=a["id"][:8])] == [a["id"]]
    assert [i["id"] for i in listing(api, q="pacific harbor")] == [a["id"]]
    assert listing(api, q="%") == []
    assert listing(api, q="_") == []
    assert len(listing(api, limit=1)) == 1


@pytest.mark.parametrize(
    "params",
    [{"sort": "nope"}, {"order": "sideways"}, {"limit": 0}, {"limit": 201}],
)
def test_list_rejects_invalid_parameters(tmp_path: Path, params: dict) -> None:
    assert client(tmp_path).get("/submissions", params=params).status_code == 422


def test_list_skips_submissions_without_a_snapshot(tmp_path: Path) -> None:
    from app.persistence.database import create_db_engine
    from app.persistence.repository import SubmissionRepository

    api = client(tmp_path)
    kept = submit(api, "SUB-A")
    SubmissionRepository(
        create_db_engine(Settings(data_dir=tmp_path).database_path)
    ).create("orphan", [])

    assert [i["id"] for i in listing(api)] == [kept["id"]]


def test_stream_ends_with_result_for_a_packet_of_only_unreadable_files(
    tmp_path: Path,
) -> None:
    events = stream(
        client(tmp_path), files=[("files", ("scan.pdf", b"not a readable pdf"))]
    )

    assert events[-1][0] == "result"
    assert "error" not in [name for name, _ in events]
