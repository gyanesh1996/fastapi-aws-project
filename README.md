# Health Shorts Agent

An AI agent that runs a YouTube Shorts channel about **lifestyle change for
Indian people**: desi diet, movement for desk jobs, sleep, stress, and
preventing lifestyle diseases like diabetes and BP.

Every day it:

```
Trusted health sources ──► AI picks today's topic + writes the script (Hinglish)
                                 │
                                 ▼
                 Poster image ──► Short video (poster + voiceover + captions)
                                 │
                                 ▼
          Preview sent on Telegram: [Approve] [Reject] [Redo with feedback]
                                 │ (approved)
                                 ▼
                     Uploaded to the YouTube channel
                                 │
                                 ▼
          Views and watch time go back to the AI so it learns what works
```

This project is also a hands-on way to learn AI, one concept per phase.

## Roadmap

| Phase | What we build | AI concept |
|---|---|---|
| 0 | Repo, API keys, YouTube channel | Setup |
| 1 | AI writes a daily topic as structured data (title, script, poster text, tags) | Prompting, structured output, tokens and cost |
| 2 | Poster generator; the AI checks its own poster | Vision |
| 3 | Shorts generator: poster + voiceover + captions → 9:16 video | Text-to-speech, multimodal pipelines |
| 4 | Telegram approval bot | Human-in-the-loop |
| 5 | YouTube upload | OAuth, YouTube Data API |
| 6 | Turn the pipeline into an agent that picks its own steps | Tool use, agent loops |
| 7 | Knowledge library + past performance; no repeated topics | Grounding / RAG, memory, evaluation |
| 8 | Runs daily on AWS | Scheduling, deployment |

## Content rules

- **Language:** Hinglish (everyday Hindi + English, Roman script).
- **Grounded:** every fact must come from a trusted source, such as the
  ICMR-NIN Dietary Guidelines for Indians, WHO, NFHS, or FSSAI Eat Right India.
  The source is stored with each video.
- **Safe:** no treatment or medicine advice. Every video carries a
  "not medical advice" line. A human approves every post.
- **Varied formats** (Myth vs Fact, Swap This for That, One Habit a Day,
  Desi Plate Breakdown, 30-Day Challenge), so the channel doesn't look
  mass-produced.

## Setup

Coming in Phase 1. Copy `.env.example` to `.env` and add your keys. Never
commit `.env`.
