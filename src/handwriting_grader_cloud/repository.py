import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import ApplicationError


class SQLiteRepository:
    """Durable local reference backend; not the production Blob Storage adapter."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS exams (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    content BLOB NOT NULL,
                    FOREIGN KEY (exam_id) REFERENCES exams(id)
                );
                """
            )
        path.chmod(0o600)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, document: dict) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO exams VALUES (?, ?, ?)",
                (document["id"], document["version"], json.dumps(document)),
            )

    def get(self, exam_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT document FROM exams WHERE id=?", (exam_id,)).fetchone()
        if row is None:
            raise ApplicationError("NOT_FOUND", "Exam not found.", 404)
        return json.loads(row[0])

    def save(
        self,
        document: dict,
        expected_version: int,
        artifact: tuple[str, bytes] | None = None,
        artifacts: list[tuple[str, bytes]] | None = None,
    ) -> None:
        with self.connection() as connection:
            changed = connection.execute(
                "UPDATE exams SET version=?, document=? WHERE id=? AND version=?",
                (
                    document["version"],
                    json.dumps(document),
                    document["id"],
                    expected_version,
                ),
            ).rowcount
            if changed != 1:
                raise ApplicationError(
                    "STALE_REVIEW", "The exam changed. Refresh and review the current version.", 409
                )
            pending = list(artifacts or [])
            if artifact is not None:
                pending.append(artifact)
            for artifact_id, content in pending:
                connection.execute(
                    "INSERT INTO artifacts VALUES (?, ?, ?)",
                    (artifact_id, document["id"], content),
                )

    def content(self, exam_id: str, artifact_id: str) -> bytes:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT content FROM artifacts WHERE exam_id=? AND id=?",
                (exam_id, artifact_id),
            ).fetchone()
        if row is None:
            raise ApplicationError("NOT_FOUND", "Artifact not found.", 404)
        return row[0]
