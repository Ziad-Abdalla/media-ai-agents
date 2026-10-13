"""Price table for the models we use, in US dollars per 1 million tokens.

Source: Anthropic pricing as of 2026-10 (https://docs.claude.com/en/docs/about-claude/pricing).
If Anthropic changes prices, this file is the only place to update.
"""

# Cache writes (5-minute cache) cost 1.25x the normal input price.
CACHE_WRITE_MULTIPLIER = 1.25

# Haiku 5.5 is cheaper when the whole prompt is at most 100K tokens.
HAIKU_LONG_PROMPT_THRESHOLD = 100_000

PRICES = {
    "claude-haiku-5-5": {
        "input": 0.10,
        "output": 0.50,
        "cache_read": 0.01,  # assumed: 0.1x input, not published separately
    },
    # Our own key, not a real model id: the row used when a Haiku prompt is over 100K tokens.
    "claude-haiku-5-5:long": {
        "input": 0.50,
        "output": 2.50,
        "cache_read": 0.05,  # assumed: 0.1x input
    },
    "claude-sonnet-5-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_read": 0.20,
    },
}


def price_key(model: str, prompt_tokens: int) -> str:
    """Pick the row of the price table for this model and prompt size."""
    if model == "claude-haiku-5-5" and prompt_tokens > HAIKU_LONG_PROMPT_THRESHOLD:
        return "claude-haiku-5-5:long"
    if model not in PRICES:
        raise KeyError(f"No price for model {model!r}. Add it to prices.py first.")
    return model


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Dollar cost of one API call."""
    prompt_tokens = input_tokens + cache_creation_tokens + cache_read_tokens
    p = PRICES[price_key(model, prompt_tokens)]
    total = (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_creation_tokens * p["input"] * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * p["cache_read"]
    )
    return total / 1_000_000
