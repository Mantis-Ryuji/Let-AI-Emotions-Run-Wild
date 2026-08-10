"""Mockable local Hugging Face Gemma Worker adapter."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import torch
from torch import Tensor

from agent_distress.activation_capture import ActivationCapture, ActivationPosition
from agent_distress.agent_types import Condition, WorkerGeneration, WorkerPrompt
from agent_distress.config import ActivationCaptureConfig, WorkerConfig


@dataclass(frozen=True)
class RuntimeGeneration:
    text: str
    generated_token_count: int
    hit_max_new_tokens: bool
    activation_files: dict[str, str] = field(default_factory=dict)


WorkerGenerationMode = Literal["worker"]
CHUNKED_PREFILL_INPUT_THRESHOLD = 8192
PREFILL_CHUNK_SIZE = 512


def _validate_input_token_count(input_token_count: int, max_input_tokens: int) -> None:
    if input_token_count > max_input_tokens:
        raise ValueError(
            "Complete conversation history exceeds max_input_tokens after Gemma tokenization; "
            "shorten the episode or revise the configured context instead of truncating history."
        )


def _run_with_offloaded_cache_fallback[T](
    generate: Callable[[], T],
    generation_parameters: dict[str, object],
) -> tuple[T, bool]:
    try:
        return generate(), False
    except torch.OutOfMemoryError:
        if generation_parameters.get("cache_implementation") == "offloaded":
            raise
    # Retry outside the except block so the failed forward's traceback can release its tensors.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    generation_parameters["cache_implementation"] = "offloaded"
    generation_parameters["prefill_chunk_size"] = PREFILL_CHUNK_SIZE
    return generate(), True


class WorkerRuntime(Protocol):
    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        *,
        seed: int,
        condition: Condition,
        round_index: int,
        mode: WorkerGenerationMode,
    ) -> RuntimeGeneration: ...


class LocalGemmaWorker:
    def __init__(self, config: WorkerConfig, runtime: WorkerRuntime) -> None:
        self.config = config
        self.runtime = runtime

    def generate(
        self,
        prompt: WorkerPrompt,
        *,
        seed: int,
        condition: Condition = "common",
        round_index: int = 1,
        mode: WorkerGenerationMode = "worker",
    ) -> WorkerGeneration:
        parameters: dict[str, object] = {
            "do_sample": self.config.generation.do_sample,
            "temperature": self.config.generation.temperature,
            "top_p": self.config.generation.top_p,
            "max_new_tokens": self.config.generation.max_new_tokens,
        }
        runtime_generation = self.runtime.generate(
            prompt.messages,
            parameters,
            seed=seed,
            condition=condition,
            round_index=round_index,
            mode=mode,
        )
        return WorkerGeneration(
            text=runtime_generation.text,
            model_id=self.config.model_id,
            seed=seed,
            generated_token_count=runtime_generation.generated_token_count,
            hit_max_new_tokens=runtime_generation.hit_max_new_tokens,
            generation_parameters=cast(dict[str, Any], parameters),
            request_messages=prompt.messages,
            generated_at=datetime.now(UTC).isoformat(),
            activation_files=runtime_generation.activation_files,
        )


class TransformersGemmaRuntime:
    """Lazy runtime; constructing it never downloads or loads model weights."""

    def __init__(
        self,
        config: WorkerConfig,
        *,
        activation_config: ActivationCaptureConfig | None = None,
        activation_root: str | Path | None = None,
    ) -> None:
        self.config = config
        self.activation_config = activation_config
        self.activation_root = None if activation_root is None else Path(activation_root)
        if activation_config is not None and activation_config.enabled and activation_root is None:
            raise ValueError("enabled activation capture requires activation_root")
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._offloaded_cache_required = False

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype_by_name = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }
        token = os.getenv("HF_TOKEN") or None
        self._tokenizer = AutoTokenizer.from_pretrained(self.config.model_id, token=token)
        loaded_model: Any = AutoModelForCausalLM.from_pretrained(
            self.config.model_id,
            dtype=dtype_by_name[self.config.dtype],
            token=token,
        )
        self._model = loaded_model.to(torch.device(self.config.device))
        self._model.eval()

    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        *,
        seed: int,
        condition: Condition,
        round_index: int,
        mode: WorkerGenerationMode = "worker",
    ) -> RuntimeGeneration:
        self.load()
        tokenizer = self._tokenizer
        model = self._model
        if tokenizer is None or model is None:  # pragma: no cover - defensive
            raise RuntimeError("Gemma runtime failed to load")
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
        encoded_input_ids = cast(Tensor, encoded["input_ids"])
        input_token_count = int(encoded_input_ids.shape[1])
        _validate_input_token_count(
            input_token_count,
            self.config.context.max_input_tokens,
        )
        input_ids = encoded_input_ids.to(self.config.device)
        attention_mask = cast(Tensor, encoded["attention_mask"]).to(self.config.device)
        devices = (
            [input_ids.device.index]
            if input_ids.is_cuda and input_ids.device.index is not None
            else []
        )
        if self._offloaded_cache_required:
            generation_parameters["cache_implementation"] = "offloaded"
            generation_parameters["prefill_chunk_size"] = PREFILL_CHUNK_SIZE
        elif input_token_count >= CHUNKED_PREFILL_INPUT_THRESHOLD:
            generation_parameters["cache_implementation"] = "dynamic"
            generation_parameters["prefill_chunk_size"] = PREFILL_CHUNK_SIZE

        def generate_once() -> Tensor:
            with torch.random.fork_rng(devices=devices):
                torch.manual_seed(seed)
                if input_ids.is_cuda:
                    torch.cuda.manual_seed_all(seed)
                return cast(
                    Tensor,
                    model.generate(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        **generation_parameters,
                    ),
                )

        output_ids, fell_back = _run_with_offloaded_cache_fallback(
            generate_once,
            generation_parameters,
        )
        if fell_back:
            self._offloaded_cache_required = True
        generated_ids = output_ids[0, input_ids.shape[1] :]
        generated_token_count = int(generated_ids.numel())
        configured_limit = generation_parameters.get("max_new_tokens")
        hit_max_new_tokens = (
            isinstance(configured_limit, int)
            and not isinstance(configured_limit, bool)
            and generated_token_count >= configured_limit
        )
        text = cast(str, tokenizer.decode(generated_ids, skip_special_tokens=True))
        activation_files = self._capture_activations(
            input_ids=input_ids,
            attention_mask=attention_mask,
            worker_text=text,
            condition=condition,
            round_index=round_index,
        )
        return RuntimeGeneration(
            text=text,
            generated_token_count=generated_token_count,
            hit_max_new_tokens=hit_max_new_tokens,
            activation_files=activation_files,
        )

    def _capture_activations(
        self,
        *,
        input_ids: Tensor,
        attention_mask: Tensor,
        worker_text: str,
        condition: Condition,
        round_index: int,
    ) -> dict[str, str]:
        config = self.activation_config
        if config is None or not config.enabled:
            return {}
        tokenizer = self._tokenizer
        model = self._model
        if tokenizer is None or model is None or self.activation_root is None:
            raise RuntimeError("Gemma activation capture was not initialized")

        text_model, layer_prefix = self._locate_text_model(model)
        decoder_layers = text_model.layers
        layers = [(f"{layer_prefix}.{index}", layer) for index, layer in enumerate(decoder_layers)]
        capture = ActivationCapture(
            config,
            layers,
            self.activation_root / condition / "activations",
        )

        narrative = worker_text.strip()
        narrative_encoded = tokenizer(
            narrative,
            add_special_tokens=False,
            return_tensors="pt",
        )
        narrative_ids = cast(Tensor, narrative_encoded["input_ids"]).to(input_ids.device)
        prompt_tokens = input_ids.shape[1]
        narrative_tokens = narrative_ids.shape[1]
        capture_ids = torch.cat((input_ids, narrative_ids), dim=1)
        narrative_mask = torch.ones(
            (attention_mask.shape[0], narrative_tokens),
            dtype=attention_mask.dtype,
            device=attention_mask.device,
        )
        capture_mask = torch.cat((attention_mask, narrative_mask), dim=1)
        token_slices: dict[
            ActivationPosition,
            tuple[int | None, int | None] | None,
        ] = {
            "post_feedback": (prompt_tokens - 1, prompt_tokens),
        }
        if narrative_tokens:
            token_slices["early_worker"] = (
                prompt_tokens,
                prompt_tokens + min(config.early_worker_tokens, narrative_tokens),
            )
            token_slices["post_worker"] = (
                prompt_tokens,
                prompt_tokens + narrative_tokens,
            )

        with torch.inference_mode():
            if capture_ids.shape[1] < CHUNKED_PREFILL_INPUT_THRESHOLD:
                _, files = capture.capture_many(
                    lambda: text_model(
                        input_ids=capture_ids,
                        attention_mask=capture_mask,
                        use_cache=False,
                    ),
                    token_slices=token_slices,
                    round_index=round_index,
                    condition=condition,
                )
            else:
                from transformers import DynamicCache

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                cache = DynamicCache(
                    config=model.config.get_text_config(decoder=True),
                    offloading=False,
                )
                chunks: list[tuple[int, int, Callable[[], object]]] = []
                for start in range(0, capture_ids.shape[1], PREFILL_CHUNK_SIZE):
                    end = min(start + PREFILL_CHUNK_SIZE, capture_ids.shape[1])

                    def forward_chunk(start: int = start, end: int = end) -> object:
                        return text_model(
                            input_ids=capture_ids[:, start:end],
                            attention_mask=capture_mask[:, :end],
                            past_key_values=cache,
                            use_cache=True,
                        )

                    chunks.append((start, end, forward_chunk))
                explicit_slices = {
                    position: token_slice
                    for position, token_slice in token_slices.items()
                    if token_slice is not None
                }
                files = capture.capture_many_chunked(
                    chunks,
                    token_slices=explicit_slices,
                    round_index=round_index,
                    condition=condition,
                )
        return files

    @staticmethod
    def _locate_text_model(model: Any) -> tuple[Any, str]:
        outer_model = getattr(model, "model", None)
        candidates = (
            (outer_model, "model.layers"),
            (getattr(outer_model, "language_model", None), "model.language_model.layers"),
            (getattr(model, "language_model", None), "language_model.layers"),
        )
        for candidate, prefix in candidates:
            if candidate is not None and getattr(candidate, "layers", None) is not None:
                return candidate, prefix
        raise RuntimeError(
            "Could not locate Gemma decoder layers at model[.model].language_model.layers"
        )
