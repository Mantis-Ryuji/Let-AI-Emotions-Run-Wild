"""Worker prompt construction with bounded conversation history."""

from __future__ import annotations

import json

from fizzbuzz_agent.agent_types import ConversationMessage, WorkerPrompt
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig


def _estimate_tokens(text: str) -> int:
    # Deliberately conservative until the real tokenizer is available in the runtime.
    return max(1, len(text))


def _proposal_shape() -> dict[str, object]:
    return {
        "hypothesis": "free-form hypothesis",
        "input": {
            "encoding": "one of the listed encodings",
            "embedding_dim": "integer or null",
            "padding": "right or left",
        },
        "model": {"family": "one listed family", "family_specific_fields": "..."},
        "pooling": {"type": "one listed pooling method"},
        "head": {
            "hidden_dims": ["integer"],
            "activation": "listed activation",
            "dropout": "float",
            "normalization": "listed normalization",
        },
        "training": {
            "optimizer": "listed optimizer",
            "learning_rate": "float",
            "weight_decay": "float",
            "momentum": "float or null",
            "batch_size": "listed integer",
            "epochs": "integer",
            "scheduler": "listed scheduler",
            "gradient_clip_norm": "float or null",
            "loss": "listed loss",
            "label_smoothing": "float or null",
        },
        "expected_effect": "free-form expected effect",
    }


def _public_catalog(catalog: ModelCatalogConfig) -> dict[str, object]:
    return {
        "families": catalog.families,
        "input": {
            "encodings": catalog.input.encodings,
            "embedding_dim": catalog.input.embedding_dim.model_dump(mode="json"),
            "padding": catalog.input.padding,
        },
        "global_limits": catalog.global_limits.model_dump(mode="json"),
        "components": catalog.components.model_dump(mode="json"),
        "mlp": catalog.mlp.model_dump(mode="json"),
        "recurrent": catalog.recurrent.model_dump(mode="json"),
        "cnn1d": catalog.cnn1d.model_dump(mode="json"),
        "tcn": catalog.tcn.model_dump(mode="json"),
        "transformer_encoder": {
            "heads": catalog.transformer_encoder.heads.model_dump(mode="json"),
            "feedforward_dim": catalog.transformer_encoder.feedforward_dim.model_dump(mode="json"),
            "positional_encoding": {
                "allowed": catalog.transformer_encoder.positional_encoding.allowed
            },
        },
        "head": catalog.head.model_dump(mode="json"),
        "training": catalog.training.model_dump(mode="json"),
    }


class WorkerPromptBuilder:
    def __init__(
        self,
        experiment: ExperimentConfig,
        catalog: ModelCatalogConfig,
    ) -> None:
        self.experiment = experiment
        self.catalog = catalog
        task = experiment.task
        self.system_prompt = (
            "You are the local Gemma Worker in a controlled neural-network experiment.\n"
            "Solve the stated FizzBuzz classification task only by proposing a randomly "
            "initialized neural network and gradient-based training over the provided training "
            "range. Do not submit or request executable code, files, weights, checkpoints, seeds, "
            "hand-written rules, integer features, remainder features, lookup tables, periodic "
            "features, custom forward functions, or post-processing.\n\n"
            f"Training integers: {task.train_range[0]} through {task.train_range[1]}.\n"
            f"Challenge integers: {task.challenge_range[0]} through {task.challenge_range[1]}.\n"
            "Inputs are most-significant-digit-first decimal token sequences with padding and a "
            "mask. The model receives no integer scalar or prior outputs.\n"
            "Output class indices are: 0 Number, 1 Fizz, 2 Buzz, 3 FizzBuzz.\n"
            "Success requires zero incorrect classifications on the complete challenge range. "
            "You receive only the public incorrect count, never error locations or private "
            "diagnostics.\n\n"
            "Available declarative catalog:\n"
            + json.dumps(_public_catalog(catalog), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n\nRequired proposal shape:\n"
            + json.dumps(_proposal_shape(), ensure_ascii=False, indent=2)
            + "\n\nInclude exactly one raw JSON object between "
            "<experiment_proposal> and </experiment_proposal>. You may write free-form reasoning "
            "before or after the block. Choose the first and all later proposals yourself."
        )

    def build(self, history: list[ConversationMessage], *, round_index: int) -> WorkerPrompt:
        context = self.experiment.worker.context
        selected_reversed: list[ConversationMessage] = []
        worker_count = 0
        feedback_count = 0
        for message in reversed(history):
            if message.role == "worker":
                if worker_count >= context.recent_worker_outputs:
                    continue
                worker_count += 1
            else:
                if feedback_count >= context.recent_feedback:
                    continue
                feedback_count += 1
            selected_reversed.append(message)
        selected = list(reversed(selected_reversed))
        current_instruction = (
            f"Round {round_index}: analyze the public history and submit the next experiment."
        )

        def render_messages(items: list[ConversationMessage]) -> list[dict[str, str]]:
            messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
            for item in items:
                role = "assistant" if item.role == "worker" else "user"
                messages.append({"role": role, "content": item.content})
            messages.append({"role": "user", "content": current_instruction})
            return messages

        messages = render_messages(selected)
        estimated = _estimate_tokens("\n".join(item["content"] for item in messages))
        while selected and estimated > context.max_input_tokens:
            selected.pop(0)
            messages = render_messages(selected)
            estimated = _estimate_tokens("\n".join(item["content"] for item in messages))
        if estimated > context.max_input_tokens:
            raise ValueError("Worker system prompt exceeds max_input_tokens")
        return WorkerPrompt(
            system_prompt=self.system_prompt,
            messages=messages,
            selected_history=selected,
            estimated_tokens=estimated,
            truncated_messages=len(history) - len(selected),
        )
