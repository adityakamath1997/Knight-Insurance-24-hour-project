from pathlib import Path

from app.settings import Settings


def test_settings_uses_local_sqlite_path(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.database_path == tmp_path / "knight-review.sqlite3"
