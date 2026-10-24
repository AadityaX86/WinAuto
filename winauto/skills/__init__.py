"""Built-in skills. Add a new skill by writing a module here and listing it below."""

from __future__ import annotations

import importlib
import logging

from winauto.core.registry import Registry
from winauto.core.skill import Skill

log = logging.getLogger(__name__)

# (module, class) in priority order: earlier skills get first try at quick commands.
BUILTIN: list[tuple[str, str]] = [
    ("apps", "AppsSkill"),
    ("notes", "NotesSkill"),
    ("web", "WebSkill"),
    ("utils", "UtilsSkill"),
    ("system", "SystemSkill"),
    ("contacts", "ContactsSkill"),
    ("reminders", "RemindersSkill"),
    ("gmail", "EmailSkill"),
    ("whatsapp", "WhatsAppSkill"),
    ("discord", "DiscordSkill"),
    ("files", "FilesSkill"),
    ("clipboard", "ClipboardSkill"),
    ("media", "MediaSkill"),
    ("window_layout", "WindowLayoutSkill"),
    ("routines", "RoutinesSkill"),
    ("shortcuts", "ShortcutsSkill"),
    ("tools", "ToolsSkill"),
    ("memory", "MemorySkill"),
    ("textactions", "TextActionsSkill"),
    ("vision", "VisionSkill"),
    ("info", "InfoSkill"),
    ("calendar", "CalendarSkill"),
    ("briefing", "BriefingSkill"),
    ("focus", "FocusSkill"),
    ("voice", "VoiceSkill"),
]


def build_registry(ctx) -> Registry:
    registry = Registry()
    for module_name, class_name in BUILTIN:
        try:
            module = importlib.import_module(f"winauto.skills.{module_name}")
            skill_cls: type[Skill] = getattr(module, class_name)
            registry.add(skill_cls(ctx))
        except Exception:
            # One broken skill shouldn't stop the rest of the app.
            log.exception("Couldn't load skill %s.%s", module_name, class_name)
    return registry
