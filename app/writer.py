"""Station 1, the Writer: turns a text idea (or no idea) into one Short's content.

It works in two steps (RAG):
  1. Search: a cheap model picks the library notes this idea needs (app/search.py).
  2. Write: Claude writes the Short using only those notes, quoting them.

Run:  python -m app.writer "your idea"     (or no idea, and Claude picks a topic)
"""
import json
import re
import sys
from datetime import datetime

import anthropic

from app.config import DRAFTS_DIR, MODEL, PROMPTS_DIR
from app.costs import USD_TO_INR, call_usage, describe
from app.knowledge import Note, check_quotes, library_prompt, load_notes
from app.schemas import ShortContent
from app.search import pick_notes

DISCLAIMER = "Yeh jaankari sirf general awareness ke liye hai, medical advice nahi. Koi bimari ho to doctor se baat karein."


def past_topics(limit: int = 30) -> list[str]:
    """Topics of the most recent drafts, so Claude doesn't repeat itself."""
    files = sorted(DRAFTS_DIR.glob("*.json"))[-limit:]
    return [json.loads(f.read_text(encoding="utf-8"))["content"]["topic"] for f in files]


def build_request(idea: str | None, topic: str | None, avoid: list[str], feedback: dict | None = None) -> str:
    if idea:
        request = f"Idea from the channel owner:\n<idea>\n{idea}\n</idea>"
    elif topic:
        request = f"No idea from the channel owner today. Today's topic, chosen from the library: {topic}"
    else:
        request = "No idea from the channel owner today. Pick a useful topic yourself."
    if avoid:
        request += "\n\nTopics already made (pick something different):\n" + "\n".join(f"- {t}" for t in avoid)
    if feedback:
        prev = feedback["previous"]
        request += (
            "\n\nYou already wrote a version of this Short, and the channel owner asked for changes."
            f"\n<previous_version>\nHook: {prev['hook']}\n"
            f"Poster: {prev['poster_title']} | {' | '.join(prev['poster_points'])}\n"
            f"Script: {prev['script_hinglish']}\n</previous_version>"
            f"\n<owner_request>\n{feedback['request']}\n</owner_request>"
            "\nWrite a new version that keeps what works and makes the changes they asked for. "
            "The facts and safety rules still apply."
        )
    return request


def write_short(
    idea: str | None = None, client: anthropic.Anthropic | None = None, feedback: dict | None = None
) -> dict:
    """Search the library, then write one Short. Returns everything needed to review and save it.

    feedback: {"previous": <content of the earlier version>, "request": "what the owner wants changed"}"""
    client = client or anthropic.Anthropic()
    notes = load_notes()
    avoid = [] if feedback else past_topics()  # a redo is meant to stay on the same topic

    # Step 1: search. If it fails or finds nothing, fall back to the whole library (costs more, but still grounded).
    search_text = idea
    if feedback:
        search_text = f"{idea or feedback['previous']['topic']}\nChange requested by the owner: {feedback['request']}"
    pick, search_usage = pick_notes(search_text, avoid, notes, client)
    selected = {i: notes[i] for i in pick.note_ids} if pick and pick.note_ids else notes
    topic = feedback["previous"]["topic"] if feedback and not idea else (pick.topic if pick else None)

    # Step 2: write, with only the selected notes in the prompt.
    system_prompt = (PROMPTS_DIR / "writer_system.md").read_text(encoding="utf-8") + "\n\n" + library_prompt(selected)
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        # If a safety check declines the request, Anthropic retries it on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system_prompt,
        messages=[{"role": "user", "content": build_request(idea, topic, avoid, feedback)}],
        output_format=ShortContent,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this idea: {response.stop_details}")

    content = response.parsed_output
    steps = [search_usage, call_usage("write", response)]
    return {
        "content": content,
        "notes_sent": list(selected),
        "notes_total": len(notes),
        "usage": {"steps": steps, "total_cost_usd": round(sum(s.get("cost_usd", 0) for s in steps), 4)},
        "problems": check_quotes(content.sources, notes),
    }


def source_names(content: ShortContent, notes: dict[str, Note]) -> list[str]:
    """'ICMR-NIN Dietary Guidelines for Indians 2024, Guideline 15, PDF p. 111' -> the document name."""
    names = [notes[s.note_id].source.split(",")[0] for s in content.sources if s.note_id in notes]
    return list(dict.fromkeys(names))


def full_description(content: ShortContent, notes: dict[str, Note]) -> str:
    sources = "; ".join(source_names(content, notes))
    return f"{content.youtube_description}\n\nSource: {sources}\n{DISCLAIMER}"


def save_draft(result: dict, idea: str | None, redo_of: str | None = None) -> str:
    content = result["content"]
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", content.topic.lower()).strip("-")[:40]
    path = DRAFTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}.json"
    draft = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
        "idea": idea,
        "redo_of": redo_of,
        "notes_sent": result["notes_sent"],
        "usage": result["usage"],
        "grounding_problems": result["problems"],
        "youtube_description_full": full_description(content, load_notes()),
        "content": content.model_dump(),
    }
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def print_draft(result: dict) -> None:
    c, problems, notes = result["content"], result["problems"], load_notes()
    print(f"\nLIBRARY SEARCH: sent {len(result['notes_sent'])} of {result['notes_total']} notes to the writer")
    print("  " + ", ".join(result["notes_sent"]))
    print(f"\nTOPIC: {c.topic}   [{c.pillar} / {c.format}]")
    print(f"\nHOOK: {c.hook}")
    print(f"\nPOSTER: {c.poster_title}")
    for point in c.poster_points:
        print(f"  - {point}")
    print(f"\nSCRIPT (Hinglish):\n{c.script_hinglish}")
    print(f"\nSCRIPT (Devanagari):\n{c.script_devanagari}")
    print(f"\nYOUTUBE TITLE: {c.youtube_title}")
    print(f"DESCRIPTION:\n{full_description(c, notes)}")
    print(f"HASHTAGS: {' '.join(c.hashtags)}")
    print("\nSOURCES:")
    for s in c.sources:
        where = notes[s.note_id].source if s.note_id in notes else "UNKNOWN NOTE"
        print(f"  - [{s.note_id}] {where}\n    \"{s.quote}\"")
    if problems:
        print("\nGROUNDING CHECK: PROBLEMS - don't post until these are fixed:")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"\nGROUNDING CHECK: OK - all {len(c.sources)} quotes found word-for-word in the library")
    print(f"\nFACT-CHECK: {c.fact_check.verdict.upper()}\n{c.fact_check.notes}")
    print("\nCOST:")
    for step in result["usage"]["steps"]:
        print(f"  {describe(step)}")
    total = result["usage"]["total_cost_usd"]
    print(f"  total: ${total} (about Rs {total * USD_TO_INR:.2f})")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # so Devanagari prints in Windows terminals
    idea = " ".join(sys.argv[1:]).strip() or None
    print("Writing a Short" + (f" from your idea: {idea!r}" if idea else " on a topic Claude picks") + " ...")
    try:
        result = write_short(idea)
    except anthropic.AuthenticationError:
        sys.exit("Your API key was rejected. Check ANTHROPIC_API_KEY in .env.")
    except anthropic.RateLimitError:
        sys.exit("Rate limit or spend limit reached. Check Settings > Billing in the Claude Console.")
    except anthropic.APIConnectionError:
        sys.exit("Couldn't reach the Claude API. Check your internet connection.")
    print_draft(result)
    print(f"\nSaved: {save_draft(result, idea)}")


if __name__ == "__main__":
    main()
