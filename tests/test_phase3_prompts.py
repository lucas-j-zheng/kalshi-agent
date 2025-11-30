"""Phase 3 Tests: Agent Prompts

Run with: pytest tests/test_phase3_prompts.py -v
"""

import pytest


class TestConvictionPrompt:
    """Test conviction extraction prompts."""

    def test_format_conviction_prompt_substitutes_placeholder(self):
        from agent.prompts.conviction import format_conviction_prompt

        prompt = format_conviction_prompt("I'm very confident Trump will win")
        assert '{user_input}' not in prompt
        assert 'Trump will win' in prompt

    def test_prompt_has_json_schema(self):
        from agent.prompts.conviction import CONVICTION_EXTRACTION_PROMPT

        assert 'has_trading_intent' in CONVICTION_EXTRACTION_PROMPT
        assert 'topic' in CONVICTION_EXTRACTION_PROMPT
        assert 'side' in CONVICTION_EXTRACTION_PROMPT
        assert 'conviction' in CONVICTION_EXTRACTION_PROMPT
        assert 'keywords' in CONVICTION_EXTRACTION_PROMPT

    def test_prompt_has_scoring_guide(self):
        from agent.prompts.conviction import CONVICTION_EXTRACTION_PROMPT

        assert 'Conviction scoring guide' in CONVICTION_EXTRACTION_PROMPT
        assert '0.9-1.0' in CONVICTION_EXTRACTION_PROMPT
        assert '0.7-0.9' in CONVICTION_EXTRACTION_PROMPT

    def test_prompt_requires_json_only(self):
        from agent.prompts.conviction import CONVICTION_EXTRACTION_PROMPT

        assert 'Return ONLY valid JSON' in CONVICTION_EXTRACTION_PROMPT

    def test_examples_cover_high_conviction(self):
        from agent.prompts.conviction import CONVICTION_EXAMPLES

        has_high = any(e['output']['conviction'] >= 0.9 for e in CONVICTION_EXAMPLES)
        assert has_high, 'Missing high conviction (>=0.9) example'

    def test_examples_cover_medium_conviction(self):
        from agent.prompts.conviction import CONVICTION_EXAMPLES

        has_medium = any(0.5 <= e['output']['conviction'] < 0.9 for e in CONVICTION_EXAMPLES)
        assert has_medium, 'Missing medium conviction (0.5-0.9) example'

    def test_examples_cover_low_conviction(self):
        from agent.prompts.conviction import CONVICTION_EXAMPLES

        has_low = any(0 < e['output']['conviction'] < 0.5 for e in CONVICTION_EXAMPLES)
        assert has_low, 'Missing low conviction (<0.5) example'

    def test_examples_cover_non_trading(self):
        from agent.prompts.conviction import CONVICTION_EXAMPLES

        has_non_trading = any(not e['output']['has_trading_intent'] for e in CONVICTION_EXAMPLES)
        assert has_non_trading, 'Missing non-trading example'

    def test_examples_have_required_fields(self):
        from agent.prompts.conviction import CONVICTION_EXAMPLES

        required_fields = ['has_trading_intent', 'topic', 'side', 'conviction',
                          'timeframe', 'keywords', 'reasoning']
        for ex in CONVICTION_EXAMPLES:
            for field in required_fields:
                assert field in ex['output'], f"Missing field '{field}' in example"


class TestExpansionPrompt:
    """Test belief expansion prompts."""

    def test_format_expansion_prompt_substitutes_placeholder(self):
        from agent.prompts.expansion import format_expansion_prompt

        prompt = format_expansion_prompt('Nike shoes are ugly')
        assert '{belief}' not in prompt
        assert 'Nike shoes are ugly' in prompt

    def test_prompt_has_required_fields(self):
        from agent.prompts.expansion import BELIEF_EXPANSION_PROMPT

        assert 'financial_implications' in BELIEF_EXPANSION_PROMPT
        assert 'search_keywords' in BELIEF_EXPANSION_PROMPT
        assert 'market_categories' in BELIEF_EXPANSION_PROMPT
        assert 'suggested_position' in BELIEF_EXPANSION_PROMPT

    def test_prompt_requires_json_only(self):
        from agent.prompts.expansion import BELIEF_EXPANSION_PROMPT

        assert 'Return ONLY valid JSON' in BELIEF_EXPANSION_PROMPT

    def test_has_minimum_examples(self):
        from agent.prompts.expansion import EXPANSION_EXAMPLES

        assert len(EXPANSION_EXAMPLES) >= 3, 'Need at least 3 expansion examples'

    def test_examples_have_required_fields(self):
        from agent.prompts.expansion import EXPANSION_EXAMPLES

        required_fields = ['original_belief', 'financial_implications',
                          'search_keywords', 'market_categories', 'suggested_position']
        for ex in EXPANSION_EXAMPLES:
            for field in required_fields:
                assert field in ex['output'], f"Missing field '{field}' in example"

    def test_examples_show_abstract_to_concrete_mapping(self):
        from agent.prompts.expansion import EXPANSION_EXAMPLES

        for ex in EXPANSION_EXAMPLES:
            assert len(ex['output']['financial_implications']) > 0
            assert len(ex['output']['search_keywords']) > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
