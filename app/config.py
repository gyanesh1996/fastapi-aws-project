"""Project settings and paths. Secrets come from .env, never from code."""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = "claude-opus-5-5"

PROMPTS_DIR = ROOT / "prompts"
DRAFTS_DIR = ROOT / "output" / "drafts"
