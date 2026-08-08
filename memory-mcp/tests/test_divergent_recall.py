"""Tests for divergent recall and consolidation."""

import asyncio

import pytest

from memory_mcp.memory import MemoryStore


class TestMetadataConcurrency:
    """Concurrent metadata mutations must not overwrite each other."""

    @pytest.mark.asyncio
    async def test_concurrent_activation_updates_do_not_lose_counts(
        self,
        memory_store: MemoryStore,
    ):
        memory = await memory_store.save(content="並行活性化の対象")

        results = await asyncio.gather(
            *(memory_store.record_activation(memory.id) for _ in range(8))
        )

        assert all(results)
        updated = await memory_store.get_by_id(memory.id)
        assert updated is not None
        assert updated.activation_count == 8

    @pytest.mark.asyncio
    async def test_concurrent_coactivation_updates_do_not_lose_weight(
        self,
        memory_store: MemoryStore,
    ):
        source = await memory_store.save(content="共起 source")
        target = await memory_store.save(content="共起 target")

        results = await asyncio.gather(
            *(
                memory_store.bump_coactivation(source.id, target.id, delta=0.1)
                for _ in range(8)
            )
        )

        assert all(results)
        updated_source = await memory_store.get_by_id(source.id)
        updated_target = await memory_store.get_by_id(target.id)
        assert updated_source is not None
        assert updated_target is not None
        assert dict(updated_source.coactivation_weights)[target.id] == pytest.approx(0.8)
        assert dict(updated_target.coactivation_weights)[source.id] == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_concurrent_partial_updates_preserve_distinct_fields(
        self,
        memory_store: MemoryStore,
    ):
        memory = await memory_store.save(content="部分更新の競合対象")

        results = await asyncio.gather(
            memory_store.update_memory_fields(memory.id, novelty_score=0.7),
            memory_store.update_memory_fields(memory.id, prediction_error=0.8),
        )

        assert all(results)
        updated = await memory_store.get_by_id(memory.id)
        assert updated is not None
        assert updated.novelty_score == pytest.approx(0.7)
        assert updated.prediction_error == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_episode_and_scoring_updates_preserve_both_fields(
        self,
        memory_store: MemoryStore,
    ):
        memory = await memory_store.save(content="episode 更新の競合対象")

        scoring_result, episode_result = await asyncio.gather(
            memory_store.update_memory_fields(memory.id, novelty_score=0.6),
            memory_store.update_episode_id(memory.id, "episode-1"),
        )

        assert episode_result is None
        assert scoring_result is True
        updated = await memory_store.get_by_id(memory.id)
        assert updated is not None
        assert updated.episode_id == "episode-1"
        assert updated.novelty_score == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_access_and_activation_updates_preserve_both_counters(
        self,
        memory_store: MemoryStore,
    ):
        memory = await memory_store.save(content="異種 counter の競合対象")

        await asyncio.gather(
            *(memory_store.update_access(memory.id) for _ in range(4)),
            *(memory_store.record_activation(memory.id) for _ in range(4)),
        )

        updated = await memory_store.get_by_id(memory.id)
        assert updated is not None
        assert updated.access_count == 4
        assert updated.activation_count == 4


class TestDivergentRecall:
    """Divergent recall behavior tests."""

    @pytest.mark.asyncio
    async def test_recall_divergent_returns_results_with_diagnostics(
        self,
        memory_store: MemoryStore,
    ):
        first = await memory_store.save(
            content="朝の空をカメラで探した",
            emotion="excited",
            category="observation",
            tags=("camera", "sky"),
        )
        second = await memory_store.save(
            content="窓の位置を変えて空を見つけた",
            emotion="happy",
            category="observation",
            tags=("window", "sky"),
        )
        await memory_store.save(
            content="夕飯の献立を考えた",
            emotion="neutral",
            category="daily",
        )
        await memory_store.add_causal_link(first.id, second.id, link_type="related")

        results, diagnostics = await memory_store.recall_divergent(
            context="空を探すカメラの話",
            n_results=3,
            max_branches=3,
            max_depth=3,
            include_diagnostics=True,
        )

        assert results
        assert "diversity_score" in diagnostics
        assert diagnostics["selected_count"] == len(results)

    @pytest.mark.asyncio
    async def test_get_association_diagnostics_has_core_metrics(
        self,
        memory_store: MemoryStore,
    ):
        await memory_store.save(content="カメラの向きと空の関係を覚えた")
        await memory_store.save(content="雲の色で天気を予測した")

        diagnostics = await memory_store.get_association_diagnostics(
            context="空とカメラ",
            sample_size=10,
        )

        assert "adaptive_branch_limit" in diagnostics
        assert "avg_prediction_error" in diagnostics


class TestConsolidation:
    """Consolidation replay tests."""

    @pytest.mark.asyncio
    async def test_consolidate_memories_updates_activation_and_coactivation(
        self,
        memory_store: MemoryStore,
    ):
        first = await memory_store.save(content="朝の観察を記録した", category="observation")
        await asyncio.sleep(0.01)
        second = await memory_store.save(content="窓辺で空を見た", category="observation")

        stats = await memory_store.consolidate_memories(
            window_hours=1,
            max_replay_events=10,
            link_update_strength=0.3,
        )

        assert stats["replay_events"] > 0
        updated_first = await memory_store.get_by_id(first.id)
        updated_second = await memory_store.get_by_id(second.id)
        assert updated_first is not None
        assert updated_second is not None
        assert updated_first.activation_count >= 1
        assert any(item_id == second.id for item_id, _ in updated_first.coactivation_weights)
