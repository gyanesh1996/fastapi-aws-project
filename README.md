# Health Shorts Agent

An AI-assisted platform for **lifestyle change for Indian people**: desi diet,
movement for desk jobs, sleep, stress, and preventing lifestyle diseases like
diabetes and BP. It has three parts that share one database:

1. **Shorts pipeline**: makes a YouTube Short every day, with your approval.
2. **Public home page** on your own domain.
3. **Private admin dashboard** (login, only you): website + YouTube stats,
   content studio, approvals.

```
   AI picks a topic   │   YOU send a text idea
                      ▼
 ① Writer (Claude: writes, or turns your idea into simple Hinglish + fact-checks)
                      ▼
 ② Poster ──► ③ Short video (your recorded voice, or a natural AI voice)
                      ▼
 ④ Approval (Telegram or admin dashboard)
                      ▼
 ⑤ YouTube upload + latest tips on the home page
                      ▼
 ⑥ Stats ──► admin dashboard, and the AI learns what works
```

This project is also a hands-on way to learn AI, one concept per phase.

## Roadmap

| Phase | What we build | AI / tech concept |
|---|---|---|
| 0 | Repo, API keys, YouTube channel | Setup |
| 1 | Writer: AI writes content, and turns your text ideas into simple Hinglish + fact-checks them | Prompting, structured output |
| 1b | Knowledge library: the Writer may only use facts from trusted notes, and code checks every quote. A cheap model first picks the notes each idea needs | Grounding, RAG |
| 2 | Poster generator; the AI checks its own poster | Vision |
| 3 | Short video: your voice or AI voice + captions + music | Text-to-speech, speech-to-text |
| 4 | Telegram approval; send ideas and voice recordings from your phone | Human-in-the-loop |
| 5 | YouTube upload | OAuth, YouTube Data API |
| 6 | Public home page | Web backend |
| 7 | Admin login + dashboard (website visitors, YouTube stats, content, AI cost) | Security, analytics |
| 8 | Go live: Cloudflare domain + HTTPS → AWS EC2, runs daily | DNS, deployment |
| 9 | Turn the pipeline into an agent that picks its own steps | Tool use, agent loops |
| 10 | Learning loop from stats; embeddings search once the library grows large | Embeddings, memory, evaluation |

## Content rules

- **Language:** Hinglish (everyday Hindi + English, Roman script).
- **Simple for everyone:** short sentences, everyday words, desi examples,
  cheap and practical tips. Written for people who aren't health experts.
- **Grounded:** every fact must come from the [knowledge library](knowledge/README.md)
  (ICMR-NIN Dietary Guidelines for Indians 2024 and WHO fact sheets), quoted
  word-for-word and checked by code. Your own ideas are fact-checked the same way.
- **Safe:** no treatment or medicine advice. Every video carries a
  "not medical advice" line. A human approves every post.
- **Varied formats** (Myth vs Fact, Swap This for That, One Habit a Day,
  Desi Plate Breakdown, 30-Day Challenge), so the channel doesn't look
  mass-produced.
- **Human voice first:** your own recording when possible; a natural AI voice
  only as a fallback.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env      # then paste your Claude API key into .env
```

Never commit `.env`.

## Phase 1: the Writer

```powershell
python -m app.writer "maida is poison, always eat atta roti"   # your idea
python -m app.writer                                           # Claude picks a topic
python -m app.search "namkeen aur papad roz khana"             # only see which notes the search picks
```

It prints the hook, poster text, script (Hinglish + Devanagari), YouTube
title and description, the library quotes it used, a grounding check, a
fact-check, and the cost of the call. Each draft is saved in
`output/drafts/`, and Claude reads past topics from there so it doesn't
repeat itself.

| File | What it does |
|---|---|
| [prompts/writer_system.md](prompts/writer_system.md) | The instructions Claude follows: audience, language, safety. Edit this to change how it writes |
| [knowledge/notes/](knowledge/notes/) | The trusted facts Claude may use (see [knowledge/README.md](knowledge/README.md)) |
| [app/schemas.py](app/schemas.py) | The exact fields Claude must return (structured output) |
| [app/knowledge.py](app/knowledge.py) | Loads the notes and checks Claude's quotes against them |
| [prompts/search_system.md](prompts/search_system.md) | Instructions for the library search |
| [app/search.py](app/search.py) | Step 1: Claude Haiku (fast, cheap) picks the notes this idea needs |
| [app/writer.py](app/writer.py) | Step 2: Claude Opus writes the Short from those notes; checks, prints and saves the draft |
| [app/costs.py](app/costs.py) | Works out what each Claude call cost |

## Phase 2: the Poster

```powershell
python -m app.poster                                  # poster for the newest draft
python -m app.poster output/drafts/some-draft.json    # poster for a specific draft
python -m app.poster --no-review                      # skip Claude's check (free)
```

It draws a 1080×1920 poster (the size of a Short) from the draft's title and
3 points, in the pillar's colour, with the source and a "medical advice nahi"
line. Text sizes shrink automatically until everything fits above the area
YouTube covers with its buttons and title. The poster is saved in
`output/posters/`.

Then Claude looks at the poster at half size, roughly what a viewer sees on a
phone. It writes out every word it can read and lists any problems, and code
checks that every word of the title and points was readable. One check costs
about ₹0.80.

| File | What it does |
|---|---|
| [app/poster.py](app/poster.py) | Draws the poster (Pillow), sends it to Claude to check, saves the result into the draft |
| [prompts/poster_review.md](prompts/poster_review.md) | What Claude checks when it looks at a poster |
| [assets/fonts/](assets/fonts/) | Poppins font (free, SIL Open Font License) |

## Phase 3: the Short video

```powershell
python -m app.video                                  # newest draft, free AI voice
python -m app.video --voice my-recording.m4a         # use your own recording instead
python -m app.video output/drafts/some-draft.json    # a specific draft
```

The video (1080×1920, 30 fps, MP4) has two parts:

1. **Intro:** the hook in big letters while the voice says it.
2. **Poster:** slowly zooming in, with captions of what's being said underneath.

**Voice:**
- By default it's the free Microsoft AI voice (edge-tts) reading the
  Devanagari script, so Hindi words sound right. Change it with
  `TTS_VOICE` in `.env`.
- With `--voice`, it uses your recording instead. Record the Hinglish
  script on your phone in any format (m4a, mp3, ogg, wav). Silence at the
  start and end is cut, background noise is reduced, and the volume is set
  to YouTube's loudness level.

**Captions:** the script is split into short phrases. FFmpeg listens for the
pauses in the voice, and each phrase is timed to the speaking parts in
proportion to its length.

**Music (optional):** put `.mp3` files in `assets/music/`, for example from the
YouTube Audio Library in YouTube Studio. One is picked at random and mixed in
quietly under the voice. The folder isn't in git.

Videos are saved in `output/videos/`. Building one takes about a minute.

| File | What it does |
|---|---|
| [app/video.py](app/video.py) | Makes the voice, times the captions, draws every frame and hands them to FFmpeg |
