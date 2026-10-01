"""Station 2, the Poster: draws a 1080x1920 poster from a draft, then Claude looks at it and checks it.

Run:  python -m app.poster                                  poster for the newest draft
      python -m app.poster output/drafts/some-draft.json    poster for a specific draft
      python -m app.poster --no-review                      skip Claude's check (free)
"""
import base64
import io
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import anthropic
from PIL import Image, ImageDraw, ImageFont

from app.config import BRAND_NAME, DRAFTS_DIR, FONTS_DIR, MODEL, POSTERS_DIR, PROMPTS_DIR
from app.costs import call_usage, describe
from app.knowledge import load_notes
from app.schemas import PosterReview

W, H = 1080, 1920
MARGIN = 80
# YouTube's title, channel name and buttons cover the bottom of a Short, so everything important stays above this.
CONTENT_TOP, CONTENT_BOTTOM = 330, 1500
CARD_PAD, CARD_GAP, CIRCLE = 40, 32, 84
TEXT_DARK = (31, 41, 55)

# (top, bottom) background colours for each pillar.
PILLAR_COLORS = {
    "diet": ((34, 139, 96), (14, 84, 60)),
    "movement": ((232, 110, 50), (176, 64, 22)),
    "sleep": ((72, 76, 176), (36, 38, 104)),
    "stress": ((30, 140, 156), (14, 86, 98)),
    "prevention": ((200, 56, 76), (130, 28, 44)),
}
FORMAT_LABELS = {
    "myth_vs_fact": "MYTH vs FACT",
    "swap_this_for_that": "SMART SWAP",
    "one_habit_a_day": "1 HABIT A DAY",
    "desi_plate_breakdown": "DESI PLATE",
    "challenge": "CHALLENGE",
}
FOOTER_NOTE = "General awareness ke liye  •  Medical advice nahi"


@lru_cache
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / f"Poppins-{weight}.ttf"), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=fnt) <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    return lines + [line] if line else lines


def plan_layout(draw, title: str, points: list[str], footer_height: int, scale: float) -> dict:
    """Work out line breaks and heights at a given text size."""
    title_font, point_font = font("Bold", int(116 * scale)), font("SemiBold", int(52 * scale))
    title_lh, point_lh = int(116 * scale * 1.18), int(52 * scale * 1.35)
    title_lines = wrap(draw, title, title_font, W - 2 * MARGIN)
    text_width = W - 2 * MARGIN - 2 * CARD_PAD - CIRCLE - 32
    cards = []
    for point in points:
        lines = wrap(draw, point, point_font, text_width)
        cards.append({"lines": lines, "height": max(CIRCLE, len(lines) * point_lh) + 2 * CARD_PAD})
    total =len(title_lines) * title_lh + 60 + sum(c["height"] for c in cards) + CARD_GAP * (len(cards) - 1) + 50 + footer_height
    return {
        "title_font": title_font, "point_font": point_font, "title_lh": title_lh, "point_lh": point_lh,
        "title_lines": title_lines, "cards": cards, "total": total,
    }


def fit_layout(draw, title: str, points: list[str], footer_height: int, content_bottom: int) -> dict:
    """Biggest text size at which everything fits in the safe area."""
    for step in range(0, 9):
        layout = plan_layout(draw, title, points, footer_height, 1.0 - step * 0.05)
        if layout["total"] <= content_bottom - CONTENT_TOP and len(layout["title_lines"]) <= 4:
            return layout
    return layout  # smallest size; the review will flag it if it's still too much


def gradient(top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        draw.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def render_poster(content: dict, source_line: str, content_bottom: int = CONTENT_BOTTOM) -> Image.Image:
    """content_bottom: lower edge for the poster's content (the video version keeps room for captions below it)."""
    top, bottom = PILLAR_COLORS.get(content["pillar"], PILLAR_COLORS["diet"])
    img = gradient(top, bottom)
    draw = ImageDraw.Draw(img, "RGBA")

    # Soft background shapes.
    draw.ellipse([W - 300, -340, W + 300, 260], fill=(255, 255, 255, 22))
    draw.ellipse([-260, H - 700, 360, H - 80], fill=(255, 255, 255, 14))

    if BRAND_NAME:
        draw.text((MARGIN, 130), BRAND_NAME.upper(), font=font("SemiBold", 34), fill=(255, 255, 255, 200))

    # Format pill, e.g. "MYTH vs FACT".
    label = FORMAT_LABELS.get(content["format"], "")
    label_font = font("SemiBold", 38)
    label_w = draw.textlength(label, font=label_font)
    draw.rounded_rectangle([MARGIN, 210, MARGIN + label_w + 56, 276], radius=33, fill=(255, 255, 255, 48))
    draw.text((MARGIN + 28, 243), label, font=label_font, fill="white", anchor="lm")

    source_lines = wrap(draw, source_line, font("Medium", 30), W - 2 * MARGIN) if source_line else []
    footer_height = len(source_lines) * 44 + 48
    layout = fit_layout(draw, content["poster_title"], content["poster_points"], footer_height, content_bottom)
    y = CONTENT_TOP
    for line in layout["title_lines"]:
        draw.text((MARGIN, y), line, font=layout["title_font"], fill="white")
        y += layout["title_lh"]
    y += 60

    for number, card in enumerate(layout["cards"], 1):
        draw.rounded_rectangle([MARGIN, y, W - MARGIN, y + card["height"]], radius=36, fill="white")
        cx, cy = MARGIN + CARD_PAD + CIRCLE // 2, y + card["height"] // 2
        draw.ellipse([cx - CIRCLE // 2, cy - CIRCLE // 2, cx + CIRCLE // 2, cy + CIRCLE // 2], fill=bottom)
        draw.text((cx, cy), str(number), font=font("Bold", 44), fill="white", anchor="mm")
        text_x = MARGIN + CARD_PAD + CIRCLE + 32
        text_y = y + (card["height"] - len(card["lines"]) * layout["point_lh"]) // 2
        for line in card["lines"]:
            draw.text((text_x, text_y), line, font=layout["point_font"], fill=TEXT_DARK)
            text_y += layout["point_lh"]
        y += card["height"] + CARD_GAP

    y += 50 - CARD_GAP
    for line in source_lines:
        draw.text((MARGIN, y), line, font=font("Medium", 30), fill=(255, 255, 255, 225))
        y += 44
    draw.text((MARGIN, y + 4), FOOTER_NOTE, font=font("Medium", 28), fill=(255, 255, 255, 190))
    return img


def review_poster(img: Image.Image, client: anthropic.Anthropic) -> tuple[PosterReview | None, dict]:
    """Claude looks at the poster at half size, roughly what a viewer sees on a phone."""
    small = img.resize((W // 2, H // 2), Image.LANCZOS)
    buffer = io.BytesIO()
    small.save(buffer, format="PNG")
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.standard_b64encode(buffer.getvalue()).decode()}},
                {"type": "text", "text": (PROMPTS_DIR / "poster_review.md").read_text(encoding="utf-8")},
            ],
        }],
        output_format=PosterReview,
    )
    return response.parsed_output, call_usage("poster review", response)


def missing_words(content: dict, text_seen: str) -> list[str]:
    """Don't trust, verify: compare the text we meant to print with the text Claude could read."""
    def words(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    seen = set(words(text_seen))
    expected = words(" ".join([content["poster_title"], *content["poster_points"]]))
    return [w for w in expected if w not in seen]


def source_line_for(content: dict) -> str:
    notes = load_notes()
    names = [notes[s["note_id"]].source.split(",")[0] for s in content.get("sources", []) if s.get("note_id") in notes]
    return "Source: " + "; ".join(dict.fromkeys(names)) if names else ""


def latest_draft() -> Path:
    drafts = sorted(DRAFTS_DIR.glob("*.json"))
    if not drafts:
        sys.exit("No drafts yet. Make one first: python -m app.writer \"your idea\"")
    return drafts[-1]


def make_poster(draft_path: Path, review: bool = True) -> dict:
    """Draw the poster for a draft, optionally have Claude check it, and record the result in the draft."""
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    content = draft["content"]

    img = render_poster(content, source_line_for(content))
    POSTERS_DIR.mkdir(parents=True, exist_ok=True)
    poster_path = POSTERS_DIR / f"{draft_path.stem}.png"
    img.save(poster_path)
    info = {"path": str(poster_path)}

    if review:
        result, usage = review_poster(img, anthropic.Anthropic())
        info["usage"] = usage
        if result is not None:
            info.update(review=result.model_dump(), missing_words=missing_words(content, result.text_seen))

    draft["poster"] = info
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    review = "--no-review" not in sys.argv
    if review:
        print("Drawing the poster, then Claude checks it ...")
    info = make_poster(Path(args[0]) if args else latest_draft(), review=review)
    print(f"Poster saved: {info['path']}")
    if not review:
        return
    if "review" not in info:
        print("The review didn't return a result.")
        return
    r = info["review"]
    print(f"\nREVIEW: {r['verdict'].upper()}  (readable on a phone: {'yes' if r['readable_on_phone'] else 'NO'})")
    for issue in r["issues"]:
        print(f"  - {issue}")
    if info["missing_words"]:
        print(f"TEXT CHECK: Claude couldn't read these words: {', '.join(info['missing_words'])}")
    else:
        print("TEXT CHECK: OK - Claude read every word of the title and points")
    print(f"\nCOST: {describe(info['usage'])}")


if __name__ == "__main__":
    main()
