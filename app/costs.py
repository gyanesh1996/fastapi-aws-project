"""What each Claude call costs, worked out from the tokens it used."""

# USD per million tokens: (input, output). Check platform.claude.com pricing if these change.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
USD_TO_INR = 88


def call_usage(step: str, response) -> dict:
    usage = {
        "step": step,
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    # The API may answer with a dated id such as claude-haiku-4-5-20251001, so match by prefix.
    prices = next((p for name, p in PRICES.items() if response.model.startswith(name)), None)
    if prices:
        usage["cost_usd"] = round(
            (usage["input_tokens"] * prices[0] + usage["output_tokens"] * prices[1]) / 1_000_000, 4
        )
    return usage


def describe(usage: dict) -> str:
    cost = usage.get("cost_usd")
    cost_text = f"${cost} (Rs {cost * USD_TO_INR:.2f})" if cost is not None else "cost unknown"
    return f"{usage['step']}: {usage['input_tokens']} in, {usage['output_tokens']} out, {cost_text} [{usage['model']}]"
