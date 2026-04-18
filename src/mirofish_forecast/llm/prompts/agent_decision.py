"""Agent decision prompt router — two-call CoT architecture.

Call 1 — Chain-of-Thought Reasoning (specialized per agent):
    Free-form 8-step structured reasoning chain. Each agent gets a prompt
    tailored to its analytical lens (institutional, market maker, retail).
    No format restrictions so the model can reason fully before committing.

Call 2 — Structured Output Extraction (AGENT_EXTRACT_PROMPT):
    Extracts the committal decision from the CoT reasoning as constrained JSON.
    Confidence minimum 0.55 prevents near-random hedging.
    Direction enum LONG/SHORT forces commitment (no "neutral" escape hatch).
    This prompt is shared across all agents — agent-specific reasoning is done
    in Call 1.

Reference: "Let Me Speak Freely" (Yuan et al.), GPT-4 CoT finance accuracy findings.
"""

from mirofish_forecast.llm.prompts.institutional_decision import (
    INSTITUTIONAL_COT_PROMPT,
)
from mirofish_forecast.llm.prompts.market_maker_decision import (
    MARKET_MAKER_COT_PROMPT,
)
from mirofish_forecast.llm.prompts.retail_decision import (
    RETAIL_CONTRARIAN_COT_PROMPT,
)

# ─────────────────────────────────────────────────────────────────────────────
# Agent-specific CoT prompt mapping
# ─────────────────────────────────────────────────────────────────────────────

_AGENT_COT_PROMPTS: dict[str, str] = {
    "institutional": INSTITUTIONAL_COT_PROMPT,
    "market_maker": MARKET_MAKER_COT_PROMPT,
    "retail": RETAIL_CONTRARIAN_COT_PROMPT,
}


def get_agent_cot_prompt(agent_type: str) -> str:
    """Get the specialized CoT prompt template for an agent type.

    Args:
        agent_type: One of "institutional", "market_maker", "retail".

    Returns:
        The prompt template string with format placeholders.
    """
    return _AGENT_COT_PROMPTS.get(agent_type, INSTITUTIONAL_COT_PROMPT)


# ─────────────────────────────────────────────────────────────────────────────
# Call 2: Structured Output Extraction Prompt (shared across all agents)
# ─────────────────────────────────────────────────────────────────────────────

AGENT_EXTRACT_PROMPT = """\
Based on the following analysis, extract a structured trading decision.

ANALYSIS:
{cot_reasoning}

PRICE CONSTRAINTS:
Current price: {current_price}
{instrument_price_guidance}

EXTRACTION RULES:
- direction: You MUST choose LONG or SHORT. No neutral. If genuinely 50/50, pick the \
slightly higher probability direction.
- confidence: 0.55 minimum. 0.55 = slight lean, 0.70 = solid conviction, \
0.90 = very high conviction. After applying time-of-day multiplier, do not round up.
- primary_target: The most likely price at end of this bar. Must be within realistic \
per-bar move range for {instrument_name}.
- secondary_target: Extension target if primary clears (can be null).
- stop_level: The price that proves your thesis wrong.
- regime: The market regime classification from your analysis.
- time_horizon_bars: How many bars until you expect resolution (1–{total_bars}).
- signal_bar_score: The pre-computed score was {signal_bar_score} — confirm or adjust.
- reasoning: One concise sentence explaining the key reason for this call.

Respond with EXACTLY this JSON (no extra text):
{{
    "direction": "LONG" | "SHORT",
    "confidence": <float 0.55–0.95>,
    "primary_target": <float>,
    "secondary_target": <float or null>,
    "stop_level": <float>,
    "regime": "TREND" | "RANGE" | "BREAKOUT" | "REVERSAL",
    "time_horizon_bars": <int 1–{total_bars}>,
    "signal_bar_score": <int 0–100>,
    "reasoning": "<one sentence>"
}}\
"""
