"""Tests for reproducible, model-independent Japanese evaluation scoring."""

from dataclasses import dataclass

import pytest

from local_inference_mcp.evaluation import (
    EvaluationCase,
    EvaluationExpectation,
    EvaluationRunner,
    EvaluationSuite,
    load_japanese_core_suite,
)
from local_inference_mcp.inference import InferenceResult


def test_suite_scores_each_declared_constraint_and_explains_failures() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="exact",
                prompt="repeat",
                expectation=EvaluationExpectation(exact="さんぽ日和やで。"),
            ),
            EvaluationCase(
                case_id="bounded",
                prompt="summarize",
                expectation=EvaluationExpectation(
                    required_terms=("散歩", "朝"),
                    forbidden_terms=("夜",),
                    max_chars=12,
                ),
            ),
        ),
    )

    report = suite.evaluate(
        {
            "exact": "さんぽ日和やで。",
            "bounded": "朝の散歩は夜も快適です。",
        }
    )

    assert report.passed_checks == 4
    assert report.total_checks == 5
    assert report.score == 0.8
    assert report.cases[0].passed is True
    assert report.cases[1].passed is False
    assert report.cases[1].failures == ("forbidden term present: 夜",)


def test_sentence_limit_is_scored_as_an_independent_constraint() -> None:
    case = EvaluationCase(
        case_id="one_sentence",
        prompt="Answer in one sentence",
        expectation=EvaluationExpectation(max_sentences=1),
    )

    passed = EvaluationSuite("unit", (case,)).evaluate(
        {"one_sentence": "Sanpoloidは散歩を楽しみにしています。"}
    )
    failed = EvaluationSuite("unit", (case,)).evaluate(
        {"one_sentence": "Sanpoloidは散歩を楽しみにしています。準備も万全です。"}
    )

    assert passed.score == 1.0
    assert failed.score == 0.0
    assert failed.cases[0].failures == ("too many sentences: 2 > 1",)


def test_required_prefix_is_scored_as_an_independent_constraint() -> None:
    case = EvaluationCase(
        case_id="subject_prefix",
        prompt="Start with the subject",
        expectation=EvaluationExpectation(starts_with="さんぽは"),
    )

    passed = EvaluationSuite("unit", (case,)).evaluate(
        {"subject_prefix": "さんぽは散歩を楽しみにしています。"}
    )
    failed = EvaluationSuite("unit", (case,)).evaluate(
        {"subject_prefix": "さんぽで散歩を楽しみます。"}
    )

    assert passed.score == 1.0
    assert failed.score == 0.0
    assert failed.cases[0].failures == ("required prefix missing: さんぽは",)


def test_missing_output_fails_all_constraints_for_that_case() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="missing",
                prompt="answer",
                expectation=EvaluationExpectation(
                    required_terms=("A", "B"),
                    max_chars=10,
                ),
            ),
        ),
    )

    report = suite.evaluate({})

    assert report.score == 0.0
    assert report.passed_checks == 0
    assert report.total_checks == 3
    assert report.cases[0].failures == ("missing output",)


def test_json_expectation_compares_structure_but_rejects_non_json_wrappers() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="json",
                prompt="json",
                expectation=EvaluationExpectation(json_equals={"状態": "正常"}),
            ),
        ),
    )

    spaced = suite.evaluate({"json": '{ "状態" : "正常" }'})
    fenced = suite.evaluate({"json": '```json\n{"状態":"正常"}\n```'})

    assert spaced.score == 1.0
    assert fenced.score == 0.0
    assert fenced.cases[0].failures == ("invalid JSON output",)


def test_builtin_suite_is_small_inspectable_and_covers_distinct_constraints() -> None:
    suite = load_japanese_core_suite()

    assert suite.name == "japanese-core-v2"
    assert 4 <= len(suite.cases) <= 8
    assert len({case.case_id for case in suite.cases}) == len(suite.cases)
    assert any(case.expectation.exact for case in suite.cases)
    assert any(case.expectation.forbidden_terms for case in suite.cases)
    assert any(case.expectation.max_chars for case in suite.cases)
    assert any(case.expectation.max_sentences for case in suite.cases)
    assert any(case.case_id == "sanpo_name_one_sentence" for case in suite.cases)


def test_suite_can_select_named_cases_without_silently_ignoring_typos() -> None:
    suite = load_japanese_core_suite()

    selected = suite.select(("json_only", "exact_phrase"))

    assert [case.case_id for case in selected.cases] == ["json_only", "exact_phrase"]
    try:
        suite.select(("missing",))
    except ValueError as error:
        assert "unknown evaluation case" in str(error)
    else:
        raise AssertionError("unknown case should fail")


@dataclass
class PresetAwareInference:
    calls: list[dict]

    def complete(self, prompt: str, **kwargs) -> InferenceResult:
        self.calls.append({"prompt": prompt, **kwargs})
        text = "OK" if kwargs["preset"] == "strict" else "extra OK"
        return InferenceResult(text=text, model="fixture-model")


def test_runner_uses_public_completion_interface_and_scores_each_variant() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="one",
                prompt="Return OK",
                expectation=EvaluationExpectation(exact="OK"),
                max_tokens=8,
            ),
        ),
    )
    inference = PresetAwareInference(calls=[])

    result = EvaluationRunner(inference, suite).run(
        presets=("default", "strict"),
        temperature=0.1,
    )

    assert [variant["preset"] for variant in result["variants"]] == [
        "default",
        "strict",
    ]
    assert [variant["score"] for variant in result["variants"]] == [0.0, 1.0]
    assert inference.calls == [
        {
            "prompt": "Return OK",
            "system_prompt": "",
            "preset": "default",
            "generation_profile": "runtime_default",
            "temperature": 0.1,
            "max_tokens": 8,
        },
        {
            "prompt": "Return OK",
            "system_prompt": "",
            "preset": "strict",
            "generation_profile": "runtime_default",
            "temperature": 0.1,
            "max_tokens": 8,
        },
    ]


def test_runner_compares_generation_profiles_as_separate_evidence_variants() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="one",
                prompt="Return OK",
                expectation=EvaluationExpectation(exact="OK"),
                max_tokens=8,
            ),
        ),
    )
    inference = PresetAwareInference(calls=[])

    result = EvaluationRunner(inference, suite).run(
        presets=("strict",),
        generation_profiles=("runtime_default", "lfm2_5_jp"),
        temperature=0.1,
    )

    assert [variant["generation_profile"] for variant in result["variants"]] == [
        "runtime_default",
        "lfm2_5_jp",
    ]
    assert [call["generation_profile"] for call in inference.calls] == [
        "runtime_default",
        "lfm2_5_jp",
    ]


def test_json_preset_rejects_cases_without_a_json_schema_before_inference() -> None:
    suite = EvaluationSuite(
        name="unit",
        cases=(
            EvaluationCase(
                case_id="plain_text_case",
                prompt="Return OK",
                expectation=EvaluationExpectation(exact="OK"),
            ),
        ),
    )
    inference = PresetAwareInference(calls=[])

    with pytest.raises(ValueError, match="plain_text_case"):
        EvaluationRunner(inference, suite).run(presets=("json",))

    assert inference.calls == []
