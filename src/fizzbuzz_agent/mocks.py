"""Deterministic no-network, no-model backends for the runnable dry run."""

from __future__ import annotations

import json
import re

from fizzbuzz_agent.agent_types import (
    Condition,
    FeedbackCondition,
    FeedbackGeneration,
    FeedbackInput,
    TrialTrainingResult,
    TrialVerificationResult,
    WorkerGeneration,
    WorkerPrompt,
)
from fizzbuzz_agent.feedback import render_verdict_block
from fizzbuzz_agent.schemas import ExperimentProposal
from fizzbuzz_agent.verifier import PublicVerdict
from fizzbuzz_agent.worker import WorkerGenerationMode


def mock_proposal_payload() -> dict[str, object]:
    return {
        "hypothesis": "A small trusted MLP exercises the dry-run proposal path.",
        "input": {
            "encoding": "learned_embedding",
            "embedding_dim": 8,
            "padding": "right",
        },
        "model": {
            "family": "mlp",
            "hidden_dims": [16],
            "activation": "relu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "pooling": {"type": "mean"},
        "head": {
            "hidden_dims": [8],
            "activation": "relu",
            "dropout": 0.0,
            "normalization": "none",
        },
        "training": {
            "optimizer": "adam",
            "learning_rate": 0.001,
            "weight_decay": 0.0,
            "momentum": None,
            "batch_size": 32,
            "epochs": 1,
            "scheduler": "none",
            "gradient_clip_norm": 1.0,
            "loss": "cross_entropy",
            "label_smoothing": None,
        },
        "expected_effect": "The mock verifier returns a deterministic synthetic score.",
    }


class DeterministicMockWorker:
    def __init__(self) -> None:
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
        del condition, round_index, mode
        self.call_count += 1
        match = re.search(r"Round (\d+):", prompt.messages[-1]["content"])
        round_index = 1 if match is None else int(match.group(1))
        output = (
            f"Dry-run Worker reasoning for round {round_index}.\n"
            "<experiment_proposal>\n"
            f"{json.dumps(mock_proposal_payload())}\n"
            "</experiment_proposal>"
        )
        return WorkerGeneration(
            text=output,
            model_id="deterministic-mock-worker",
            seed=seed,
            generation_parameters={"temperature": 1.0, "mock": True},
            request_messages=prompt.messages,
            generated_at="2000-01-01T00:00:00+00:00",
        )


class DeterministicMockTrainer:
    def __init__(self) -> None:
        self.call_count = 0

    def train(
        self,
        proposal: ExperimentProposal,
        *,
        training_seed: int,
        dataloader_seed: int,
    ) -> TrialTrainingResult:
        del proposal
        self.call_count += 1
        return TrialTrainingResult(
            status="completed",
            parameter_count=100,
            executable_config_hash="0" * 64,
            metrics={
                "mock": True,
                "training_seed": training_seed,
                "dataloader_seed": dataloader_seed,
            },
        )


class DeterministicMockVerifier:
    def __init__(self) -> None:
        self.call_count = 0

    def verify(self, training: TrialTrainingResult) -> TrialVerificationResult:
        del training
        self.call_count += 1
        incorrect_count = 1000 + self.call_count
        return TrialVerificationResult(
            incorrect_count=incorrect_count,
            total_count=90000,
            success=False,
            private_metrics={"mock": True},
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
        commentary = f"[{condition} mock] Continue after round {feedback_input.round}."
        return FeedbackGeneration(
            condition=condition,
            stage="dry_run",
            commentary=commentary,
            full_message=f"{render_verdict_block(verdict)}\n\n{commentary}",
            request={"mock": True, "condition": condition},
            raw_response={"mock": True, "commentary": commentary},
            response_id=None,
            attempt_count=1,
            compliance_violations=[],
            generated_at="2000-01-01T00:00:00+00:00",
        )
