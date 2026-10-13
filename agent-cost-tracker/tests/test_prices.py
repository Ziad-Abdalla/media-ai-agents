import pytest

from agent_cost_tracker.prices import cost_usd


def test_haiku_short_prompt():
    # 100K input at $0.10/M + 1M output at $0.50/M (100K is still the cheap tier)
    assert cost_usd("claude-haiku-5-5", 100_000, 1_000_000) == pytest.approx(0.51)


def test_haiku_long_prompt_uses_higher_price():
    # 200K input tokens is over the 100K line, so input is $0.50/M
    assert cost_usd("claude-haiku-5-5", 200_000, 0) == pytest.approx(0.10)


def test_cache_tokens_count_toward_long_prompt_line():
    # 60K fresh + 60K read from cache = 120K prompt -> long-prompt prices
    cost = cost_usd("claude-haiku-5-5", 60_000, 0, cache_read_tokens=60_000)
    assert cost == pytest.approx(60_000 * 0.50 / 1e6 + 60_000 * 0.05 / 1e6)


def test_cache_write_is_125_percent_of_input():
    assert cost_usd("claude-sonnet-5-5", 0, 0, cache_creation_tokens=1_000_000) == pytest.approx(2.50)


def test_sonnet_cache_read():
    assert cost_usd("claude-sonnet-5-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.20)


def test_unknown_model_fails_loudly():
    with pytest.raises(KeyError):
        cost_usd("some-new-model", 10, 10)
