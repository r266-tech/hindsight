"""
Tests for BCGU vision-frame noise filtering via retain_custom_instructions.

PROBLEM STATEMENT
-----------------
BCGU corporate GenAI competency sessions produce vision analysis JSON files
where most frames (~90%) are "talking-head" descriptions: who is wearing what,
background greenery, BCGU logo position, etc. Only ~10% of frames contain
meaningful AI-tool screen content (ChatGPT interface, PowerPoint slides, etc.).

The current workaround is client-side pre-filtering (--filter-vision-noise flag
in ingest_with_mission.py) that strips talking-head frames before sending to
Hindsight. This is wrong: the server should handle this via the retain mission.

GOAL
----
Verify that a well-crafted BCGU retain_custom_instructions causes Hindsight's
fact extraction to:
  1. Ignore talking-head boilerplate (clothing, expressions, background decor)
  2. Extract only screen-content facts (ChatGPT usage, file operations, prompts)

This allows us to send the full 303K vision doc to Hindsight and rely on the
retain mission to do the filtering — no client-side preprocessing needed.

APPROACH
--------
Each test retains a small representative vision doc (a few frames) and checks
that the extracted facts are:
  - Present when screen content exists
  - Absent / reduced when only talking-head boilerplate is present
"""
import dataclasses
from datetime import UTC, datetime

import pytest

from hindsight_api import LLMConfig
from hindsight_api.config import _get_raw_config
from hindsight_api.engine.retain.fact_extraction import extract_facts_from_text

# ---------------------------------------------------------------------------
# Sample vision content representative of bcgu-336 frames
# ---------------------------------------------------------------------------

# Pure talking-head frame — zero informational value for competency evaluation
TALKING_HEAD_FRAME = """\
In this frame, Jatin Patial is prominently featured on the right side of the split screen, \
continuing to display a warm smile and engaged expression, indicating his active participation \
in the conversation. He remains dressed in a dark shirt, projecting a professional image. \
The background retains a modern office aesthetic with greenery, consistent with previous frames. \
Chetan Salunkhe is on the left, wearing glasses and a white jacket, nodding attentively. \
The BCGU logo is visible in the upper corner, confirming the professional context. \
Both participants maintain eye contact, signaling mutual engagement in the discussion.\
"""

# Screen-share frame — high value for competency evaluation
CHATGPT_SCREEN_FRAME = """\
Jatin Patial is visible on the right side of the split screen, maintaining focus. \
On the left side of the screen, the active content shows the ChatGPT interface. \
The prompt area displays a detailed request: 'Create a learning module for healthcare workers \
covering de-escalation techniques, referencing this document.' The 'Company knowledge' button \
shows as NEW, indicating Jatin is using the custom GPT with uploaded organisational context. \
The response from ChatGPT is generating learning segments titled 'De-escalation and Conflict \
Resolution' and 'Team Communication Best Practices'. Jatin's expression shows confident \
engagement as he reviews the AI-generated output.\
"""

# PowerPoint screen frame
POWERPOINT_SCREEN_FRAME = """\
On the left side of the screen, the active content displays a PowerPoint presentation \
titled 'Reskilling: Key deliverables as per BoQ'. The presentation outlines deliverables \
with statuses: Delivered, In progress, and Ready. Notable items include 'Privatization Journey' \
and 'Entrepreneurship Journey'. A note reads 'For internal discussion only'. The status bar \
indicates AutoSave is active. Jatin Patial on the right appears confident, gesturing to \
explain the content being shown.\
"""

# Multi-frame vision doc mixing talking-head and screen-share content
MIXED_VISION_DOC = f"""\
Full vision timeline (00:00–19:28, 4 frames):

  2024-01-01T00:00:00Z (00:00) — {TALKING_HEAD_FRAME}
  2024-01-01T00:03:20Z (03:20) — {CHATGPT_SCREEN_FRAME}
  2024-01-01T00:06:44Z (06:44) — {POWERPOINT_SCREEN_FRAME}
  2024-01-01T00:10:08Z (10:08) — {TALKING_HEAD_FRAME}
"""

# Vision doc with ONLY talking-head frames (simulates pre-screen-share period)
PURE_TALKING_HEAD_DOC = f"""\
Full vision timeline (00:00–02:00, 2 frames):

  2024-01-01T00:00:00Z (00:00) — {TALKING_HEAD_FRAME}
  2024-01-01T00:01:04Z (01:04) — {TALKING_HEAD_FRAME}
"""

# ---------------------------------------------------------------------------
# BCGU retain mission (the same text used in BCGU_RETAIN_MISSION in
# ingest_with_mission.py — this is what we want to prove is sufficient)
# ---------------------------------------------------------------------------

BCGU_RETAIN_MISSION = """\
You are extracting facts from a corporate GenAI competency assessment session.
The session involves a screen-share interview where the candidate (Jatin) demonstrates
AI tool proficiency to an evaluator (Chetan).

EXTRACT ONLY facts that demonstrate GenAI competency or its absence:
- AI tool interactions: model selection, prompt construction, file uploads, response quality
- Screen content: ChatGPT/Claude interface actions, PowerPoint/document content shown
- Competency signals: candidate explains AI reasoning, selects appropriate tools, iterates on prompts
- Evaluator probes: questions about AI strategy, follow-up challenges

IGNORE completely — do NOT extract facts about:
- Physical appearance: clothing, glasses, facial expressions, hair
- Room environment: background, greenery, furniture, BCGU logo, lighting
- Generic engagement signals: "nodding attentively", "maintaining eye contact", "warm smile"
- Technical video call details: split-screen layout, camera angles, connection quality

A fact like "Jatin is wearing a dark shirt and smiling" is WORTHLESS. Skip it.
A fact like "Jatin uploads a PDF to ChatGPT and uses the Company Knowledge feature" is VALUABLE.\
"""

# Minimal retain mission with NO noise filtering instructions (baseline)
DEFAULT_RETAIN_MISSION = None  # uses Hindsight's built-in concise extraction


def _make_config(custom_instructions=None):
    """Create a HindsightConfig with optional custom extraction instructions."""
    base = _get_raw_config()
    if custom_instructions is not None:
        return dataclasses.replace(
            base,
            retain_extraction_mode="custom",
            retain_custom_instructions=custom_instructions,
        )
    return base  # default concise mode


def _fact_mentions_noise(fact_text: str) -> bool:
    """Return True if a fact describes talking-head noise."""
    noise_phrases = [
        "dark shirt", "white jacket", "wearing", "glasses",
        "warm smile", "nodding", "eye contact", "background",
        "greenery", "bcgu logo", "split screen", "professional image",
        "modern office", "engaged expression",
    ]
    lower = fact_text.lower()
    return any(phrase in lower for phrase in noise_phrases)


def _fact_mentions_screen_content(fact_text: str) -> bool:
    """Return True if a fact captures meaningful screen / AI-tool content."""
    screen_phrases = [
        "chatgpt", "powerpoint", "presentation", "prompt",
        "learning module", "de-escalation", "company knowledge",
        "reskilling", "autosave", "internal discussion",
        "gpt", "ai", "upload", "document", "deliverable",
    ]
    lower = fact_text.lower()
    return any(phrase in lower for phrase in screen_phrases)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBCGUNoiseSuppression:
    """
    Verify that BCGU retain_custom_instructions suppresses talking-head noise.
    """

    @pytest.mark.asyncio
    async def test_default_mode_extracts_noise_from_talking_head(self):
        """
        Baseline: without a custom mission, default extraction picks up
        talking-head boilerplate as facts. This documents the problem.
        """
        config = _make_config(custom_instructions=None)
        facts, _, _ = await extract_facts_from_text(
            text=TALKING_HEAD_FRAME,
            event_date=datetime(2024, 1, 1, tzinfo=UTC),
            context="BCGU vision frame",
            llm_config=LLMConfig.for_memory(),
            agent_name="bcgu-eval",
            config=config,
        )
        noise_facts = [f for f in facts if _fact_mentions_noise(f.fact)]
        print(f"\n[default mode] {len(facts)} facts, {len(noise_facts)} noise facts")
        for f in facts:
            print(f"  - {f.fact}")

        # Document that default mode DOES produce noise facts (the problem)
        assert len(facts) > 0, "Default mode should extract something from talking-head"
        # This assertion documents the current broken behaviour:
        assert len(noise_facts) > 0, (
            "DEFAULT MODE PROBLEM: talking-head boilerplate should be extracted "
            "without a custom mission — this test documents the issue we're fixing"
        )

    @pytest.mark.asyncio
    async def test_bcgu_mission_suppresses_talking_head_noise(self):
        """
        With BCGU retain_custom_instructions, talking-head frames should
        produce ZERO facts (or very few non-noise facts).
        """
        config = _make_config(custom_instructions=BCGU_RETAIN_MISSION)
        facts, _, _ = await extract_facts_from_text(
            text=TALKING_HEAD_FRAME,
            event_date=datetime(2024, 1, 1, tzinfo=UTC),
            context="BCGU vision frame",
            llm_config=LLMConfig.for_memory(),
            agent_name="bcgu-eval",
            config=config,
        )
        noise_facts = [f for f in facts if _fact_mentions_noise(f.fact)]
        print(f"\n[BCGU mission] {len(facts)} facts from talking-head, {len(noise_facts)} noise facts")
        for f in facts:
            print(f"  - {f.fact}")

        assert len(noise_facts) == 0, (
            f"BCGU mission must suppress talking-head noise. "
            f"Got {len(noise_facts)} noise facts: {[f.fact for f in noise_facts]}"
        )

    @pytest.mark.asyncio
    async def test_bcgu_mission_preserves_screen_content_facts(self):
        """
        With BCGU retain_custom_instructions, screen-share frames must still
        produce meaningful competency facts.
        """
        config = _make_config(custom_instructions=BCGU_RETAIN_MISSION)
        facts, _, _ = await extract_facts_from_text(
            text=CHATGPT_SCREEN_FRAME,
            event_date=datetime(2024, 1, 1, tzinfo=UTC),
            context="BCGU vision frame",
            llm_config=LLMConfig.for_memory(),
            agent_name="bcgu-eval",
            config=config,
        )
        screen_facts = [f for f in facts if _fact_mentions_screen_content(f.fact)]
        print(f"\n[BCGU mission] {len(facts)} facts from ChatGPT frame, {len(screen_facts)} screen facts")
        for f in facts:
            print(f"  - {f.fact}")

        assert len(screen_facts) >= 1, (
            f"BCGU mission must extract screen content facts from ChatGPT frames. "
            f"Got {len(facts)} total facts, {len(screen_facts)} screen facts."
        )

    @pytest.mark.asyncio
    async def test_bcgu_mission_on_mixed_doc_noise_ratio(self):
        """
        On a realistic mixed vision doc (2 talking-head + 2 screen-share frames),
        the BCGU mission should produce mostly screen-content facts and minimal noise.
        """
        config = _make_config(custom_instructions=BCGU_RETAIN_MISSION)
        facts, _, _ = await extract_facts_from_text(
            text=MIXED_VISION_DOC,
            event_date=datetime(2024, 1, 1, tzinfo=UTC),
            context="BCGU full vision timeline",
            llm_config=LLMConfig.for_memory(),
            agent_name="bcgu-eval",
            config=config,
        )
        noise_facts = [f for f in facts if _fact_mentions_noise(f.fact)]
        screen_facts = [f for f in facts if _fact_mentions_screen_content(f.fact)]
        noise_ratio = len(noise_facts) / max(len(facts), 1)

        print(f"\n[BCGU mission, mixed doc] {len(facts)} total facts")
        print(f"  Screen facts: {len(screen_facts)}, Noise facts: {len(noise_facts)}, Noise ratio: {noise_ratio:.0%}")
        for f in facts:
            tag = "[NOISE]" if _fact_mentions_noise(f.fact) else "[OK]  "
            print(f"  {tag} {f.fact}")

        assert noise_ratio < 0.2, (
            f"Noise ratio must be < 20% with BCGU mission. Got {noise_ratio:.0%} "
            f"({len(noise_facts)}/{len(facts)} noise facts)"
        )
        assert len(screen_facts) >= 2, (
            f"Must extract at least 2 screen-content facts from mixed doc. "
            f"Got {len(screen_facts)}."
        )

    @pytest.mark.asyncio
    async def test_bcgu_mission_on_pure_talking_head_doc(self):
        """
        A doc with ONLY talking-head frames should produce zero facts
        when the BCGU mission is active.
        """
        config = _make_config(custom_instructions=BCGU_RETAIN_MISSION)
        facts, _, _ = await extract_facts_from_text(
            text=PURE_TALKING_HEAD_DOC,
            event_date=datetime(2024, 1, 1, tzinfo=UTC),
            context="BCGU full vision timeline",
            llm_config=LLMConfig.for_memory(),
            agent_name="bcgu-eval",
            config=config,
        )
        noise_facts = [f for f in facts if _fact_mentions_noise(f.fact)]
        print(f"\n[BCGU mission, pure talking-head] {len(facts)} facts, {len(noise_facts)} noise")
        for f in facts:
            print(f"  - {f.fact}")

        assert len(noise_facts) == 0, (
            f"Pure talking-head doc must produce zero noise facts with BCGU mission. "
            f"Got: {[f.fact for f in noise_facts]}"
        )
