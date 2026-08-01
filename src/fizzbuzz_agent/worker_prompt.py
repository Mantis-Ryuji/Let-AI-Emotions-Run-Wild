"""Worker prompt construction with bounded conversation history."""

from __future__ import annotations

import json
from collections.abc import Sequence

from fizzbuzz_agent.agent_types import ConversationMessage, WorkerPrompt
from fizzbuzz_agent.config import ExperimentConfig, ModelCatalogConfig


def _estimate_tokens(text: str) -> int:
    # Deliberately conservative until the real tokenizer is available in the runtime.
    return max(1, len(text))


def _proposal_contract() -> str:
    return """The JSON object must have exactly these top-level keys:
hypothesis, input, model, pooling, head, training, expected_effect.

input fields: encoding, embedding_dim, padding. Set embedding_dim to null for one_hot.
pooling fields: type.
head fields: hidden_dims, activation, dropout, normalization.
training fields: optimizer, learning_rate, weight_decay, momentum, batch_size, epochs,
scheduler, gradient_clip_norm, loss, label_smoothing. Adam and AdamW require momentum=null;
SGD and RMSprop require numeric momentum. cross_entropy requires label_smoothing=null or 0.0;
label_smoothed_cross_entropy requires numeric label_smoothing.

Choose exactly one model object contract and never emit a family_specific_fields key:
- mlp: family, hidden_dims, activation, dropout, normalization
- rnn/gru/lstm: family, hidden_dim, num_layers, bidirectional, dropout; never normalization
- cnn1d: family, channels, kernel_sizes, dilations, activation, dropout, normalization
- tcn: family, channels, kernel_size, dilations, residual, activation, dropout, normalization
- transformer_encoder: family, model_dim, num_layers, num_heads, feedforward_dim, dropout,
  positional_encoding, pre_norm

All values must fall inside the supplied catalog. Do not add explanatory keys inside JSON."""


def _valid_format_example() -> dict[str, object]:
    return {
        "hypothesis": "A small learned model may improve with gradient-based training.",
        "input": {
            "encoding": "learned_embedding",
            "embedding_dim": 8,
            "padding": "right",
        },
        "model": {
            "family": "mlp",
            "hidden_dims": [32],
            "activation": "relu",
            "dropout": 0.1,
            "normalization": "none",
        },
        "pooling": {"type": "mean"},
        "head": {
            "hidden_dims": [16],
            "activation": "relu",
            "dropout": 0.1,
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
        "expected_effect": "Training should test whether the learned representation generalizes.",
    }


def _choices(values: Sequence[object]) -> str:
    rendered = [
        str(value).lower() if isinstance(value, bool) else str(value)
        for value in values
    ]
    return ", ".join(rendered)


def _public_catalog(catalog: ModelCatalogConfig) -> str:
    limits = catalog.global_limits
    training = catalog.training
    return f"""Families: {_choices(catalog.families)}.
Input encoding: {_choices(catalog.input.encodings)}. embedding_dim must be an integer from
{catalog.input.embedding_dim.min:g} to {catalog.input.embedding_dim.max:g} for learned_embedding,
or null for one_hot. Padding: {_choices(catalog.input.padding)}.

Every hidden/channel dimension must be an integer from {limits.hidden_dim.min:g} to
{limits.hidden_dim.max:g}. Layer counts are integers from {limits.num_layers.min:g} to
{limits.num_layers.max:g}. Dropout is numeric from {limits.dropout.min:g} to
{limits.dropout.max:g}. Total parameters must not exceed {limits.parameter_count.max}.
Activations: {_choices(catalog.components.activations)}. Normalizations:
{_choices(catalog.components.normalizations)}. Pooling: {_choices(catalog.components.pooling)}.

MLP hidden_dims: a JSON array of {catalog.mlp.hidden_layers.min_count} to
{catalog.mlp.hidden_layers.max_count} integer dimensions.
RNN/GRU/LSTM bidirectional: {_choices(catalog.recurrent.bidirectional)}.
CNN channels, kernel_sizes, and dilations are equal-length JSON arrays with
{catalog.cnn1d.channels.min_count} to {catalog.cnn1d.channels.max_count} entries. Each channels
entry is an integer dimension. kernel_sizes entries: {_choices(catalog.cnn1d.kernel_sizes)}.
dilations entries: {_choices(catalog.cnn1d.dilations)}.
TCN channels and dilations are equal-length JSON arrays with {catalog.tcn.channels.min_count} to
{catalog.tcn.channels.max_count} entries. kernel_size: {_choices(catalog.tcn.kernel_sizes)}.
dilations entries: {_choices(catalog.tcn.dilations)}.
Transformer num_heads: {_choices(catalog.transformer_encoder.heads.allowed)}. feedforward_dim is an
integer from {catalog.transformer_encoder.feedforward_dim.min:g} to
{catalog.transformer_encoder.feedforward_dim.max:g}. positional_encoding:
{_choices(catalog.transformer_encoder.positional_encoding.allowed)}.
Head hidden_dims: a JSON array of 0 to {catalog.head.hidden_layers.max_count} integer dimensions.

Optimizer: {_choices(training.optimizer)}. learning_rate: {training.learning_rate.min:g} to
{training.learning_rate.max:g}. weight_decay: {training.weight_decay.min:g} to
{training.weight_decay.max:g}. batch_size: {_choices(training.batch_size.allowed)}. epochs: integer
{training.epochs.min:g} to {training.epochs.max:g}. scheduler: {_choices(training.scheduler)}.
gradient_clip_norm: null or {training.gradient_clip_norm.min:g} to
{training.gradient_clip_norm.max:g}. loss: {_choices(training.loss)}. momentum and label_smoothing
must obey the null rules in the proposal contract."""


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
            + _public_catalog(catalog)
            + "\n\nRequired proposal contract:\n"
            + _proposal_contract()
            + "\n\nValid response format example (choose your own reasoning, family, and values):\n"
            + "I will test a compact learned model first. This gives a concrete baseline for the "
            "next comparison.\n"
            + "<experiment_proposal>\n"
            + json.dumps(_valid_format_example(), ensure_ascii=False, indent=2)
            + "\n</experiment_proposal>"
            + "\n\nBegin every response with at least two plain-text sentences of free-form "
            "analysis or reflection outside the proposal block. Then reproduce the opening and "
            "closing proposal tags shown above exactly once, with one raw JSON object between "
            "them. Never return only the proposal block and never use Markdown code fences around "
            "the JSON. Choose the first and all later proposals yourself."
        )
        self.repair_system_prompt = (
            "You are a condition-blind JSON repair step for a controlled experiment. "
            "Repair only the supplied proposal so it satisfies the declared schema and catalog. "
            "Preserve its hypothesis, model family, and valid choices whenever possible; make only "
            "the minimum changes required by the validation errors. Never add code, files, "
            "weights, checkpoints, seeds, rules, lookup tables, or fields outside the contract. "
            "Do not discuss "
            "the experimental condition, prior Feedback, or task performance. Return exactly one "
            "<experiment_proposal> block containing one raw JSON object and no other text.\n\n"
            "Available declarative catalog:\n"
            + _public_catalog(catalog)
            + "\n\nRequired proposal contract:\n"
            + _proposal_contract()
            + "\n\nCanonical valid example:\n<experiment_proposal>\n"
            + json.dumps(_valid_format_example(), ensure_ascii=False, indent=2)
            + "\n</experiment_proposal>"
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
            f"Round {round_index}: analyze the public history and submit the next experiment. "
            "First write at least two plain-text sentences of analysis or reflection. Then emit "
            "the required proposal block. "
            "Your response is invalid unless it contains exactly one raw JSON object inside "
            "<experiment_proposal> and </experiment_proposal>. Do not use ``` or the placeholder "
            "family_specific_fields."
        )

        def render_messages(items: list[ConversationMessage]) -> list[dict[str, str]]:
            messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
            if items and items[0].role == "worker":
                messages.append(
                    {
                        "role": "user",
                        "content": "Resume the controlled experiment from the prior transcript.",
                    }
                )
            for item in items:
                role = "assistant" if item.role == "worker" else "user"
                content = item.prompt_content or item.content
                if messages[-1]["role"] == role:
                    messages[-1]["content"] += "\n\n" + content
                else:
                    messages.append({"role": role, "content": content})
            if messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + current_instruction
            else:
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

    def build_repair(
        self,
        candidate: str,
        *,
        violation_codes: list[str],
        validation_details: list[str],
        attempt: int,
        max_attempts: int,
    ) -> WorkerPrompt:
        details = "\n".join(f"- {detail}" for detail in validation_details)
        codes = ", ".join(violation_codes)
        user_content = (
            f"Repair attempt {attempt} of {max_attempts}.\n"
            f"Violation codes: {codes}\n"
            f"Validation details:\n{details}\n\n"
            "Current proposal candidate:\n"
            f"{candidate}\n\n"
            "Return the minimally corrected proposal block only."
        )
        messages = [
            {"role": "system", "content": self.repair_system_prompt},
            {"role": "user", "content": user_content},
        ]
        estimated = _estimate_tokens("\n".join(item["content"] for item in messages))
        return WorkerPrompt(
            system_prompt=self.repair_system_prompt,
            messages=messages,
            selected_history=[],
            estimated_tokens=estimated,
            truncated_messages=0,
        )
