from __future__ import annotations

import pytest
import torch

from fizzbuzz_agent.config import ModelCatalogConfig
from fizzbuzz_agent.model_factory import ParameterLimitError, build_model
from fizzbuzz_agent.schemas import ExperimentProposal
from tests.conftest import make_proposal, proposal_payload


@pytest.mark.parametrize(
    "family",
    ["mlp", "rnn", "gru", "lstm", "cnn1d", "tcn", "transformer_encoder"],
)
def test_all_model_families_return_four_logits(
    family: str,
    catalog: ModelCatalogConfig,
) -> None:
    proposal = make_proposal(family)
    built = build_model(proposal, catalog, max_sequence_length=6)
    built.model.eval()
    input_ids = torch.tensor(
        [[1, 2, 7, 5, 10, 10], [10, 10, 1, 5, 10, 10], [9, 9, 9, 9, 9, 10]]
    )
    attention_mask = input_ids.ne(10)

    with torch.inference_mode():
        logits = built.model(input_ids, attention_mask)

    assert logits.shape == (3, 4)
    assert torch.isfinite(logits).all()
    assert 0 < built.parameter_count <= catalog.global_limits.parameter_count.max
    assert len(built.executable_config_hash) == 64


def test_one_hot_input_is_supported(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload()
    payload["input"] = {"encoding": "one_hot", "embedding_dim": None, "padding": "right"}
    proposal = ExperimentProposal.model_validate(payload, strict=True)
    built = build_model(proposal, catalog, max_sequence_length=6)
    input_ids = torch.tensor([[1, 2, 3, 10, 10, 10]])
    assert built.model(input_ids, input_ids.ne(10)).shape == (1, 4)


def test_parameter_limit_is_checked_before_real_build(catalog: ModelCatalogConfig) -> None:
    payload = catalog.model_dump(mode="python")
    payload["global_limits"]["parameter_count"]["max"] = 10
    tiny_limit = ModelCatalogConfig.model_validate(payload, strict=True)

    with pytest.raises(ParameterLimitError):
        build_model(make_proposal(), tiny_limit, max_sequence_length=6)
