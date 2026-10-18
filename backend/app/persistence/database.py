from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Engine, event
from sqlmodel import Field, SQLModel, create_engine


def _now() -> datetime:
    return datetime.now(UTC)


class SubmissionRow(SQLModel, table=True):
    __tablename__ = "submissions"

    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    # Current ReviewedField payloads keyed by field name, overrides included.
    reviewed_fields: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class DocumentRow(SQLModel, table=True):
    __tablename__ = "documents"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submissions.id", index=True)
    file_name: str
    kind: str
    content: bytes
    readable: bool
    detected_type: str | None = None


class SourceRunRow(SQLModel, table=True):
    __tablename__ = "source_runs"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submissions.id", index=True)
    source: str
    status: str
    attempts: int
    error: str | None = None


class SnapshotRow(SQLModel, table=True):
    __tablename__ = "snapshots"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submissions.id", index=True)
    created_at: datetime = Field(default_factory=_now)
    trigger: str
    overall_status: str
    rules: list[dict[str, Any]] = Field(sa_type=JSON)


class NarrativeRow(SQLModel, table=True):
    __tablename__ = "narratives"

    submission_id: str = Field(foreign_key="submissions.id", primary_key=True)
    status: str
    error: str | None = None
    summary: str | None = None
    draft_body: str = ""
    draft_edited: bool = False
    draft_stale: bool = False


class MessageRow(SQLModel, table=True):
    __tablename__ = "narrative_messages"

    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submissions.id", index=True)
    created_at: datetime = Field(default_factory=_now)
    role: str
    content: str


def _configure_connection(connection: Any, _record: Any) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")


def create_db_engine(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        # sqlite3 timeout is the busy timeout; the threadpool shares connections.
        connect_args={"timeout": 5, "check_same_thread": False},
    )
    event.listen(engine, "connect", _configure_connection)
    SQLModel.metadata.create_all(engine)
    return engine
