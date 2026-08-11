from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


@router.get("/", response_class=HTMLResponse)
def read_root():
    template_path = BASE_DIR / "templates" / "index.html"
    return template_path.read_text(encoding="utf-8")
