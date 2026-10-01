"""Retrieval, the "R" in RAG: pick only the library notes an idea needs.

A small, cheap model reads a catalog of the notes (id + first few words) and
picks the relevant ones. It understands Hinglish ("cheeni" = sugar), which a
plain keyword search wouldn't.

Run:  python -m app.search "your idea"     see which notes get picked, without writing a Short
"""
import sys

import anthropic

from app.config import PROMPTS_DIR, SEARCH_MODEL
from app.costs import call_usage, describe
from app.knowledge import Note, load_notes
from app.schemas import NotePick

CATALOG_WORDS = 20
MAX_NOTES = 12


def catalog(notes: dict[str, Note]) -> str:
    return "\n".join(f"{n.id}: {' '.join(n.text.split()[:CATALOG_WORDS])}..." for n in notes.values())


def pick_notes(
    idea: str | None, avoid: list[str], notes: dict[str, Note], client: anthropic.Anthropic
) -> tuple[NotePick | None, dict]:
    """Returns the pick (None if the search failed) and the call's usage."""
    request = f"<idea>\n{idea}\n</idea>" if idea else "No idea from the owner today."
    if avoid:
        request += "\n\nTopics already made:\n" + "\n".join(f"- {t}" for t in avoid)
    response = client.messages.parse(
        model=SEARCH_MODEL,
        max_tokens=2048,
        system=(PROMPTS_DIR / "search_system.md").read_text(encoding="utf-8") + f"\n\n<catalog>\n{catalog(notes)}\n</catalog>",
        messages=[{"role": "user", "content": request}],
        output_format=NotePick,
    )
    usage = call_usage("search", response)
    pick = response.parsed_output
    if response.stop_reason == "refusal" or pick is None:
        return None, usage
    # Drop ids that aren't real notes, and duplicates.
    pick.note_ids = [i for i in dict.fromkeys(pick.note_ids) if i in notes][:MAX_NOTES]
    return pick, usage


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    idea = " ".join(sys.argv[1:]).strip() or None
    notes = load_notes()
    pick, usage = pick_notes(idea, [], notes, anthropic.Anthropic())
    if pick is None:
        sys.exit("The search didn't return a result.")
    print(f"TOPIC: {pick.topic}\nPICKED {len(pick.note_ids)} of {len(notes)} notes:")
    for note_id in pick.note_ids:
        print(f"  - {note_id}")
    print(f"\n{describe(usage)}")


if __name__ == "__main__":
    main()
