"""Station 1, the Writer: turns a text idea (or no idea) into one Short's content.

Run:  python -m app.writer "your idea"     (or no idea, and Claude picks a topic)
"""
import json
import re
import sys
from datetime import datetime

import anthropic

from app.config import DRAFTS_DIR, MODEL, PROMPTS_DIR
from app.schemas import ShortContent

# USD per million tokens: (input, output). Check platform.claude.com pricing if these change.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00)}
USD_TO_INR = 88

SYSTEM_PROMPT = (PROMPTS_DIR / "writer_system.md").read_text(encoding="utf-8")


def past_topics(limit: int = 30) -> list[str]:
    """Topics of the most recent drafts, so Claude doesn't repeat itself."""
    files = sorted(DRAFTS_DIR.glob("*.json"))[-limit:]
    return [json.loads(f.read_text(encoding="utf-8"))["content"]["topic"] for f in files]


def build_request(idea: str | None, avoid: list[str]) -> str:
    if idea:
        request = f"Idea from the channel owner:\n<idea>\n{idea}\n</idea>"
    else:
        request = "No idea from the channel owner today. Pick a useful topic yourself."
    if avoid:
        request += "\n\nTopics already made (pick something different):\n" + "\n".join(f"- {t}" for t in avoid)
    return request


def write_short(idea: str | None = None, client: anthropic.Anthropic | None = None) -> tuple[ShortContent, dict]:
    """Ask Claude for one Short. Returns the content and a usage/cost summary."""
    client = client or anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        # If a safety check declines the request, Anthropic retries it on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_request(idea, past_topics())}],
        output_format=ShortContent,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this idea: {response.stop_details}")

    usage = {
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    if response.model in PRICES:
        in_price, out_price = PRICES[response.model]
        usage["cost_usd"] = round(
            (usage["input_tokens"] * in_price + usage["output_tokens"] * out_price) / 1_000_000, 4
        )
    return response.parsed_output, usage


def save_draft(content: ShortContent, usage: dict, idea: str | None) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", content.topic.lower()).strip("-")[:40]
    path = DRAFTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}.json"
    draft = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "idea": idea,
        "usage": usage,
        "content": content.model_dump(),
    }
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def print_draft(c: ShortContent, usage: dict) -> None:
    print(f"\nTOPIC: {c.topic}   [{c.pillar} / {c.format}]")
    print(f"\nHOOK: {c.hook}")
    print(f"\nPOSTER: {c.poster_title}")
    for point in c.poster_points:
        print(f"  - {point}")
    print(f"\nSCRIPT (Hinglish):\n{c.script_hinglish}")
    print(f"\nSCRIPT (Devanagari):\n{c.script_devanagari}")
    print(f"\nYOUTUBE TITLE: {c.youtube_title}")
    print(f"DESCRIPTION:\n{c.youtube_description}")
    print(f"HASHTAGS: {' '.join(c.hashtags)}")
    print("\nSOURCES:")
    for s in c.sources:
        print(f"  - {s.name}: {s.supports}")
    print(f"\nFACT-CHECK: {c.fact_check.verdict.upper()}\n{c.fact_check.notes}")
    cost = usage.get("cost_usd")
    cost_text = f"${cost} (about Rs {cost * USD_TO_INR:.2f})" if cost is not None else "unknown"
    print(f"\nTOKENS: {usage['input_tokens']} in, {usage['output_tokens']} out | COST: {cost_text} | MODEL: {usage['model']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # so Devanagari prints in Windows terminals
    idea = " ".join(sys.argv[1:]).strip() or None
    print("Writing a Short" + (f" from your idea: {idea!r}" if idea else " on a topic Claude picks") + " ...")
    try:
        content, usage = write_short(idea)
    except anthropic.AuthenticationError:
        sys.exit("Your API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        sys.exit("Rate limit or spend limit reached. Check Settings > Billing in the Claude Console.")
    except anthropic.APIConnectionError:
        sys.exit("Couldn't reach the Claude API. Check your internet connection.")
    print_draft(content, usage)
    print(f"\nSaved: {save_draft(content, usage, idea)}")


if __name__ == "__main__":
    main()
