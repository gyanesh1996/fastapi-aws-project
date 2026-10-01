"""The exact shapes Claude must reply in (structured output)."""
from typing import Literal

from pydantic import BaseModel, Field


class NotePick(BaseModel):
    """What the library search returns."""
    topic: str = Field(description="Today's topic in plain English")
    note_ids: list[str] = Field(description="ids of the library notes the writer will need, most relevant first")


class Source(BaseModel):
    note_id: str = Field(description="id of the library note this fact comes from")
    quote: str = Field(description="The exact words copied from that note that back the Short")


class FactCheck(BaseModel):
    verdict: Literal["supported", "softened", "not_supported", "no_source"] = Field(
        description=(
            "supported = the idea is correct as given; "
            "softened = partly right, wording was made more accurate; "
            "not_supported = the idea is wrong or unsafe, so a close safe topic was written instead; "
            "no_source = the library has nothing on this idea, so a close topic the library supports was written instead"
        )
    )
    notes: str = Field(description="For the channel owner, in simple English: what was checked, what changed and why")


class PosterReview(BaseModel):
    """What Claude reports after looking at a poster."""
    text_seen: str = Field(description="Every word you can read in the image, top to bottom, exactly as written")
    readable_on_phone: bool
    issues: list[str] = Field(
        description="Real problems only: cut-off or overlapping text, low contrast, odd characters or boxes, cramped layout"
    )
    verdict: Literal["good", "fix_needed"]


class ShortContent(BaseModel):
    topic: str = Field(description="Short topic name in English, used to avoid repeats")
    pillar: Literal["diet", "movement", "sleep", "stress", "prevention"]
    format: Literal["myth_vs_fact", "swap_this_for_that", "one_habit_a_day", "desi_plate_breakdown", "challenge"]
    hook: str = Field(description="First line spoken in the first 2 seconds, Roman Hinglish, makes people stop scrolling")
    poster_title: str = Field(description="Big poster heading, Roman Hinglish, at most 6 words")
    poster_points: list[str] = Field(description="Exactly 3 short poster points, Roman Hinglish, at most 8 words each")
    script_hinglish: str = Field(description="Voiceover for 20-30 seconds (55-75 words), Roman Hinglish, written for speaking")
    script_devanagari: str = Field(description="The same voiceover written in Devanagari, for a Hindi AI voice")
    youtube_title: str = Field(description="YouTube title, under 70 characters, Hinglish")
    youtube_description: str = Field(description="2-3 lines in Hinglish. No sources or disclaimer; those are added automatically")
    hashtags: list[str] = Field(description="3-5 hashtags without spaces, including #shorts")
    sources: list[Source]
    fact_check: FactCheck
