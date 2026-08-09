"""Lightweight SQLite/FTS collection adapter with Chroma-shaped results."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

_SQLITE_FILE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _database_file(path: str | Path) -> str:
    raw_path = str(path)
    if raw_path == ":memory:":
        return raw_path
    candidate = Path(raw_path).expanduser()
    if candidate.suffix.lower() in _SQLITE_FILE_SUFFIXES:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return str(candidate)
    candidate.mkdir(parents=True, exist_ok=True)
    return str(candidate / "memory.sqlite3")


def _matches_where(metadata: Mapping[str, Any], where: Mapping[str, Any] | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        conditions = where["$and"]
        return isinstance(conditions, list) and all(
            isinstance(condition, Mapping) and _matches_where(metadata, condition)
            for condition in conditions
        )
    for key, condition in where.items():
        if key.startswith("$") or not isinstance(condition, Mapping):
            return False
        value = metadata.get(key)
        for operator, expected in condition.items():
            if operator == "$eq" and value != expected:
                return False
            try:
                if operator == "$gte" and (value is None or value < expected):
                    return False
                if operator == "$lte" and (value is None or value > expected):
                    return False
            except TypeError:
                return False
            if operator not in {"$eq", "$gte", "$lte"}:
                return False
    return True


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    if not normalized:
        return set()
    if len(normalized) <= size:
        return {normalized}
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _lexical_distance(query: str, document: str) -> float:
    query_grams = _character_ngrams(query)
    document_grams = _character_ngrams(document)
    if not query_grams or not document_grams:
        return 1.0
    overlap = len(query_grams & document_grams)
    union = len(query_grams | document_grams)
    similarity = overlap / union if union else 0.0
    query_terms = set(re.findall(r"\w+", query.casefold()))
    document_terms = set(re.findall(r"\w+", document.casefold()))
    if query_terms and document_terms:
        similarity = max(similarity, len(query_terms & document_terms) / len(query_terms))
    return max(0.0, min(1.0, 1.0 - similarity))


def _fts_expression(query: str) -> str | None:
    terms: set[str] = set()
    for token in re.findall(r"\w+", query.casefold()):
        if len(token) < 3:
            terms.add(token)
        else:
            terms.update(_character_ngrams(token))
    if not terms:
        return None
    return " OR ".join(
        f'"{term.replace(chr(34), chr(34) * 2)}"' for term in sorted(terms)
    )


class SQLiteClient:
    """Own one SQLite connection shared by all logical collections."""

    def __init__(self, path: str | Path):
        self.path = _database_file(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            if self.path != ":memory:":
                self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    collection TEXT NOT NULL,
                    id TEXT NOT NULL,
                    document TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    PRIMARY KEY (collection, id)
                )
                """
            )
            try:
                self._connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
                    USING fts5(collection UNINDEXED, id UNINDEXED, document, tokenize='trigram')
                    """
                )
            except sqlite3.OperationalError:
                self._connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
                    USING fts5(collection UNINDEXED, id UNINDEXED, document)
                    """
                )

    def get_or_create_collection(
        self,
        name: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "SQLiteCollection":
        del metadata
        if not name or not isinstance(name, str):
            raise ValueError("Collection name must be a non-empty string")
        return SQLiteCollection(self, name)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class SQLiteCollection:
    """Subset of Chroma Collection used by MemoryStore and EpisodeManager."""

    def __init__(self, client: SQLiteClient, name: str):
        self._client = client
        self.name = name

    def add(
        self,
        *,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]],
    ) -> None:
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("ids, documents, and metadatas must have equal lengths")
        rows = [
            (
                self.name,
                record_id,
                document,
                json.dumps(dict(metadata), ensure_ascii=False, separators=(",", ":")),
            )
            for record_id, document, metadata in zip(
                ids, documents, metadatas, strict=True
            )
        ]
        fts_rows = [
            (self.name, record_id, document)
            for record_id, document in zip(ids, documents, strict=True)
        ]
        with self._client._lock, self._client._connection:
            self._client._connection.executemany(
                "INSERT INTO records(collection, id, document, metadata) VALUES (?, ?, ?, ?)",
                rows,
            )
            self._client._connection.executemany(
                "INSERT INTO records_fts(collection, id, document) VALUES (?, ?, ?)",
                fts_rows,
            )

    def get(
        self,
        *,
        ids: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> dict[str, list[Any]]:
        rows = self._records(ids=ids, where=where)
        return {
            "ids": [row[0] for row in rows],
            "documents": [row[1] for row in rows],
            "metadatas": [row[2] for row in rows],
        }

    def query(
        self,
        *,
        query_texts: Sequence[str],
        n_results: int,
        where: Mapping[str, Any] | None = None,
    ) -> dict[str, list[list[Any]]]:
        result_ids: list[list[str]] = []
        result_documents: list[list[str]] = []
        result_metadatas: list[list[dict[str, Any]]] = []
        result_distances: list[list[float]] = []
        for query_text in query_texts:
            fts_matches = self._fts_matches(
                query_text,
                limit=max(200, max(0, n_results) * 20),
            )
            candidate_rows = self._records(ids=sorted(fts_matches), where=where)
            rows = (
                candidate_rows
                if len(candidate_rows) >= n_results
                else self._records(where=where)
            )
            ranked = sorted(
                (
                    (_lexical_distance(query_text, row[1]), row)
                    for row in rows
                ),
                key=lambda scored: (scored[0], scored[1][0]),
            )[: max(0, n_results)]
            result_ids.append([row[0] for _, row in ranked])
            result_documents.append([row[1] for _, row in ranked])
            result_metadatas.append([row[2] for _, row in ranked])
            result_distances.append([distance for distance, _ in ranked])
        return {
            "ids": result_ids,
            "documents": result_documents,
            "metadatas": result_metadatas,
            "distances": result_distances,
        }

    def update(
        self,
        *,
        ids: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]] | None = None,
        documents: Sequence[str] | None = None,
    ) -> None:
        if metadatas is not None and len(ids) != len(metadatas):
            raise ValueError("ids and metadatas must have equal lengths")
        if documents is not None and len(ids) != len(documents):
            raise ValueError("ids and documents must have equal lengths")
        with self._client._lock, self._client._connection:
            for index, record_id in enumerate(ids):
                current = self._client._connection.execute(
                    "SELECT document, metadata FROM records WHERE collection=? AND id=?",
                    (self.name, record_id),
                ).fetchone()
                if current is None:
                    continue
                document = documents[index] if documents is not None else current["document"]
                metadata = (
                    dict(metadatas[index])
                    if metadatas is not None
                    else json.loads(current["metadata"])
                )
                self._client._connection.execute(
                    "UPDATE records SET document=?, metadata=? WHERE collection=? AND id=?",
                    (
                        document,
                        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                        self.name,
                        record_id,
                    ),
                )
                if documents is not None:
                    self._client._connection.execute(
                        "DELETE FROM records_fts WHERE collection=? AND id=?",
                        (self.name, record_id),
                    )
                    self._client._connection.execute(
                        "INSERT INTO records_fts(collection, id, document) VALUES (?, ?, ?)",
                        (self.name, record_id, document),
                    )

    def delete(self, *, ids: Sequence[str]) -> None:
        with self._client._lock, self._client._connection:
            self._client._connection.executemany(
                "DELETE FROM records WHERE collection=? AND id=?",
                [(self.name, record_id) for record_id in ids],
            )
            self._client._connection.executemany(
                "DELETE FROM records_fts WHERE collection=? AND id=?",
                [(self.name, record_id) for record_id in ids],
            )

    def count(self) -> int:
        with self._client._lock:
            row = self._client._connection.execute(
                "SELECT COUNT(*) FROM records WHERE collection=?", (self.name,)
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _records(
        self,
        *,
        ids: Sequence[str] | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        if ids is not None and not ids:
            return []
        with self._client._lock:
            if ids is None:
                database_rows = self._client._connection.execute(
                    "SELECT id, document, metadata FROM records "
                    "WHERE collection=? ORDER BY rowid",
                    (self.name,),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in ids)
                database_rows = self._client._connection.execute(
                    "SELECT id, document, metadata FROM records "
                    f"WHERE collection=? AND id IN ({placeholders})",
                    (self.name, *ids),
                ).fetchall()
        rows = [
            (row["id"], row["document"], json.loads(row["metadata"]))
            for row in database_rows
        ]
        if ids is not None:
            by_id = {row[0]: row for row in rows}
            rows = [by_id[record_id] for record_id in ids if record_id in by_id]
        return [row for row in rows if _matches_where(row[2], where)]

    def _fts_matches(self, query: str, *, limit: int) -> set[str]:
        expression = _fts_expression(query)
        if expression is None:
            return set()
        try:
            with self._client._lock:
                rows = self._client._connection.execute(
                    """
                    SELECT id FROM records_fts
                    WHERE records_fts MATCH ? AND collection=?
                    ORDER BY bm25(records_fts)
                    LIMIT ?
                    """,
                    (expression, self.name, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(row["id"]) for row in rows}
