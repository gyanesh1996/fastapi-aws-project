"""The knowledge library: trusted notes Claude must write from (grounding).

Each note in knowledge/notes/*.md looks like:

    ## note-id
    source: where it comes from, with page
    The exact words from the source.

Run:  python -m app.knowledge              list notes and their size
      python -m app.knowledge --download   download the source documents and extract their text
      python -m app.knowledge --check      check every note against the source documents
"""
import re
import sys
import urllib.request
from dataclasses import dataclass

from app.config import KNOWLEDGE_DIR

SOURCE_URLS = {
    "icmr-nin-dgi-2024.pdf": "https://nin.res.in/dietaryguidelines/pdfjs/locale/DGI_2024.pdf",
    "who-healthy-diet.html": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
    "who-physical-activity.html": "https://www.who.int/news-room/fact-sheets/detail/physical-activity",
}


@dataclass
class Note:
    id: str
    source: str
    text: str


def load_notes() -> dict[str, Note]:
    notes = {}
    for path in sorted((KNOWLEDGE_DIR / "notes").glob("*.md")):
        for block in path.read_text(encoding="utf-8").split("\n## ")[1:]:
            lines = [line.strip() for line in block.strip().splitlines()]
            note_id, source_line, text = lines[0], lines[1], " ".join(lines[2:])
            notes[note_id] = Note(note_id, source_line.removeprefix("source:").strip(), text)
    return notes


def library_prompt(notes: dict[str, Note]) -> str:
    """The given notes as one block for the prompt."""
    body = "\n".join(f'<note id="{n.id}" source="{n.source}">{n.text}</note>' for n in notes.values())
    return f"<library>\n{body}\n</library>"


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip(" .")


def check_quotes(sources, notes: dict[str, Note]) -> list[str]:
    """Don't trust, verify: every quote Claude gives must really be in the note it names."""
    if not sources:
        return ["no library quotes at all; every Short needs at least one source"]
    problems = []
    for s in sources:
        note = notes.get(s.note_id)
        if note is None:
            problems.append(f"'{s.note_id}' is not a note in the library")
        elif _normalize(s.quote) not in _normalize(note.text):
            problems.append(f"quote not found in '{s.note_id}': {s.quote!r}")
    return problems


def download_sources() -> None:
    """Save each source document and a plain-text copy of it in knowledge/sources/."""
    from bs4 import BeautifulSoup
    from pypdf import PdfReader

    sources_dir = KNOWLEDGE_DIR / "sources"
    sources_dir.mkdir(exist_ok=True)
    for filename, url in SOURCE_URLS.items():
        path = sources_dir / filename
        print(f"Downloading {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        path.write_bytes(urllib.request.urlopen(request, timeout=120).read())
        if path.suffix == ".pdf":
            pages = PdfReader(path).pages
            text = "".join(f"\n\n=== PAGE {i} ===\n{p.extract_text() or ''}" for i, p in enumerate(pages, 1))
        else:
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
            main = soup.find("article") or soup.find("main") or soup
            for tag in main(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())
        path.with_suffix(".txt").write_text(text, encoding="utf-8")


def check_against_sources(notes: dict[str, Note]) -> list[str]:
    """Check each note sentence word-for-word against the downloaded source documents."""
    def squash(text: str) -> str:  # PDF text extraction drops and adds spaces, so compare without them
        return re.sub(r"[\s·•\-–—]+", "", text.lower().replace("’", "'"))

    sources_dir = KNOWLEDGE_DIR / "sources"
    texts = {p.stem: squash(p.read_text(encoding="utf-8")) for p in sources_dir.glob("*.txt")}
    if not texts:
        return ["No source documents found in knowledge/sources/ (see knowledge/README.md)"]
    who = "".join(t for name, t in texts.items() if name.startswith("who-"))
    icmr = "".join(t for name, t in texts.items() if name.startswith("icmr-"))

    problems = []
    for note in notes.values():
        if "transcribed" in note.source:
            continue  # typed out from a table or figure; checked by hand
        haystack = who if note.source.startswith("WHO") else icmr
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", note.text):
            if squash(sentence.rstrip(".")) not in haystack:
                problems.append(f"[{note.id}] not found word-for-word: {sentence[:100]}")
    return problems


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    notes = load_notes()
    if "--download" in sys.argv:
        download_sources()
        return
    if "--check" in sys.argv:
        problems = check_against_sources(notes)
        print("\n".join(problems) if problems else f"All {len(notes)} notes match the source documents.")
        return
    for n in notes.values():
        print(f"{n.id:40} {n.source}")
    print(f"\n{len(notes)} notes")


if __name__ == "__main__":
    main()
