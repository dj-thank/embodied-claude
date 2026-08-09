"""Deterministic evaluation and a thin runner for local Japanese inference."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

from .config import InferenceConfig
from .inference import InferenceResult, LocalInference, UrllibJsonTransport
from .prompts import available_prompt_presets
from .sampling import available_generation_profiles


@dataclass(frozen=True)
class EvaluationExpectation:
    """Independently scored, deterministic constraints for one response."""

    exact: str | None = None
    json_equals: Any | None = None
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    max_chars: int | None = None

    @property
    def check_count(self) -> int:
        return (
            int(self.exact is not None)
            + int(self.json_equals is not None)
            + len(self.required_terms)
            + len(self.forbidden_terms)
            + int(self.max_chars is not None)
        )


@dataclass(frozen=True)
class EvaluationCase:
    """One user-level evaluation task and its observable contract."""

    case_id: str
    prompt: str
    expectation: EvaluationExpectation
    system_prompt: str = ""
    max_tokens: int = 64
    json_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class CaseResult:
    """Constraint score and diagnostics for one case."""

    case_id: str
    output: str | None
    passed_checks: int
    total_checks: int
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.total_checks > 0 and self.passed_checks == self.total_checks

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "output": self.output,
            "passed": self.passed,
            "passed_checks": self.passed_checks,
            "total_checks": self.total_checks,
            "failures": list(self.failures),
        }


@dataclass(frozen=True)
class EvaluationReport:
    """Aggregate micro-average over every declared constraint."""

    suite: str
    cases: tuple[CaseResult, ...]

    @property
    def passed_checks(self) -> int:
        return sum(case.passed_checks for case in self.cases)

    @property
    def total_checks(self) -> int:
        return sum(case.total_checks for case in self.cases)

    @property
    def score(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return round(self.passed_checks / self.total_checks, 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "score": self.score,
            "passed_checks": self.passed_checks,
            "total_checks": self.total_checks,
            "cases": [case.as_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class EvaluationSuite:
    """A named set of stable cases scored without model-specific heuristics."""

    name: str
    cases: tuple[EvaluationCase, ...]

    def evaluate(self, outputs: Mapping[str, str]) -> EvaluationReport:
        return EvaluationReport(
            suite=self.name,
            cases=tuple(_evaluate_case(case, outputs.get(case.case_id)) for case in self.cases),
        )

    def select(self, case_ids: Sequence[str]) -> EvaluationSuite:
        """Return cases in requested order and reject stale or misspelled IDs."""
        indexed = {case.case_id: case for case in self.cases}
        unknown = [case_id for case_id in case_ids if case_id not in indexed]
        if unknown:
            raise ValueError(f"unknown evaluation case: {', '.join(unknown)}")
        return EvaluationSuite(self.name, tuple(indexed[case_id] for case_id in case_ids))


class CompletionInterface(Protocol):
    """Public local-inference interface needed by the evaluator."""

    def complete(self, prompt: str, **kwargs: Any) -> InferenceResult: ...


class EvaluationRunner:
    """Run the same stable suite against one or more prompt presets."""

    def __init__(self, inference: CompletionInterface, suite: EvaluationSuite) -> None:
        self._inference = inference
        self._suite = suite

    def run(
        self,
        *,
        presets: Sequence[str],
        generation_profiles: Sequence[str] = ("runtime_default",),
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        valid_presets = set(available_prompt_presets())
        if not presets or any(preset not in valid_presets for preset in presets):
            raise ValueError("presets must contain known prompt preset names")
        valid_profiles = set(available_generation_profiles())
        if not generation_profiles or any(
            profile not in valid_profiles for profile in generation_profiles
        ):
            raise ValueError("generation_profiles must contain known profile names")
        variants: list[dict[str, Any]] = []
        for preset in presets:
            for generation_profile in generation_profiles:
                outputs: dict[str, str] = {}
                models: list[str] = []
                started = time.perf_counter()
                for case in self._suite.cases:
                    completion_arguments: dict[str, Any] = {
                        "system_prompt": case.system_prompt,
                        "preset": preset,
                        "generation_profile": generation_profile,
                        "temperature": temperature,
                        "max_tokens": case.max_tokens,
                    }
                    if preset == "json" and case.json_schema is not None:
                        completion_arguments["json_schema"] = case.json_schema
                    result = self._inference.complete(case.prompt, **completion_arguments)
                    outputs[case.case_id] = result.text
                    models.append(result.model)
                report = self._suite.evaluate(outputs)
                variant = report.as_dict()
                variant.update(
                    {
                        "preset": preset,
                        "generation_profile": generation_profile,
                        "temperature": temperature,
                        "model": models[0] if len(set(models)) == 1 else models,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                    }
                )
                variants.append(variant)
        return {"suite": self._suite.name, "variants": variants}


def load_japanese_core_suite() -> EvaluationSuite:
    """Load the packaged, inspectable Japanese core fixture."""
    resource = files("local_inference_mcp").joinpath("evals/japanese_core.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    cases = tuple(_case_from_dict(item) for item in payload["cases"])
    return EvaluationSuite(name=payload["name"], cases=cases)


def _case_from_dict(payload: Mapping[str, Any]) -> EvaluationCase:
    expected = payload["expectation"]
    return EvaluationCase(
        case_id=payload["id"],
        prompt=payload["prompt"],
        system_prompt=payload.get("system_prompt", ""),
        max_tokens=payload.get("max_tokens", 64),
        json_schema=payload.get("json_schema"),
        expectation=EvaluationExpectation(
            exact=expected.get("exact"),
            json_equals=expected.get("json_equals"),
            required_terms=tuple(expected.get("required_terms", ())),
            forbidden_terms=tuple(expected.get("forbidden_terms", ())),
            max_chars=expected.get("max_chars"),
        ),
    )


def _evaluate_case(case: EvaluationCase, output: str | None) -> CaseResult:
    total = case.expectation.check_count
    if output is None:
        return CaseResult(case.case_id, None, 0, total, ("missing output",))

    normalized = output.strip()
    passed = 0
    failures: list[str] = []
    expected = case.expectation
    if expected.exact is not None:
        if normalized == expected.exact:
            passed += 1
        else:
            failures.append(f"exact mismatch: expected {expected.exact}")
    if expected.json_equals is not None:
        try:
            decoded_json = json.loads(normalized)
        except json.JSONDecodeError:
            failures.append("invalid JSON output")
        else:
            if decoded_json == expected.json_equals:
                passed += 1
            else:
                failures.append("JSON structure mismatch")
    for term in expected.required_terms:
        if term in normalized:
            passed += 1
        else:
            failures.append(f"required term missing: {term}")
    for term in expected.forbidden_terms:
        if term not in normalized:
            passed += 1
        else:
            failures.append(f"forbidden term present: {term}")
    if expected.max_chars is not None:
        if len(normalized) <= expected.max_chars:
            passed += 1
        else:
            failures.append(f"too long: {len(normalized)} > {expected.max_chars}")
    return CaseResult(case.case_id, output, passed, total, tuple(failures))


def main(argv: Sequence[str] | None = None) -> None:
    """Run the core suite and emit a portable JSON evidence artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        action="append",
        dest="presets",
        choices=available_prompt_presets(),
        help="prompt preset to evaluate; repeat to compare (default: default and strict)",
    )
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument(
        "--generation-profile",
        action="append",
        dest="generation_profiles",
        choices=available_generation_profiles(),
        help="sampling profile to evaluate; repeat to compare (default: runtime_default)",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="case ID to run; repeat to select multiple (default: all)",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    presets = tuple(arguments.presets or ("default", "strict"))
    inference = LocalInference(InferenceConfig.from_env(), UrllibJsonTransport())
    suite = load_japanese_core_suite()
    if arguments.cases:
        suite = suite.select(tuple(arguments.cases))
    result = EvaluationRunner(inference, suite).run(
        presets=presets,
        generation_profiles=tuple(
            arguments.generation_profiles or ("runtime_default",)
        ),
        temperature=arguments.temperature,
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
