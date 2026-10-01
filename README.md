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
| 2 | Poster generator; the AI checks its own poster | Vision |
| 3 | Short video: your voice or AI voice + captions + music | Text-to-speech, speech-to-text |
| 4 | Telegram approval; send ideas and voice recordings from your phone | Human-in-the-loop |
| 5 | YouTube upload | OAuth, YouTube Data API |
| 6 | Public home page | Web backend |
| 7 | Admin login + dashboard (website visitors, YouTube stats, content, AI cost) | Security, analytics |
| 8 | Go live: Cloudflare domain + HTTPS → AWS EC2, runs daily | DNS, deployment |
| 9 | Turn the pipeline into an agent that picks its own steps | Tool use, agent loops |
| 10 | Learning loop from stats; no repeated topics | Grounding / RAG, memory, evaluation |

## Content rules

- **Language:** Hinglish (everyday Hindi + English, Roman script).
- **Simple for everyone:** short sentences, everyday words, desi examples,
  cheap and practical tips. Written for people who aren't health experts.
- **Grounded:** every fact must come from a trusted source, such as the
  ICMR-NIN Dietary Guidelines for Indians, WHO, NFHS, or FSSAI Eat Right India.
  The source is stored with each post. Your own ideas are fact-checked the same way.
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
```

It prints the hook, poster text, script (Hinglish + Devanagari), YouTube
title, sources, a fact-check, and the cost of the call. Each draft is saved
in `output/drafts/`, and Claude reads past topics from there so it doesn't
repeat itself.

| File | What it does |
|---|---|
| [prompts/writer_system.md](prompts/writer_system.md) | The instructions Claude follows: audience, language, safety. Edit this to change how it writes |
| [app/schemas.py](app/schemas.py) | The exact fields Claude must return (structured output) |
| [app/writer.py](app/writer.py) | Sends the request, checks the reply, prints and saves the draft |
