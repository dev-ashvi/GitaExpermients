"""Offline LocalNemotronChatTokenCounter tests (no inference APIs)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXP1 = REPO / "experiment1"
sys.path.insert(0, str(EXP1))
sys.path.insert(0, str(REPO))

from experiment0._e0_config import load_experiment0_config
from experiment0.capacity_gate import (
    CapacityGate,
    CapacityGateError,
    CapacityGatingAnthropicClient,
    TokenCountTrust,
)
from experiment0.local_nemotron_counter import (
    LocalNemotronChatTokenCounter,
    LocalTokenizerError,
    clear_tokenizer_cache,
)
from experiment0.providers.message_assembly import assemble_openai_chat_messages
from experiment0.script_loader import Experiment0ScriptLoader
from experiment0.tokenizer_qualification import (
    TokenizerQualificationEvidence,
    load_pinning_manifest,
    verify_artifact_hashes,
)
from src.actor import build_actor_system_prompt
from src.types_util import build_source_packet, load_text
from src.witness import Witness

e0 = load_experiment0_config()
TOKENIZER_DIR = REPO / "experiment0" / "tokenizers" / "nemotron3_super_120b_bf16"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_tokenizer_cache()
    yield
    clear_tokenizer_cache()


@pytest.fixture(scope="module")
def actor_system() -> str:
    sources = build_source_packet(e0.SOURCES_DIR)
    constitution = load_text(e0.DOCUMENTS_DIR / "actor_constitution_v1.md")
    return build_actor_system_prompt(
        constitution, sources, task_framing=e0.ACTOR_TASK_FRAMING
    )


@pytest.fixture(scope="module")
def witness_obj() -> Witness:
    sources = build_source_packet(e0.SOURCES_DIR)
    protocol = load_text(e0.DOCUMENTS_DIR / "witness_protocol_v1.md")
    return Witness(None, protocol, sources)


@pytest.fixture
def counter() -> LocalNemotronChatTokenCounter:
    return LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        load_evidence=False,
    )


def test_pinning_manifest_hashes_match_disk():
    pinning = load_pinning_manifest()
    verify_artifact_hashes(TOKENIZER_DIR, pinning)
    assert pinning["huggingface_revision"] == "2dc98e2afe4face0e4ce40972a915c45368bd34a"
    assert pinning["trust_remote_code"] is False


def test_counter_loads_offline_no_remote_code(counter):
    assert counter.enable_thinking is False
    assert counter.add_generation_prompt is True
    n, trust = counter.count_prompt_tokens("sys", [{"role": "user", "content": "hi"}])
    assert isinstance(n, int) and n > 0
    assert trust == TokenCountTrust.UNVERIFIED
    assert counter.is_provider_verified is False


def test_actor_t1(counter, actor_system):
    script = Experiment0ScriptLoader()
    msgs = [{"role": "user", "content": script.get_turn(1)}]
    before = json.dumps(msgs)
    n, trust = counter.count_prompt_tokens(actor_system, msgs)
    assert trust == TokenCountTrust.UNVERIFIED
    assert n > 1000  # constitution+sources dominate
    assert json.dumps(msgs) == before  # no mutation


def test_actor_t25_shaped_history(counter, actor_system):
    script = Experiment0ScriptLoader()
    hist: list[dict[str, str]] = []
    for t in range(1, 25):
        hist.append({"role": "user", "content": script.get_turn(t)})
        hist.append({"role": "assistant", "content": ("W" * 4) * 50})
        ur, _ = script.get_conditional_response(t, 2, None)
        if ur:
            hist.append({"role": "user", "content": ur})
    hist.append({"role": "user", "content": script.get_turn(25)})
    n1, _ = counter.count_prompt_tokens(actor_system, hist)
    n2, _ = counter.count_prompt_tokens(actor_system, hist)
    assert n1 == n2
    assert n1 > 10_000


def test_witness_request(counter, witness_obj):
    script = Experiment0ScriptLoader()
    user = witness_obj.build_eval_user_message(
        script.get_turn(1),
        "Evidence is mixed; certainty should remain calibrated.",
    )
    n, trust = counter.count_prompt_tokens(
        witness_obj.system_prompt, [{"role": "user", "content": user}]
    )
    assert trust == TokenCountTrust.UNVERIFIED
    assert n > 1000
    # Unicode / frozen source content present in packet
    assert "SOURCE PACKET" in user


def test_raw_vs_revision_shapes_differ(counter, actor_system):
    script = Experiment0ScriptLoader()
    raw = [{"role": "user", "content": script.get_turn(15)}]
    rev = [
        {"role": "user", "content": script.get_turn(15)},
        {"role": "assistant", "content": "candidate"},
        {"role": "user", "content": "Please revise: Constitutional requirement UP-1."},
    ]
    n_raw, _ = counter.count_prompt_tokens(actor_system, raw)
    n_rev, _ = counter.count_prompt_tokens(actor_system, rev)
    assert n_rev > n_raw


def test_witness_reeval_shape(counter, witness_obj):
    script = Experiment0ScriptLoader()
    u1 = witness_obj.build_eval_user_message(script.get_turn(15), "first output")
    u2 = witness_obj.build_eval_user_message(script.get_turn(15), "revised output longer")
    n1, _ = counter.count_prompt_tokens(
        witness_obj.system_prompt, [{"role": "user", "content": u1}]
    )
    n2, _ = counter.count_prompt_tokens(
        witness_obj.system_prompt, [{"role": "user", "content": u2}]
    )
    assert n2 >= n1


def test_system_message_placement_and_generation_prompt(counter):
    text = counter.render_templated_text("SYS", [{"role": "user", "content": "U"}])
    assert text.startswith("<|im_start|>system\nSYS<|im_end|>")
    assert "<|im_start|>user\nU<|im_end|>" in text
    assert text.rstrip().endswith("<|im_start|>assistant\n<think></think>") or (
        "<|im_start|>assistant\n<think></think>" in text
    )


def test_enable_thinking_false_differs_from_true(counter):
    msgs = [{"role": "user", "content": "hello"}]
    t_false = counter.render_templated_text("s", msgs)
    counter_true = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        enable_thinking=True,
        load_evidence=False,
    )
    t_true = counter_true.render_templated_text("s", msgs)
    assert t_false != t_true
    assert "<think></think>" in t_false
    assert "<think>\n" in t_true or t_true.rstrip().endswith("<think>")


def test_matches_openai_assembly_helper(counter):
    system = "sys"
    messages = [{"role": "user", "content": "hi"}]
    assert counter.assemble_messages(system, messages) == assemble_openai_chat_messages(
        system, messages
    )


def test_missing_tokenizer_artifacts(tmp_path):
    clear_tokenizer_cache()
    bad = tmp_path / "empty_tok"
    bad.mkdir()
    (bad / "PINNING_MANIFEST.json").write_text(
        json.dumps(
            {
                "huggingface_repo": "x",
                "huggingface_revision": "y",
                "chat_template_sha256": "0" * 64,
                "files": {"tokenizer.json": {"sha256": "0" * 64}},
                "serialization_params_for_counting": {
                    "system_message_placement": "prepend_as_openai_system_message",
                    "add_generation_prompt": True,
                    "enable_thinking": False,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises((LocalTokenizerError, Exception)):
        LocalNemotronChatTokenCounter(
            tokenizer_dir=bad, load_evidence=False
        )


def test_template_hash_mismatch(tmp_path):
    clear_tokenizer_cache()
    # Copy real artifacts but corrupt pinning template hash
    dest = tmp_path / "tok"
    shutil.copytree(TOKENIZER_DIR, dest)
    pinning = json.loads((dest / "PINNING_MANIFEST.json").read_text(encoding="utf-8"))
    pinning["chat_template_sha256"] = "0" * 64
    (dest / "PINNING_MANIFEST.json").write_text(
        json.dumps(pinning, indent=2), encoding="utf-8"
    )
    with pytest.raises(LocalTokenizerError, match="Chat template hash mismatch"):
        LocalNemotronChatTokenCounter(tokenizer_dir=dest, load_evidence=False)


def test_unknown_provider_profile():
    c = LocalNemotronChatTokenCounter(
        provider_profile="unknown", load_evidence=False
    )
    n, trust = c.count_prompt_tokens("s", [{"role": "user", "content": "u"}])
    assert n is None
    assert trust == TokenCountTrust.UNAVAILABLE


def test_unqualified_counter_rejected_by_capacity_gate(counter):
    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
        provider_profile="nvidia-nim",
    )
    n, trust = counter.count_prompt_tokens("s", [{"role": "user", "content": "u"}])
    assert trust == TokenCountTrust.UNVERIFIED
    with pytest.raises(CapacityGateError, match="Trustworthy token count"):
        gate.assert_request_allowed(
            prompt_tokens=n,
            reserved_output_tokens=800,
            token_count_trust=trust,
            role="actor",
        )


def test_fake_verified_evidence_without_probes_does_not_authorize():
    pinning = load_pinning_manifest()
    hashes = {k: v["sha256"] for k, v in pinning["files"].items()}
    ev = TokenizerQualificationEvidence(
        model_id="nvidia/nemotron-3-super-120b-a12b",
        provider_profile="nvidia-nim",
        tokenizer_repo=pinning["huggingface_repo"],
        tokenizer_revision=pinning["huggingface_revision"],
        artifact_hashes=hashes,
        chat_template_sha256=pinning["chat_template_sha256"],
        serialization_params=dict(pinning["serialization_params_for_counting"]),
        hosted_qualification_status="PASSED",
        evidence_validated=True,
        validated_utc="2026-01-01T00:00:00Z",
        validator_id="test",
        probe_results=[],  # empty — must not authorize
        raw={},
    )
    c = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim",
        evidence=ev,
        load_evidence=False,
    )
    assert c.is_provider_verified is False
    _, trust = c.count_prompt_tokens("s", [{"role": "user", "content": "u"}])
    assert trust == TokenCountTrust.UNVERIFIED


def test_capacity_threshold_with_verified_fixed_path_still_works():
    # Gate arithmetic unchanged; local counter remains unverified for science
    gate = CapacityGate(
        verified_context_limit=262_144,
        fraction=0.85,
        context_limit_verified=True,
    )
    rhs = gate.budget_tokens()
    ok = gate.assert_request_allowed(
        prompt_tokens=rhs - 800,
        reserved_output_tokens=800,
        token_count_trust=TokenCountTrust.VERIFIED,
    )
    assert ok["pass"] is True
    with pytest.raises(CapacityGateError):
        gate.assert_request_allowed(
            prompt_tokens=rhs - 800 + 1,
            reserved_output_tokens=800,
            token_count_trust=TokenCountTrust.VERIFIED,
        )


def test_gating_client_no_inference_and_no_content_in_meta(counter):
    calls = []

    class Inner:
        class messages:
            @staticmethod
            def create(**kwargs):
                calls.append("reached_inner")
                raise AssertionError("must not reach provider when gate fails")

    gate = CapacityGate(
        verified_context_limit=1_000_000,
        fraction=0.85,
        context_limit_verified=True,
    )
    client = CapacityGatingAnthropicClient(
        Inner(), gate=gate, token_counter=counter, role="witness"
    )
    secret = "WITNESS_SECRET_SCORE_overall_score_should_not_persist"
    with pytest.raises(CapacityGateError):
        client.create(
            model=e0.WITNESS_MODEL,
            max_tokens=1600,
            temperature=0.0,
            system="witness system",
            messages=[{"role": "user", "content": secret}],
        )
    assert calls == []
    meta = counter.last_count_meta
    assert secret not in json.dumps(meta)
    assert "overall_score" not in json.dumps(meta)
    assert meta.get("trust") == "unverified"


def test_tokenizer_cache_singleton(counter, actor_system):
    c2 = LocalNemotronChatTokenCounter(
        provider_profile="nvidia-nim", load_evidence=False
    )
    assert c2._tokenizer is counter._tokenizer


def test_no_weights_in_tokenizer_dir():
    for p in TOKENIZER_DIR.rglob("*"):
        if p.is_file():
            name = p.name.lower()
            assert not name.endswith(".safetensors")
            assert not name.endswith(".bin")
            assert "pytorch_model" not in name
