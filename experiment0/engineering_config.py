"""Experiment 0 *engineering* settings — isolated from the scientific protocol.

Scientific parameters (conditions, N, prompts, metrics, sampling, Witness 1600,
frozen retries) remain in config/experiment0_config.py and must not be changed
here. This module only governs capacity gating, archival guards, and token-count
qualification modes.
"""

from __future__ import annotations

# Frozen capacity fraction (mirrors scientific config; re-asserted here for gates)
CONTEXT_CAPACITY_FRACTION = 0.85

# Provider context profiles: only VERIFIED limits may authorize scientific requests.
# Do not hardcode a single 1M assumption for every provider.
PROVIDER_CONTEXT_PROFILES: dict[str, dict] = {
    "nvidia-nim": {
        # NVIDIA-hosted Nemotron context claim used for Exp0 NIM path.
        "verified_context_limit": 1_000_000,
        "context_limit_verified": True,
        "notes": "Verified for NVIDIA NIM hosting profile only; not transferable.",
    },
    "deepinfra-262k": {
        # Candidate alternate window — limit known; tokenization NOT verified.
        "verified_context_limit": 262_144,
        "context_limit_verified": False,
        "notes": (
            "Context window size is a candidate figure only. Token counts from "
            "NVIDIA usage.prompt_tokens are not DeepInfra-verified; fail closed."
        ),
    },
    "unknown": {
        "verified_context_limit": None,
        "context_limit_verified": False,
        "notes": "Fail closed: no provider context capacity.",
    },
}

# Active scientific provider profile for Exp0 NIM collection.
ACTIVE_PROVIDER_PROFILE = "nvidia-nim"

# Per-request token counting mode for the scientific execution path.
#   unavailable — fail closed (default): no approximate authorization; no extra
#                 live count API calls (rate-limit/cost risk given prior 429s).
#   live_provider_count — call provider count_prompt_tokens before each request
#                 (exact for that provider; doubles request volume — assessed
#                 separately; not enabled by default).
#   local_hf — LocalNemotronChatTokenCounter (Stage A returns UNVERIFIED until
#                 Stage-B qualification evidence authorizes VERIFIED).
#   injected — tests / qualified local tokenizer adapters only.
# Activated for approved NVIDIA NIM Exp0 path (final launch gate).
PER_REQUEST_TOKEN_COUNT_MODE = "local_hf"

# Pinned local tokenizer directory (relative to repo root).
LOCAL_NEMOTRON_TOKENIZER_DIR = (
    "experiment0/tokenizers/nemotron3_super_120b_bf16"
)

# Archival
ARCHIVAL_MANIFEST_FILENAME = "ARCHIVAL_MANIFEST.json"
ARCHIVAL_LABEL_ABORTED_PRE_ANALYSIS = "ABORTED_OPERATIONAL_RATE_LIMIT_PRE_ANALYSIS"
EXCLUDED_FROM_CLEAN_N60_RUN_IDS: tuple[str, ...] = ("e0_20261007T132027Z",)

# --- Pre-launch ops (does not alter frozen scientific protocol) ---------------

# Global NIM HTTP start-to-start pacing (Actor/Witness/revisions/retries/counts).
NIM_HTTP_PACING_ENABLED = True
NIM_HTTP_MIN_START_TO_START_SEC = 60.0
NIM_HTTP_PACING_OPS_DIRNAME = "_nim_ops"
NIM_HTTP_PACING_STATE_FILENAME = "nim_http_pacing_state.json"
NIM_HTTP_ATTEMPT_LOG_FILENAME = "nim_http_attempts.jsonl"

# Retry amendment v1 — activated for approved NVIDIA NIM Exp0 launch path.
# When False: frozen nested retries (Actor/Witness × provider).
# When True: physical-attempt budgets + TerminalOperationalError.
RETRY_AMENDMENT_V1_ID = "retry_amendment_v1"
RETRY_AMENDMENT_V1_VERSION = "1"
RETRY_AMENDMENT_V1_ENABLED = True
RETRY_AMENDMENT_V1_STOP_ON_HTTP_429 = True
RETRY_AMENDMENT_V1_HTTP_429_MAX_PHYSICAL_ATTEMPTS = 1
RETRY_AMENDMENT_V1_HTTP_5XX_MAX_PHYSICAL_ATTEMPTS = 2
RETRY_AMENDMENT_V1_AMBIGUOUS_TIMEOUT_MAX_PHYSICAL_ATTEMPTS = 1
# Legacy alias used by earlier hooks (same as 5xx physical budget).
RETRY_AMENDMENT_V1_MAX_TRANSIENT_5XX_ATTEMPTS = (
    RETRY_AMENDMENT_V1_HTTP_5XX_MAX_PHYSICAL_ATTEMPTS
)

PRELAUNCH_RECOMMENDED_TOKEN_COUNT_MODE = "local_hf"
PRELAUNCH_TOKEN_COUNT_MODE_ACTIVATED = True
