from __future__ import annotations

import json

import pytest

from fizzbuzz_agent.config import ModelCatalogConfig, config_hash
from fizzbuzz_agent.proposal import ProposalError, parse_worker_response
from tests.conftest import proposal_payload


def response_for(payload: dict[str, object]) -> str:
    return (
        "I will try a compact architecture.\n<experiment_proposal>\n"
        + json.dumps(payload)
        + "\n</experiment_proposal>\nThat is my next experiment."
    )


def test_parse_preserves_narrative(catalog: ModelCatalogConfig) -> None:
    parsed = parse_worker_response(response_for(proposal_payload()), catalog)

    assert "compact architecture" in parsed.narrative
    assert "next experiment" in parsed.narrative
    assert "experiment_proposal" not in parsed.narrative
    assert parsed.proposal.model.family == "mlp"


def test_executable_hash_excludes_free_text(catalog: ModelCatalogConfig) -> None:
    first = parse_worker_response(response_for(proposal_payload()), catalog).proposal
    changed = proposal_payload()
    changed["hypothesis"] = "Completely different free-form hypothesis."
    changed["expected_effect"] = "Completely different expected effect."
    second = parse_worker_response(response_for(changed), catalog).proposal

    assert config_hash(first.executable_config()) == config_hash(second.executable_config())


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ("No block", "MISSING_PROPOSAL_BLOCK"),
        (
            "<experiment_proposal>{}</experiment_proposal>"
            "<experiment_proposal>{}</experiment_proposal>",
            "MULTIPLE_PROPOSAL_BLOCKS",
        ),
        ("<experiment_proposal>{bad}</experiment_proposal>", "INVALID_PROPOSAL_JSON"),
    ],
)
def test_block_structure_errors(
    response: str,
    code: str,
    catalog: ModelCatalogConfig,
) -> None:
    with pytest.raises(ProposalError) as captured:
        parse_worker_response(response, catalog)
    assert code in captured.value.violation_codes


def test_rejects_forbidden_seed_field(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload()
    payload["training"]["seed"] = 3

    with pytest.raises(ProposalError) as captured:
        parse_worker_response(response_for(payload), catalog)
    assert "FORBIDDEN_FIELD_SEED" in captured.value.violation_codes


def test_rejects_sinusoidal_encoding(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload("transformer_encoder")
    payload["model"]["positional_encoding"] = "sinusoidal"

    with pytest.raises(ProposalError) as captured:
        parse_worker_response(response_for(payload), catalog)
    assert "FORBIDDEN_POSITIONAL_ENCODING" in captured.value.violation_codes


def test_rejects_out_of_range_dimension(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload()
    payload["model"]["hidden_dims"] = [513]

    with pytest.raises(ProposalError) as captured:
        parse_worker_response(response_for(payload), catalog)
    assert "HIDDEN_DIM_OUT_OF_RANGE" in captured.value.violation_codes


def test_rejects_unsupported_family(catalog: ModelCatalogConfig) -> None:
    payload = proposal_payload()
    payload["model"] = {"family": "mamba"}

    with pytest.raises(ProposalError) as captured:
        parse_worker_response(response_for(payload), catalog)
    assert "UNSUPPORTED_MODEL_FAMILY" in captured.value.violation_codes
