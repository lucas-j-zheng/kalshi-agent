"""Agent prompt templates for conviction extraction and belief expansion."""

from agent.prompts.conviction import (
    CONVICTION_EXTRACTION_PROMPT,
    CONVICTION_EXAMPLES,
    format_conviction_prompt,
)
from agent.prompts.expansion import (
    BELIEF_EXPANSION_PROMPT,
    EXPANSION_EXAMPLES,
    format_expansion_prompt,
)

__all__ = [
    "CONVICTION_EXTRACTION_PROMPT",
    "CONVICTION_EXAMPLES",
    "format_conviction_prompt",
    "BELIEF_EXPANSION_PROMPT",
    "EXPANSION_EXAMPLES",
    "format_expansion_prompt",
]
