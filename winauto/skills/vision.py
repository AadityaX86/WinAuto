"""Ask about what's on screen, or about an image, with a local vision model."""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import Any, Callable, Literal

from winauto.adapters.winos import NotOnWindows
from winauto.adapters.winos.screen import capture
from winauto.core.context import Context
from winauto.core.skill import QuickRule, Skill, ToolResult, fail, ok, tool

log = logging.getLogger(__name__)
MAX_SIDE = 1600
SYSTEM = ("You look at a screenshot or image from the user's Windows PC and answer their question about it. "
          "Be specific and brief. If there's an error message, explain what it means and how to fix it.")


def encode_image(image: Any) -> str:
    """PIL image -> base64 PNG, shrunk so the model gets a sensible size."""
    image = image.convert("RGB")
    w, h = image.size
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        image = image.resize((int(w * scale), int(h * scale)))
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class VisionSkill(Skill):
    name = "vision"
    icon = "eye"
    description = "Answer questions about the screen or an image (local vision model)."
    keywords = (r"\b(screen|on my screen|see|look at|this error|this window|screenshot|image|picture|photo|"
                r"read the text|what am i looking at)\b")
    prompt_hint = "Vision: for questions about what's on the user's screen, call ask_about_screen."

    def __init__(self, ctx: Context, grabber: Callable[[int | None], Any] | None = None):
        super().__init__(ctx)
        self._grab = grabber or capture

    def _ask(self, question: str, image_b64: str) -> ToolResult:
        assistant = self.ctx.assistant
        if assistant is None:
            return fail("The AI model isn't available.")
        model = getattr(self.ctx.config.llm, "vision_model", "") or None
        try:
            answer = assistant.complete(SYSTEM, question, images=[image_b64], model=model, stream=True)
        except Exception as exc:
            msg = str(exc)
            if "isn't downloaded" in msg or "not found" in msg:
                msg += " (A vision model is needed for this; set it in Settings → AI model.)"
            return fail(msg)
        return ok(answer.strip() or "I couldn't make anything out.")

    @tool(
        "Look at the user's screen (or the window they were using) and answer a question about it.",
        params={"question": "What to find out, e.g. 'what does this error mean?'", "what": "screen or window"},
    )
    def ask_about_screen(self, question: str = "What's on my screen?", what: Literal["screen", "window"] = "screen") -> ToolResult:
        hwnd = self.ctx.host.last_window if what == "window" else None
        hidden = self.ctx.host.hide()
        if hidden:
            time.sleep(0.4)  # let the popup fade out of the shot
        try:
            image = self._grab(hwnd)
        except (NotOnWindows, OSError, ImportError) as exc:
            return fail(f"Couldn't capture the screen: {exc}")
        finally:
            if hidden:
                self.ctx.host.show()
        return self._ask(question, encode_image(image))

    @tool("Answer a question about an image file.", params={"path": "Full path to the image", "question": "What to find out"})
    def ask_about_image(self, path: str, question: str = "Describe this image.") -> ToolResult:
        p = Path(path.strip().strip('"')).expanduser()
        if not p.exists():
            return fail(f"I can't find {p}.")
        try:
            from PIL import Image

            image = Image.open(p)
        except Exception as exc:
            return fail(f"Couldn't open the image: {exc}")
        return self._ask(question, encode_image(image))

    @tool("Read all the text on the screen (like OCR) and copy it.", params={"what": "screen or window"})
    def read_screen_text(self, what: Literal["screen", "window"] = "screen") -> ToolResult:
        result = self.ask_about_screen("Transcribe all the readable text exactly, in reading order. Output only the text.", what)
        if result.ok:
            result.data = {"text": result.message,
                           "actions": [{"label": "Copy", "icon": "copy", "tool": "set_clipboard", "args": {"text": result.message}}]}
        return result

    def quick_rules(self) -> list[QuickRule]:
        return [
            QuickRule(r"what(?:'s| is)\s+on\s+(?:my|the)\s+screen|what\s+am\s+i\s+looking\s+at|describe\s+(?:my|the)\s+screen",
                      lambda m: ("ask_about_screen", {"question": "What's on my screen? Give a short overview."})),
            QuickRule(r"(?:explain|what\s+does)\s+(?:this|the)\s+error(?:\s+mean)?(?:\s+on\s+(?:my\s+)?screen)?",
                      lambda m: ("ask_about_screen", {"question": "What does the error on screen mean, and how do I fix it?"})),
            QuickRule(r"(?:read|copy|grab|extract)\s+(?:the\s+|all\s+the\s+)?text\s+(?:on|from)\s+(?:my\s+|the\s+)?(?P<w>screen|window)",
                      lambda m: ("read_screen_text", {"what": m["w"]})),
        ]
