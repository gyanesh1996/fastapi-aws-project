"""Project settings and paths. Secrets come from .env, never from code."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = "claude-opus-5-5"         # writes the Short
SEARCH_MODEL = "claude-haiku-4-5"  # picks library notes: a simple job, so the fast, cheap model

BRAND_NAME = os.getenv("BRAND_NAME", "")  # shown at the top of posters; empty = no brand line
TTS_VOICE = os.getenv("TTS_VOICE", "hi-IN-SwaraNeural")  # free AI voice; hi-IN-MadhurNeural is the male one

PROMPTS_DIR = ROOT / "prompts"
KNOWLEDGE_DIR = ROOT / "knowledge"
FONTS_DIR = ROOT / "assets" / "fonts"
MUSIC_DIR = ROOT / "assets" / "music"
DRAFTS_DIR = ROOT / "output" / "drafts"
POSTERS_DIR = ROOT / "output" / "posters"
VIDEOS_DIR = ROOT / "output" / "videos"
