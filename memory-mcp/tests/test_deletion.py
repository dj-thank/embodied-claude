"""Tests for fail-closed per-item memory record deletion."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory_mcp.episode import EpisodeManager
from memory_mcp.memory import MemoryStore
from memory_mcp.types import SensoryData


@pytest.mark.asyncio
async def test_delete_memory_record_cleans_graph_and_reports_external_files(
    memory_store: MemoryStore,
    tmp_path: Path,
) -> None:
    sensory_path = tmp_path / "private-observation.jpg"
    sensory_path.write_bytes(b"external sensory data")
    target = await memory_store.save(
        content="削除対象の秘密の観察",
        sensory_data=(
            SensoryData(
                sensory_type="visual",
                file_path=str(sensory_path),
                metadata={},
                description="private observation",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        ),
    )
    survivor = await memory_store.save_with_auto_link(
        content="削除対象に関連する観察",
        link_threshold=2.0,
    )
    await memory_store.add_causal_link(
        survivor.id,
        target.id,
        link_type="related",
    )
    await memory_store.bump_coactivation(survivor.id, target.id, delta=0.4)
    episode_manager = EpisodeManager(
        memory_store,
        memory_store.get_episodes_collection(),
    )
    episode = await episode_manager.create_episode(
        title="削除対象を含む episode",
        memory_ids=[target.id, survivor.id],
        participants=["User"],
    )

    result = await memory_store.delete_memory_record(target.id)

    assert result.deleted is True
    assert result.memory_id == target.id
    assert result.deleted_episode_ids == (episode.id,)
    assert result.external_sensory_paths == (str(sensory_path),)
    assert sensory_path.exists(), "External media deletion requires a separate policy"
    assert await memory_store.get_by_id(target.id) is None
    assert target.id not in {
        memory.id for memory in await memory_store.get_working_memory().get_all()
    }
    assert await episode_manager.get_episode_by_id(episode.id) is None

    survivor_after = await memory_store.get_by_id(survivor.id)
    assert survivor_after is not None
    assert target.id not in survivor_after.linked_ids
    assert all(link.target_id != target.id for link in survivor_after.links)
    assert target.id not in dict(survivor_after.coactivation_weights)
    assert survivor_after.episode_id is None

    second_result = await memory_store.delete_memory_record(target.id)
    assert second_result.deleted is False


@pytest.mark.asyncio
async def test_delete_resumes_cleanup_when_primary_record_is_already_missing(
    memory_store: MemoryStore,
) -> None:
    """A retry must finish references left by an interrupted prior deletion."""
    target = await memory_store.save(content="先に本体だけ消えた記憶")
    survivor = await memory_store.save_with_auto_link(
        content="先に消えた記憶への参照を持つ記憶",
        link_threshold=2.0,
    )
    episode_manager = EpisodeManager(
        memory_store,
        memory_store.get_episodes_collection(),
    )
    episode = await episode_manager.create_episode(
        title="途中で削除が中断したエピソード",
        memory_ids=[target.id, survivor.id],
    )
    collection = memory_store._ensure_connected()
    await asyncio.to_thread(collection.delete, ids=[target.id])

    result = await memory_store.delete_memory_record(target.id)

    assert result.deleted is False
    assert result.cleaned_memory_ids == (survivor.id,)
    assert result.deleted_episode_ids == (episode.id,)
    assert target.id not in {
        memory.id for memory in await memory_store.get_working_memory().get_all()
    }
    survivor_after = await memory_store.get_by_id(survivor.id)
    assert survivor_after is not None
    assert target.id not in survivor_after.linked_ids
    assert survivor_after.episode_id is None
    assert await episode_manager.get_episode_by_id(episode.id) is None


@pytest.mark.asyncio
async def test_auto_link_revalidates_candidates_after_concurrent_delete(
    memory_store: MemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate deleted after search must not become a dangling link."""
    target = await memory_store.save(content="検索後に削除されるリンク候補")
    original_search = memory_store.search
    search_finished = asyncio.Event()
    continue_save = asyncio.Event()

    async def paused_search(*args: object, **kwargs: object):
        results = await original_search(*args, **kwargs)
        search_finished.set()
        await continue_save.wait()
        return results

    monkeypatch.setattr(memory_store, "search", paused_search)
    save_task = asyncio.create_task(
        memory_store.save_with_auto_link(
            content="削除候補に似た新しい記憶",
            link_threshold=2.0,
        )
    )
    await asyncio.wait_for(search_finished.wait(), timeout=5)

    deletion = await memory_store.delete_memory_record(target.id)
    continue_save.set()
    saved = await save_task

    assert deletion.deleted is True
    assert target.id not in saved.linked_ids
    persisted = await memory_store.get_by_id(saved.id)
    assert persisted is not None
    assert target.id not in persisted.linked_ids


@pytest.mark.asyncio
async def test_episode_creation_is_serialized_with_memory_deletion(
    memory_store: MemoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deletion must remove an episode even if creation already read the memory."""
    target = await memory_store.save(content="エピソード化の途中で削除される記憶")
    survivor = await memory_store.save(content="同じエピソードに残る記憶")
    episode_manager = EpisodeManager(
        memory_store,
        memory_store.get_episodes_collection(),
    )
    original_get_by_ids = memory_store.get_by_ids
    memories_read = asyncio.Event()
    continue_creation = asyncio.Event()

    async def paused_get_by_ids(memory_ids: list[str]):
        memories = await original_get_by_ids(memory_ids)
        memories_read.set()
        await continue_creation.wait()
        return memories

    monkeypatch.setattr(memory_store, "get_by_ids", paused_get_by_ids)
    creation_task = asyncio.create_task(
        episode_manager.create_episode(
            title="削除と競合するエピソード",
            memory_ids=[target.id, survivor.id],
        )
    )
    await asyncio.wait_for(memories_read.wait(), timeout=5)

    deletion_task = asyncio.create_task(memory_store.delete_memory_record(target.id))
    await asyncio.sleep(0)
    continue_creation.set()
    episode = await creation_task
    deletion = await deletion_task

    assert deletion.deleted is True
    assert episode.id in deletion.deleted_episode_ids
    assert await episode_manager.get_episode_by_id(episode.id) is None
    survivor_after = await memory_store.get_by_id(survivor.id)
    assert survivor_after is not None
    assert survivor_after.episode_id is None
