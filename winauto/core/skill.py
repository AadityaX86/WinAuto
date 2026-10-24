"""Skills and tools.

A *skill* is a group of related abilities (apps, notes, web...). Each ability is
a *tool*: a method marked with @tool. The tool's signature becomes the JSON
schema the AI model sees, so adding an ability is just adding a method.
"""

from __future__ import annotations

import enum
import inspect
import json
import logging
import types
import typing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from winauto.core.context import Context

log = logging.getLogger(__name__)


class Risk(enum.Enum):
    SAFE = "safe"  # runs right away
    CONFIRM = "confirm"  # user must approve (sending, deleting, shutting down...)


@dataclass
class ToolResult:
    ok: bool
    message: str  # human-readable; shown to the user
    data: Any = None  # extra detail for the model
    cancelled: bool = False
    # For quick commands: True means "I couldn't find what you meant", so the
    # AI model gets a go at the request instead.
    fallback: bool = False

    def for_model(self, limit: int = 6000) -> str:
        payload: dict[str, Any] = {"ok": self.ok, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        if self.cancelled:
            payload["cancelled"] = True
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > limit:
            text = text[:limit] + "...(truncated)"
        return text


def ok(message: str, data: Any = None) -> ToolResult:
    return ToolResult(True, message, data)


def fail(message: str, data: Any = None, fallback: bool = False) -> ToolResult:
    return ToolResult(False, message, data, fallback=fallback)


class ArgumentError(ValueError):
    pass


@dataclass
class Param:
    name: str
    kind: str  # JSON schema type
    description: str = ""
    required: bool = True
    default: Any = None
    choices: list[str] | None = None
    item_kind: str | None = None

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.kind}
        if self.description:
            out["description"] = self.description
        if self.choices:
            out["enum"] = list(self.choices)
        if self.kind == "array":
            out["items"] = {"type": self.item_kind or "string"}
        return out

    def coerce(self, value: Any) -> Any:
        if value is None:
            return None
        try:
            if self.kind == "string":
                value = value if isinstance(value, str) else (
                    json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                )
                if self.choices:
                    lowered = value.strip().lower()
                    for c in self.choices:
                        if c.lower() == lowered:
                            return c
                    raise ArgumentError(f"'{self.name}' must be one of {self.choices}")
                return value
            if self.kind == "integer":
                if isinstance(value, bool):
                    return int(value)
                if isinstance(value, str):
                    value = value.strip().rstrip("%")
                return int(float(value))
            if self.kind == "number":
                if isinstance(value, str):
                    value = value.strip().rstrip("%")
                return float(value)
            if self.kind == "boolean":
                if isinstance(value, str):
                    return value.strip().lower() in ("true", "yes", "1", "on", "y")
                return bool(value)
            if self.kind == "array":
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped.startswith("["):
                        try:
                            value = json.loads(stripped)
                        except ValueError:
                            value = [stripped]
                    else:
                        value = [v.strip() for v in stripped.split(",") if v.strip()]
                if not isinstance(value, list):
                    value = [value]
                return [str(v) for v in value]
        except ArgumentError:
            raise
        except (TypeError, ValueError) as exc:
            raise ArgumentError(f"'{self.name}' should be a {self.kind}, got {value!r}") from exc
        return value


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., ToolResult]
    params: list[Param]
    risk: Risk = Risk.SAFE
    # If True the result message is a complete answer, so the agent can stop
    # without another (slow) model call.
    final: bool = True
    editable: tuple[str, ...] = ()
    confirm_label: str = "Approve"
    preview: Callable[[dict[str, Any]], str] | None = None
    # For risky tools: a problem to report before the approval card (e.g. "Gmail isn't set up").
    precheck: Callable[[dict[str, Any]], ToolResult | None] | None = None
    skill: str = ""
    # Hide the popup after this runs successfully (it opened something on screen).
    hides_popup: bool = False
    # How the launcher names a call: "Open {name}", or a function of the arguments.
    title: str | Callable[[dict[str, Any]], str] = ""

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {p.name: p.schema() for p in self.params},
                    "required": [p.name for p in self.params if p.required],
                },
            },
        }

    def coerce_args(self, args: dict[str, Any] | None) -> dict[str, Any]:
        args = dict(args or {})
        out: dict[str, Any] = {}
        known = {p.name: p for p in self.params}
        for p in self.params:
            if p.name in args and args[p.name] not in (None, ""):
                out[p.name] = p.coerce(args[p.name])
            elif p.required:
                raise ArgumentError(f"missing required argument '{p.name}'")
        unknown = set(args) - set(known)
        if unknown:
            log.debug("Tool %s ignoring unknown args %s", self.name, unknown)
        return out

    def describe_call(self, args: dict[str, Any]) -> str:
        if self.preview:
            try:
                return self.preview(args)
            except Exception:  # preview must never break confirmation
                log.exception("preview failed for %s", self.name)
        shown = ", ".join(f"{k}: {v}" for k, v in args.items())
        return f"{self.name}({shown})"

    def run(self, args: dict[str, Any]) -> ToolResult:
        result = self.func(**args)
        if not isinstance(result, ToolResult):
            result = ok(str(result) if result is not None else "Done.")
        return result


_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _param_from_annotation(name: str, annotation: Any, default: Any, description: str) -> Param:
    required = default is inspect.Parameter.empty
    kind = "string"
    choices = None
    item_kind = None
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    # Optional[X] / X | None
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            annotation = non_none[0]
            origin = typing.get_origin(annotation)
            args = typing.get_args(annotation)
    if origin is typing.Literal:
        choices = [str(a) for a in args]
    elif origin in (list, tuple):
        kind = "array"
        item_kind = _TYPE_MAP.get(args[0], "string") if args else "string"
    elif annotation in _TYPE_MAP:
        kind = _TYPE_MAP[annotation]
    return Param(
        name=name,
        kind=kind,
        description=description,
        required=required,
        default=None if required else default,
        choices=choices,
        item_kind=item_kind,
    )


def tool(
    description: str,
    *,
    params: dict[str, str] | None = None,
    risk: Risk = Risk.SAFE,
    final: bool = True,
    editable: tuple[str, ...] = (),
    confirm_label: str = "Approve",
    name: str | None = None,
    hides_popup: bool = False,
    title: str | Callable[[dict[str, Any]], str] = "",
) -> Callable:
    """Mark a Skill method as a tool. `params` maps argument name -> description.

    `title` is what the launcher shows for an instant command, e.g. "Open {name}"
    (unset or default arguments are left out), or a function of the arguments.
    """

    def deco(fn: Callable) -> Callable:
        fn._tool_meta = {  # type: ignore[attr-defined]
            "description": description,
            "params": params or {},
            "risk": risk,
            "final": final,
            "editable": editable,
            "confirm_label": confirm_label,
            "name": name or fn.__name__,
            "hides_popup": hides_popup,
            "title": title,
        }
        return fn

    return deco


@dataclass
class Suggestion:
    """A live result in the launcher while you type (an app, a setting, a calculation...).

    Choosing it runs `tool` with `args` through the normal path (approval cards
    included). `score` (0-100) orders results across skills.
    """

    title: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    subtitle: str = ""
    kind: str = ""  # short label shown on the right: "App", "Setting", "Copy"...
    icon: str = ""  # icon name (see ui/icons.py) or "file:<path>" for the file's own icon
    score: float = 50.0


@dataclass
class Widget:
    """A small card on the home screen ("3 due today", "Dentist · 3 PM", "23° Sunny")."""

    icon: str  # icon name (see ui/icons.py)
    text: str
    order: int = 50  # lower shows first


@dataclass
class QuickRule:
    """A fast, offline shortcut: if `pattern` matches the whole command,
    `handler(match)` returns (tool_name, args) to run without asking the AI.
    Return None from the handler to let the AI deal with it instead."""

    pattern: str
    handler: Callable[[Any], tuple[str, dict[str, Any]] | None]
    # Lower runs first, across all skills.
    priority: int = 50


class Skill:
    """Base class for a group of tools. Subclasses set `name` and add @tool methods."""

    name = "skill"
    # Icon name from winauto/ui/icons.py, shown in results and Settings.
    icon = "puzzle"
    description = ""
    # Extra guidance added to the system prompt when this skill is loaded.
    prompt_hint = ""
    # Regex of words that mean a request probably needs this skill. Only matching
    # skills' tools are sent to the model, which keeps local models fast.
    keywords = ""
    # Always offer this skill's tools (general-purpose ones like web search).
    always = False

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def quick_rules(self) -> list[QuickRule]:
        return []

    def suggest(self, query: str) -> list[Suggestion]:
        """Live launcher results for what's typed so far. Must be fast (no network)."""
        return []

    def prompt_context(self) -> str:
        """Extra text for the system prompt on every request (keep it short)."""
        return ""

    def widgets(self) -> list[Widget]:
        """Cards for the home screen. Runs off the UI thread, so a short network call is fine (cache it)."""
        return []

    def start(self) -> None:
        """Called once when the app starts (warm caches, start timers...)."""

    def stop(self) -> None:
        """Called when the app quits."""

    def preview(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Override to give a friendly confirmation text for risky tools."""
        return None

    def precheck(self, tool_name: str, args: dict[str, Any]) -> ToolResult | None:
        """Override to stop a risky tool before its approval card, e.g. when an account isn't set up.

        Return a failed ToolResult to stop (the user never sees a card they can't use), or None to go on.
        """
        return None

    def tools(self) -> list[Tool]:
        found: list[Tool] = []
        for attr in dir(type(self)):
            fn = getattr(type(self), attr, None)
            meta = getattr(fn, "_tool_meta", None)
            if not meta:
                continue
            bound = getattr(self, attr)
            hints = typing.get_type_hints(fn)
            sig = inspect.signature(fn)
            plist = []
            for pname, p in sig.parameters.items():
                if pname == "self":
                    continue
                plist.append(
                    _param_from_annotation(
                        pname, hints.get(pname, str), p.default, meta["params"].get(pname, "")
                    )
                )
            tool_name = meta["name"]

            def make_preview(tn: str) -> Callable[[dict[str, Any]], str] | None:
                if type(self).preview is Skill.preview:
                    return None

                def _p(args: dict[str, Any]) -> str:
                    text = self.preview(tn, args)
                    if text is None:
                        raise ValueError("no preview")
                    return text

                return _p

            def make_precheck(tn: str) -> Callable[[dict[str, Any]], ToolResult | None] | None:
                if type(self).precheck is Skill.precheck:
                    return None
                return lambda args: self.precheck(tn, args)

            found.append(
                Tool(
                    name=tool_name,
                    description=meta["description"],
                    func=bound,
                    params=plist,
                    risk=meta["risk"],
                    final=meta["final"],
                    editable=meta["editable"],
                    confirm_label=meta["confirm_label"],
                    preview=make_preview(tool_name),
                    precheck=make_precheck(tool_name),
                    skill=self.name,
                    hides_popup=meta["hides_popup"],
                    title=meta["title"],
                )
            )
        return found
