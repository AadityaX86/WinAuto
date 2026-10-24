"""Writing tools (Ctrl+Alt+T): the actions to offer and the selected text they work on."""

from __future__ import annotations

from winauto.core.context import Context


class WritingTools:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    def actions(self) -> list[tuple[str, str, str]]:
        """(key, label, icon) for each one-click action; empty if the skill is turned off."""
        skill = self.ctx.skill("textactions")
        return skill.menu() if skill else []

    def label(self, key: str) -> str:
        return next((label for k, label, _ in self.actions() if k == key), key)

    def begin(self, selection: str) -> None:
        """Remember the text the user selected, so actions work on it."""
        self.ctx.host.selection = selection

    def end(self) -> None:
        self.ctx.host.selection = ""
