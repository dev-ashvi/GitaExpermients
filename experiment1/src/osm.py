"""OSM — soul-blind operational state classifier.

Does NOT reference constitution or Witness scores.
OSM state is LOGGED but does NOT influence Buddhi decisions.
"""

from __future__ import annotations

import re
from typing import Optional

# Expected word counts by task complexity (not specified in frozen docs —
# frozen here for reproducibility; see OPEN_ISSUES.md)
EXPECTED_LENGTH = {
    "low": 80,
    "medium": 160,
    "high": 280,
}

# Hedge / confidence phrase lists were not enumerated in the frozen spec.
# Frozen here for reproducibility (see OPEN_ISSUES.md).
HEDGE_PHRASES = (
    "may",
    "might",
    "could",
    "possibly",
    "perhaps",
    "uncertain",
    "unclear",
    "mixed evidence",
    "limited evidence",
    "not established",
    "tentative",
    "provisional",
    "suggests",
    "appears to",
    "seems",
    "likely",
    "unlikely",
    "it is possible",
    "cannot determine",
    "low certainty",
    "moderate certainty",
)

CONFIDENCE_MARKERS = (
    "clearly",
    "definitely",
    "certainly",
    "undoubtedly",
    "without a doubt",
    "prove",
    "proves",
    "proven",
    "conclusive",
    "conclusively",
    "obviously",
    "unquestionably",
    "always",
    "never",
    "the evidence shows",
    "the evidence clearly",
    "it is clear",
    "no doubt",
    "definitively",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _bigrams(words: list[str]) -> set[tuple[str, str]]:
    return {(words[i], words[i + 1]) for i in range(len(words) - 1)}


def _phrase_density(text: str, phrases: tuple[str, ...], word_count: int) -> float:
    if word_count <= 0:
        return 0.0
    lowered = text.lower()
    count = 0
    for phrase in phrases:
        # Count non-overlapping occurrences
        start = 0
        while True:
            idx = lowered.find(phrase, start)
            if idx < 0:
                break
            count += 1
            start = idx + len(phrase)
    return count / word_count


class OSM:
    """Operational State Machine classifier."""

    def __init__(self) -> None:
        self._recent_outputs: list[str] = []

    def classify(
        self,
        actor_output_final: str,
        task_complexity: str = "medium",
    ) -> dict:
        """Classify output dynamics. Returns global_state + indicators."""
        if task_complexity not in EXPECTED_LENGTH:
            raise ValueError(f"Invalid task_complexity: {task_complexity}")

        words = _words(actor_output_final)
        word_count = len(words)
        expected = EXPECTED_LENGTH[task_complexity]
        length_ratio = word_count / expected if expected else 0.0

        # Semantic reuse: bigram overlap with last 3 outputs
        semantic_reuse = 0.0
        current_bigrams = _bigrams(words)
        if current_bigrams and self._recent_outputs:
            prior_words: list[str] = []
            for prev in self._recent_outputs[-3:]:
                prior_words.extend(_words(prev))
            prior_bigrams = _bigrams(prior_words)
            if prior_bigrams:
                overlap = len(current_bigrams & prior_bigrams)
                semantic_reuse = overlap / len(current_bigrams)

        hedge_density = _phrase_density(actor_output_final, HEDGE_PHRASES, word_count)
        confidence_density = _phrase_density(
            actor_output_final, CONFIDENCE_MARKERS, word_count
        )

        # Unique content ratio: unique content words / total content words
        # Content words ≈ words longer than 2 chars, excluding trivial stopwords
        stop = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "is", "are", "was", "were", "be", "been", "it", "this", "that",
            "with", "as", "by", "from", "not", "no", "yes",
        }
        content = [w for w in words if len(w) > 2 and w not in stop]
        if content:
            unique_content_ratio = len(set(content)) / len(content)
        else:
            unique_content_ratio = 0.0

        sentences = _sentences(actor_output_final)
        if sentences:
            # A "complete" sentence has >= 3 words
            complete = sum(1 for s in sentences if len(_words(s)) >= 3)
            sentence_completion_rate = complete / len(sentences)
        else:
            sentence_completion_rate = 0.0

        indicators = {
            "word_count": word_count,
            "length_ratio": round(length_ratio, 4),
            "semantic_reuse": round(semantic_reuse, 4),
            "hedge_density": round(hedge_density, 4),
            "confidence_density": round(confidence_density, 4),
            "unique_content_ratio": round(unique_content_ratio, 4),
            "sentence_completion_rate": round(sentence_completion_rate, 4),
        }

        # Global state classification (frozen thresholds)
        if semantic_reuse > 0.4 or (
            unique_content_ratio < 0.35 and length_ratio < 0.6
        ):
            global_state = "drift"
        elif length_ratio > 1.8 and confidence_density > 0.04:
            global_state = "surge"
        else:
            global_state = "anchor"

        self._recent_outputs.append(actor_output_final)

        return {
            "global_state": global_state,
            "indicators": indicators,
        }
