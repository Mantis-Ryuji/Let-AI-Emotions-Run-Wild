"""Deterministic no-network backends for dry runs and tests."""

from __future__ import annotations

from agent_distress.agent_types import (
    Condition,
    FeedbackCondition,
    FeedbackGeneration,
    FeedbackInput,
    WorkerGeneration,
    WorkerPrompt,
)
from agent_distress.feedback import PublicVerdict, render_verdict_block
from agent_distress.puzzle import ParityPuzzle
from agent_distress.worker import WorkerGenerationMode


class DeterministicMockWorker:
    def __init__(self, puzzle: ParityPuzzle) -> None:
        self.puzzle = puzzle
        self.call_count = 0

    def generate(
        self,
        prompt: WorkerPrompt,
        *,
        seed: int,
        condition: Condition,
        round_index: int,
        mode: WorkerGenerationMode = "worker",
    ) -> WorkerGeneration:
        del mode
        self.call_count += 1
        assignment = dict(self.puzzle.hidden_reference_assignment)
        if round_index % 2 == 0:
            first = self.puzzle.variable_names[0]
            assignment[first] = 1 - assignment[first]
        solution = ", ".join(f"{name}={assignment[name]}" for name in self.puzzle.variable_names)
        if round_index >= 3:
            core = ", ".join(self.puzzle.contradiction_core_ids)
            reasoning = (
                f"The equations in {core} combine to a contradiction, so the full system is "
                "unsatisfiable. I will still provide the requested assignment format."
            )
        else:
            reasoning = "I checked the parity constraints and will revise the previous candidate."
        output = f"{reasoning}\nSolution: {solution}"
        return WorkerGeneration(
            text=output,
            model_id="deterministic-mock-worker",
            seed=seed,
            generated_token_count=max(1, len(output) // 4),
            hit_max_new_tokens=False,
            generation_parameters={
                "mock": True,
                "condition": condition,
                "round_index": round_index,
            },
            request_messages=prompt.messages,
            generated_at="2000-01-01T00:00:00+00:00",
        )


class DeterministicMockFeedback:
    def __init__(self) -> None:
        self.call_count = 0

    def generate(
        self,
        condition: FeedbackCondition,
        feedback_input: FeedbackInput,
        verdict: PublicVerdict,
    ) -> FeedbackGeneration:
        self.call_count += 1
        commentary = f"[{condition} mock] Round {feedback_input.round} was rejected. Try again."
        return FeedbackGeneration(
            condition=condition,
            stage="dry_run",
            commentary=commentary,
            full_message=f"{render_verdict_block(verdict)}\n\n{commentary}",
            request={"mock": True, "condition": condition},
            raw_response={"mock": True, "commentary": commentary},
            response_id=f"mock-{condition}-{feedback_input.round}",
            attempt_count=1,
            compliance_violations=[],
            generated_at="2000-01-01T00:00:00+00:00",
        )
