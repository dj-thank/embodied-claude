"""Contract and integration tests for the lightweight SQLite backend."""

from pathlib import Path

import pytest

from memory_mcp.config import MemoryConfig
from memory_mcp.episode import EpisodeManager
from memory_mcp.memory import MemoryStore
from memory_mcp.sqlite_store import SQLiteClient


def test_sqlite_collection_supports_chroma_shaped_crud_and_filters(
    tmp_path: Path,
) -> None:
    client = SQLiteClient(tmp_path / "memory.sqlite3")
    collection = client.get_or_create_collection("memories")
    collection.add(
        ids=["one", "two"],
        documents=["幼馴染とカメラで散歩した", "データベースの設計を見直した"],
        metadatas=[
            {"category": "memory", "timestamp": "2026-08-08T10:00:00"},
            {"category": "technical", "timestamp": "2026-08-09T10:00:00"},
        ],
    )

    filtered = collection.get(
        where={
            "$and": [
                {"category": {"$eq": "technical"}},
                {"timestamp": {"$gte": "2026-08-09"}},
            ]
        }
    )
    assert filtered == {
        "ids": ["two"],
        "documents": ["データベースの設計を見直した"],
        "metadatas": [
            {"category": "technical", "timestamp": "2026-08-09T10:00:00"}
        ],
    }
    assert collection.get(where={"timestamp": {"$gte": 1}})["ids"] == []

    collection.update(ids=["two"], metadatas=[{"category": "learning"}])
    assert collection.get(ids=["two"])["metadatas"] == [{"category": "learning"}]

    collection.delete(ids=["one"])
    assert collection.get(ids=["one"])["ids"] == []
    client.close()


def test_sqlite_fts_returns_chroma_shaped_ranked_results(tmp_path: Path) -> None:
    client = SQLiteClient(tmp_path / "memory.sqlite3")
    collection = client.get_or_create_collection("memories")
    collection.add(
        ids=["camera", "food", "code"],
        documents=[
            "幼馴染とカメラの機能について話した",
            "美味しいラーメンを食べた",
            "Pythonコードを書いた",
        ],
        metadatas=[{"category": "memory"}, {"category": "daily"}, {}],
    )

    results = collection.query(query_texts=["カメラの会話"], n_results=2)

    assert results["ids"][0][0] == "camera"
    assert results["documents"][0][0].startswith("幼馴染")
    assert len(results["distances"][0]) == 2
    assert all(0.0 <= distance <= 1.0 for distance in results["distances"][0])
    client.close()


def test_sqlite_client_persists_collections_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    first = SQLiteClient(path)
    first.get_or_create_collection("memories").add(
        ids=["persistent"],
        documents=["再起動後も残る記憶"],
        metadatas=[{"importance": 5}],
    )
    first.close()

    second = SQLiteClient(path)
    restored = second.get_or_create_collection("memories").get(ids=["persistent"])

    assert restored["documents"] == ["再起動後も残る記憶"]
    assert restored["metadatas"] == [{"importance": 5}]
    second.close()


@pytest.mark.asyncio
async def test_memory_store_and_episode_contract_run_on_sqlite(tmp_path: Path) -> None:
    store = MemoryStore(
        MemoryConfig(
            db_path=str(tmp_path / "lite"),
            collection_name="memories",
            backend="sqlite",
        )
    )
    await store.connect()
    try:
        camera = await store.save(
            content="幼馴染とカメラで散歩した",
            category="memory",
            importance=5,
        )
        await store.save(content="Pythonの型を整理した", category="technical")

        results = await store.search("カメラの散歩", category_filter="memory")
        assert [result.memory.id for result in results] == [camera.id]

        episodes = EpisodeManager(store, store.get_episodes_collection())
        episode = await episodes.create_episode("散歩", [camera.id])
        restored_episode = await episodes.get_episode_by_id(episode.id)
        assert restored_episode is not None
        assert restored_episode.memory_ids == (camera.id,)
    finally:
        await store.disconnect()

    reopened = MemoryStore(
        MemoryConfig(
            db_path=str(tmp_path / "lite"),
            collection_name="memories",
            backend="sqlite",
        )
    )
    await reopened.connect()
    try:
        restored = await reopened.get_by_id(camera.id)
        assert restored is not None
        assert restored.content == camera.content
    finally:
        await reopened.disconnect()
