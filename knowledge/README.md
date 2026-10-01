# Knowledge library

These notes are the **only** health facts the Writer is allowed to use. Claude
must quote a note for every fact, and the code checks that each quote really
is in the note. This is called **grounding**: the AI writes from documents
we trust instead of from its memory.

For each idea, a cheap model first searches the library and picks the notes
that idea needs, so the Writer gets about 5–12 notes instead of all of them.
This is **RAG** (Retrieval-Augmented Generation).

## What's in it

84 notes copied word-for-word from:

| Source | Link |
|---|---|
| ICMR-NIN Dietary Guidelines for Indians 2024 | https://nin.res.in/dietaryguidelines/pdfjs/locale/DGI_2024.pdf |
| WHO fact sheet: Healthy diet | https://www.who.int/news-room/fact-sheets/detail/healthy-diet |
| WHO fact sheet: Physical activity | https://www.who.int/news-room/fact-sheets/detail/physical-activity |

Topics: India today (NFHS-5 numbers), balanced plate, vegetables and fruits,
oils and fats, protein, sugar, salt, processed foods, water and cooking,
movement, weight, sleep, screen time and food labels.

**Not covered yet:** stress and mental health. Ideas about them will come
back as `no_source` until notes are added.

## Adding a note

Add it to the right file in `notes/` (or make a new `.md` file):

```markdown
## short-unique-id
source: Document name, section, PDF p. 12
The exact words from the document. Copy them; don't rewrite them.
```

Write `transcribed` in the source line if you typed it out from a table or
figure, because that can't be checked automatically.

## Checking the notes

The original documents are saved in `sources/`. That folder isn't in git
because the PDF is 24 MB.

```powershell
python -m app.knowledge              # list all notes and their size
python -m app.knowledge --download   # download the documents into sources/ (first time only; takes a few minutes)
python -m app.knowledge --check      # check every note word-for-word against the documents
```
