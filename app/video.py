"""Station 3, the Video: poster + voice + captions (+ music) -> a 9:16 Short (MP4).

Run:  python -m app.video                               newest draft, free AI voice
      python -m app.video --voice my-recording.m4a      use your own recording instead
      python -m app.video output/drafts/some-draft.json a specific draft

The video:
  1. Intro: the hook in big letters while the voice says it.
  2. The poster, slowly zooming in, with captions of what's being said underneath.
"""
import asyncio
import json
import math
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw

from app.config import BRAND_NAME, MUSIC_DIR, TTS_VOICE, VIDEOS_DIR
from app.poster import H, MARGIN, PILLAR_COLORS, W, font, gradient, latest_draft, render_poster, source_line_for, wrap

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()  # a copy of FFmpeg that comes with the pip package
FPS = 30
TAIL_SECONDS = 0.8          # hold the last frame a little after the voice ends
ZOOM = 0.035                # the poster grows by 3.5% over the video
VIDEO_CONTENT_BOTTOM = 1290  # the video's poster ends here, leaving a band for captions
CAPTION_CENTER_Y = 1395
CAPTION_MAX_WIDTH = 820
TTS_RATE = "+8%"            # Shorts are fast; a little quicker than normal speech
MUSIC_VOLUME = 0.12


# ---------- Audio ----------

def ffmpeg(*args: str) -> str:
    """Run FFmpeg and return its log (FFmpeg writes its information to stderr)."""
    result = subprocess.run([FFMPEG, "-hide_banner", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-2000:]}")
    return result.stderr


def make_ai_voice(text: str, path: Path) -> None:
    asyncio.run(edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE).save(str(path)))


def prepare_voice(src: Path, dst: Path, own_recording: bool) -> None:
    """Trim silence at both ends and set YouTube's loudness. Own recordings also get light noise removal."""
    trim = "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB"
    filters = [trim, "areverse", trim, "areverse", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    if own_recording:
        filters = ["highpass=f=80", "afftdn=nf=-25", *filters]
    ffmpeg("-y", "-i", str(src), "-af", ",".join(filters), "-ar", "48000", "-ac", "1", str(dst))


def audio_duration(path: Path) -> float:
    log = ffmpeg("-i", str(path), "-f", "null", "-")
    h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", log)[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def speech_intervals(path: Path, duration: float) -> list[tuple[float, float]]:
    """When the voice is actually speaking, found by listening for pauses."""
    log = ffmpeg("-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    intervals, cursor = [], 0.0
    for start, end in zip(starts, ends + [duration] * (len(starts) - len(ends))):
        if start > cursor:
            intervals.append((cursor, start))
        cursor = end
    if cursor < duration:
        intervals.append((cursor, duration))
    return intervals or [(0.0, duration)]


# ---------- Captions ----------

def caption_chunks(script: str, max_words: int = 5) -> list[str]:
    """Split the script into short bits that fit on screen: at punctuation, then at most 5 words."""
    chunks = []
    for phrase in re.findall(r"[^.,!?;:]+[.,!?;:]*", script):
        words = phrase.split()
        for i in range(0, len(words), max_words):
            chunks.append(" ".join(words[i:i + max_words]).rstrip(",;:"))
    return [c for c in chunks if c]


def time_captions(chunks: list[str], intervals: list[tuple[float, float]]) -> list[tuple[float, float, str]]:
    """Spread the captions over the speaking time, in proportion to their length.

    Pauses are skipped, so captions wait while the speaker pauses."""
    weights = [len(c) + 3 for c in chunks]
    speech_total = sum(end - start for start, end in intervals)

    def to_real_time(speech_time: float) -> float:
        for start, end in intervals:
            if speech_time <= end - start:
                return start + speech_time
            speech_time -= end - start
        return intervals[-1][1]

    timed, done = [], 0
    for chunk, weight in zip(chunks, weights):
        start = to_real_time(speech_total * done / sum(weights))
        done += weight
        end = to_real_time(speech_total * done / sum(weights))
        timed.append((start, end, chunk))
    # Close small gaps so captions don't flicker off during short pauses.
    return [(s, max(e, timed[i + 1][0]) if i + 1 < len(timed) and timed[i + 1][0] - e < 0.6 else e, t)
            for i, (s, e, t) in enumerate(timed)]


def hook_end_time(content: dict, captions: list[tuple[float, float, str]]) -> float:
    """When the voice finishes saying the hook (the script starts with it). Old drafts: about 2 seconds."""
    def letters(text: str) -> str:
        return re.sub(r"[^a-z]", "", text.lower())

    hook, script = letters(content["hook"]), letters(content["script_hinglish"])
    if not script.startswith(hook[: max(10, len(hook) // 2)]):
        return 2.0
    said = ""
    for _, end, text in captions:
        said += letters(text)
        if len(said) >= len(hook):
            return end
    return captions[-1][1]


# ---------- Pictures ----------

def render_caption(text: str) -> Image.Image:
    fnt = font("Bold", 58)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = wrap(probe, text, fnt, CAPTION_MAX_WIDTH)
    if len(lines) == 2:  # balance the two lines so one word isn't left alone
        words = text.split()
        best = min(range(1, len(words)), key=lambda i: max(probe.textlength(" ".join(words[:i]), font=fnt),
                                                          probe.textlength(" ".join(words[i:]), font=fnt)))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    line_h = 74
    width = int(max(probe.textlength(line, font=fnt) for line in lines)) + 56
    height = len(lines) * line_h + 28
    img = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, width, height], radius=26, fill=(0, 0, 0, 165))
    for i, line in enumerate(lines):
        draw.text((width // 2, 14 + i * line_h + line_h // 2), line, font=fnt, fill="white", anchor="mm")
    return img


def render_intro(content: dict) -> Image.Image:
    top, bottom = PILLAR_COLORS.get(content["pillar"], PILLAR_COLORS["diet"])
    img = gradient(top, bottom)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse([-260, -260, 420, 420], fill=(255, 255, 255, 20))
    if BRAND_NAME:
        draw.text((W // 2, 260), BRAND_NAME.upper(), font=font("SemiBold", 38), fill=(255, 255, 255, 210), anchor="mm")
    for size in range(104, 56, -6):
        fnt = font("Bold", size)
        lines = wrap(draw, content["hook"], fnt, W - 2 * MARGIN)
        if len(lines) <= 5:
            break
    line_h = int(size * 1.2)
    y = 820 - len(lines) * line_h // 2
    for line in lines:
        draw.text((W // 2, y + line_h // 2), line, font=fnt, fill="white", anchor="mm")
        y += line_h
    draw.rounded_rectangle([W // 2 - 60, y + 50, W // 2 + 60, y + 62], radius=6, fill=(255, 255, 255, 200))
    return img


def zoomed(img: Image.Image, z: float) -> Image.Image:
    big = img.resize((int(W * z), int(H * z)), Image.BILINEAR)
    left, top = (big.width - W) // 2, (big.height - H) // 2
    return big.crop((left, top, left + W, top + H))


# ---------- Putting it together ----------

def build_video(content: dict, voice_wav: Path, out_path: Path) -> dict:
    duration = audio_duration(voice_wav)
    total = duration + TAIL_SECONDS
    captions = time_captions(caption_chunks(content["script_hinglish"]), speech_intervals(voice_wav, duration))
    intro_end = hook_end_time(content, captions)

    intro = render_intro(content)
    poster = render_poster(content, source_line_for(content), content_bottom=VIDEO_CONTENT_BOTTOM)
    caption_images = [(start, end, render_caption(text)) for start, end, text in captions if end > intro_end]

    music = sorted(MUSIC_DIR.glob("*.mp3")) if MUSIC_DIR.exists() else []
    track = random.choice(music) if music else None
    inputs = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(voice_wav)]
    if track:
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        audio = (f"[1:a]apad=pad_dur={TAIL_SECONDS}[v];"
                 f"[2:a]volume={MUSIC_VOLUME},afade=t=in:d=1,afade=t=out:st={total - 1.5:.2f}:d=1.5[m];"
                 f"[v][m]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        audio = f"[1:a]apad=pad_dur={TAIL_SECONDS}[a]"
    command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", audio,
               "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)]

    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = math.ceil(total * FPS)
    poster_frames = max(1, frames - int(intro_end * FPS))
    for i in range(frames):
        t = i / FPS
        if t < intro_end:
            frame = zoomed(intro, 1 + 0.02 * t / max(intro_end, 0.1))
        else:
            frame = zoomed(poster, 1 + ZOOM * (i - int(intro_end * FPS)) / poster_frames)
            for start, end, cap in caption_images:
                if start <= t < end:
                    frame.paste(cap, ((W - cap.width) // 2, CAPTION_CENTER_Y - cap.height // 2), cap)
                    break
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError(f"FFmpeg failed:\n{process.stderr.read().decode(errors='replace')[-2000:]}")
    return {"path": str(out_path), "seconds": round(total, 1), "music": track.name if track else None,
            "captions": len(captions)}


def make_video(draft_path: Path, own_voice: Path | None = None) -> dict:
    """Make the video for a draft (AI voice, or own_voice if given) and record it in the draft."""
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    content = draft["content"]

    with tempfile.TemporaryDirectory() as tmp:
        voice_wav = Path(tmp) / "voice.wav"
        if own_voice:
            prepare_voice(own_voice, voice_wav, own_recording=True)
            voice_label = f"own:{own_voice.name}"
        else:
            raw = Path(tmp) / "voice.mp3"
            make_ai_voice(content["script_devanagari"], raw)
            prepare_voice(raw, voice_wav, own_recording=False)
            voice_label = f"ai:{TTS_VOICE}"
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        info = build_video(content, voice_wav, VIDEOS_DIR / f"{draft_path.stem}.mp4")

    info["voice"] = voice_label
    draft["video"] = info
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    own_voice = Path(args[args.index("--voice") + 1]) if "--voice" in args else None
    drafts = [a for a in args if a.endswith(".json")]
    print(f"Using your recording: {own_voice}" if own_voice else f"Using the AI voice ({TTS_VOICE})")
    print("Building the video (about a minute) ...")
    info = make_video(Path(drafts[0]) if drafts else latest_draft(), own_voice)
    print(f"\nVideo saved: {info['path']}")
    print(f"Length: {info['seconds']}s | voice: {info['voice']} | music: {info['music'] or 'none'} | captions: {info['captions']}")


if __name__ == "__main__":
    main()
