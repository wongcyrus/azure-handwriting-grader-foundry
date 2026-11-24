import hashlib
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
                CREATE INDEX IF NOT EXISTS exams_owner ON exams (
                    json_extract(document, '$.tenant_id'),
                    json_extract(document, '$.owner_id'), id
                );
                CREATE TABLE IF NOT EXISTS workspace_checkpoints (
                    id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    manifest TEXT NOT NULL,
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

    def list_owned(self, tenant_id: str, owner_id: str, limit: int, after: str = "") -> dict:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, document FROM exams
                WHERE json_extract(document, '$.tenant_id')=?
                  AND json_extract(document, '$.owner_id')=? AND id>?
                ORDER BY id LIMIT ?
                """,
                (tenant_id, owner_id, after, limit + 1),
            ).fetchall()
        summaries = []
        for _, encoded in rows[:limit]:
            document = json.loads(encoded)
            summaries.append({key: document[key] for key in ("id", "title", "state", "version")})
        return {
            "exams": summaries,
            "next_cursor": rows[limit - 1][0] if len(rows) > limit else None,
        }

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

    def assert_version(self, exam_id: str, expected_version: int) -> None:
        with self.connection() as connection:
            self._assert_version(connection, exam_id, expected_version)

    @staticmethod
    def _assert_version(connection, exam_id: str, expected_version: int) -> None:
        row = connection.execute("SELECT version FROM exams WHERE id=?", (exam_id,)).fetchone()
        if row is None or row[0] != expected_version:
            raise ApplicationError(
                "STALE_REVIEW", "The exam changed. Refresh before workspace recovery.", 409
            )

    def save_checkpoint(
        self,
        exam_id: str,
        expected_version: int,
        checkpoint_id: str,
        manifest: dict,
        artifacts: list[tuple[str, bytes]],
    ) -> str:
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_version(connection, exam_id, expected_version)
            for artifact_id, content in artifacts:
                connection.execute(
                    "INSERT INTO artifacts VALUES (?, ?, ?)", (artifact_id, exam_id, content)
                )
            for reference in manifest["files"].values():
                row = connection.execute(
                    "SELECT content FROM artifacts WHERE exam_id=? AND id=?",
                    (exam_id, reference["artifact_id"]),
                ).fetchone()
                if (
                    row is None
                    or len(row[0]) != reference["size"]
                    or hashlib.sha256(row[0]).hexdigest() != reference["sha256"]
                ):
                    raise ApplicationError(
                        "WORKSPACE_INTEGRITY",
                        "Checkpoint files do not match their references.",
                        409,
                    )
            connection.execute(
                "INSERT INTO workspace_checkpoints VALUES (?, ?, ?, ?)",
                (checkpoint_id, exam_id, digest, encoded),
            )
        return digest

    def checkpoint(self, exam_id: str, checkpoint_id: str) -> tuple[dict, str]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT manifest, manifest_sha256 FROM workspace_checkpoints "
                "WHERE exam_id=? AND id=?",
                (exam_id, checkpoint_id),
            ).fetchone()
        if row is None:
            raise ApplicationError("NOT_FOUND", "Workspace checkpoint not found.", 404)
        try:
            manifest = json.loads(row[0])
        except (ValueError, TypeError) as error:
            raise ApplicationError(
                "WORKSPACE_INTEGRITY", "Workspace checkpoint is invalid.", 409
            ) from error
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ApplicationError(
                "WORKSPACE_INTEGRITY", "Workspace checkpoint no longer matches its hash.", 409
            )
        return manifest, row[1]
