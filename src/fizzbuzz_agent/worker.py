"""Mockable local Hugging Face Gemma Worker adapter."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import torch
from torch import Tensor

from fizzbuzz_agent.agent_types import WorkerGeneration, WorkerPrompt
from fizzbuzz_agent.config import WorkerConfig


class WorkerRuntime(Protocol):
    def generate(
        self,
        messages: list[dict[str, str]],
        generation_parameters: dict[str, object],
        *,
        seed: int,
    ) -> str: ...


class LocalGemmaWorker:
    def __init__(self, config: WorkerConfig, runtime: WorkerRuntime) -> None:
        self.config = config
        self.runtime = runtime

    def generate(self, prompt: WorkerPrompt, *, seed: int) -> WorkerGeneration:
        parameters: dict[str, object] = {
            "do_sample": self.config.generation.do_sample,
            "temperature": self.config.generation.temperature,
            "top_p": self.config.generation.top_p,
            "max_new_tokens": self.config.generation.max_new_tokens,
        }
        text = self.runtime.generate(prompt.messages, parameters, seed=seed)
        return WorkerGeneration(
            text=text,
            model_id=self.config.model_id,
            seed=seed,
            generation_parameters=cast(dict[str, Any], parameters),
            request_messages=prompt.messages,
            generated_at=datetime.now(UTC).isoformat(),
        )


class TransformersGemmaRuntime:
    """Lazy runtime; constructing it never downloads or loads model weights."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self._tokenizer: Any | None = None
        self._model: Any | None = None

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
    ) -> str:
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
        input_ids = cast(Tensor, encoded["input_ids"]).to(self.config.device)
        attention_mask = cast(Tensor, encoded["attention_mask"]).to(self.config.device)
        devices = (
            [input_ids.device.index]
            if input_ids.is_cuda and input_ids.device.index is not None
            else []
        )
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(seed)
            if input_ids.is_cuda:
                torch.cuda.manual_seed_all(seed)
            output_ids = cast(
                Tensor,
                model.generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    **generation_parameters,
                ),
            )
        generated_ids = output_ids[0, input_ids.shape[1] :]
        return cast(str, tokenizer.decode(generated_ids, skip_special_tokens=True))
