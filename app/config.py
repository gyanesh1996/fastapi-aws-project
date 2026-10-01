"""Project settings and paths. Secrets come from .env, never from code."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = "claude-opus-5-5"         # writes the Short
SEARCH_MODEL = "claude-haiku-4-5"  # picks library notes: a simple job, so the fast, cheap model

BRAND_NAME = os.getenv("BRAND_NAME", "")  # shown at the top of posters; empty = no brand line

PROMPTS_DIR = ROOT / "prompts"
KNOWLEDGE_DIR = ROOT / "knowledge"
FONTS_DIR = ROOT / "assets" / "fonts"
DRAFTS_DIR = ROOT / "output" / "drafts"
POSTERS_DIR = ROOT / "output" / "posters"
