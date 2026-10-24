"""Music and video: play/pause/skip for whatever's playing, what's playing, play a song."""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Callable, Literal

from winauto.adapters.http import FetchError, fetch
from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.media import WindowsMedia
from winauto.core.context import Context
from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool

log = logging.getLogger(__name__)

def first_youtube_video(html: str) -> str | None:
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html) or re.search(r'"videoId":"([\w-]{11})"', html)
    return m.group(1) if m else None


def _app_name(app_id: str) -> str:
    low = app_id.lower()
    for key, name in (("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"), ("firefox", "Firefox"),
                      ("zune", "Media Player"), ("vlc", "VLC"), ("brave", "Brave"), ("music", "Media Player")):
        if key in low:
            return name
    return app_id.split("!")[0].split(".")[-1] if app_id else "something"


class MediaSkill(Skill):
    name = "media"
    icon = "music"
    description = "Media controls and playing music."
    keywords = r"\b(play|pause|resume|skip|next|previous|songs?|track|music|playing|spotify|youtube|video|listen|playlist|album)\b"

    def __init__(self, ctx: Context, backend: Any = None, fetcher: Callable[..., tuple[str, str]] | None = None):
        super().__init__(ctx)
        self.backend = backend or WindowsMedia()
        self._fetch = fetcher or fetch

    def _control(self, action: str, message: str) -> ToolResult:
        try:
            self.backend.control(action)
        except NotOnWindows as exc:
            return fail(str(exc))
        return ok(message)

    @tool("Pause or resume whatever is playing (music, videos).", title="Play / pause")
    def play_pause(self) -> ToolResult:
        return self._control("play_pause", "⏯ Done.")

    @tool("Skip to the next track.", title="Next track")
    def next_track(self) -> ToolResult:
        return self._control("next", "⏭ Next track.")

    @tool("Go back to the previous track.", title="Previous track")
    def previous_track(self) -> ToolResult:
        return self._control("previous", "⏮ Previous track.")

    @tool("What song or video is playing right now.")
    def now_playing(self) -> ToolResult:
        try:
            info = self.backend.now_playing()
        except NotOnWindows as exc:
            return fail(str(exc))
        if not info or not info.get("title"):
            return ok("Nothing seems to be playing.")
        by = f" by {info['artist']}" if info.get("artist") else ""
        state = "" if info.get("status") == "Playing" else f" ({info.get('status', '').lower()})"
        return ok(f"🎵 {info['title']}{by}, in {_app_name(info.get('app', ''))}{state}.", data=info)

    @tool(
        "Play a song, artist, playlist or video. YouTube plays the top result straight away; Spotify opens its search.",
        params={"query": "What to play", "service": "youtube or spotify (default: the user's setting)"},
        hides_popup=True,
    )
    def play_music(self, query: str, service: Literal["default", "youtube", "spotify"] = "default") -> ToolResult:
        if service == "default":
            service = getattr(self.ctx.config, "music_service", "youtube") or "youtube"
        if service == "spotify":
            try:
                self.backend.open("spotify:search:" + urllib.parse.quote(query))
                return ok(f"Opened Spotify search for “{query}”. Press play on the top result.")
            except OSError:
                service = "youtube"
        q = urllib.parse.quote_plus(query)
        try:
            html, _ = self._fetch(f"https://www.youtube.com/results?search_query={q}", timeout=10)
            video = first_youtube_video(html)
        except FetchError:
            video = None
        if video:
            self.backend.open(f"https://www.youtube.com/watch?v={video}")
            return ok(f"Playing “{query}” on YouTube.")
        self.backend.open(f"https://www.youtube.com/results?search_query={q}")
        return ok(f"Opened YouTube results for “{query}”.")

    def quick_rules(self) -> list[QuickRule]:
        thing = r"(?:\s+(?:the\s+)?(?:music|song|video|track|playback|it|spotify|youtube))?"
        return [
            QuickRule(r"(?:pause|resume|unpause|stop)" + thing + r"|play" + thing + r"|continue playing",
                      lambda m: ("play_pause", {}), priority=40),
            QuickRule(r"(?:next|skip)(?:\s+(?:the\s+)?(?:song|track|video|one))?|skip\s+(?:this|it)",
                      lambda m: ("next_track", {}), priority=40),
            QuickRule(r"(?:previous|last|go back a)(?:\s+(?:song|track|video|one))?|play\s+(?:the\s+)?previous(?:\s+(?:song|track))?",
                      lambda m: ("previous_track", {}), priority=40),
            QuickRule(r"what(?:'s| is)\s+(?:this\s+song|playing|the song)(?:\s+(?:called|now|right now))?|what\s+song\s+is\s+(?:this|playing)|now\s+playing",
                      lambda m: ("now_playing", {}), priority=40),
            QuickRule(r"play\s+(?P<q>.+?)\s+on\s+(?P<s>youtube|yt|spotify)",
                      lambda m: ("play_music", {"query": m["q"], "service": "spotify" if m["s"].lower() == "spotify" else "youtube"}),
                      priority=40),
            QuickRule(r"play\s+(?:some\s+)?(?P<q>.+)",
                      lambda m: ("play_music", {"query": m["q"]}) if m["q"].lower() not in ("music", "it", "something") else None,
                      priority=60),
        ]
