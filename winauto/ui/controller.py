"""Connects the popup to the agent: live search, running results, chat, approvals, streaming."""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from winauto.core.agent import AgentReply, ConfirmRequest, Decision, Step
from winauto.core.launcher import ASK_TOOL
from winauto.core.llm import ToolCall
from winauto.core.skill import Suggestion, ToolResult
from winauto.storage.db import now_iso
from winauto.ui.popup import ConfirmCard, PopupWindow

log = logging.getLogger(__name__)

COPY_TOOLS = {"set_clipboard", "copy_from_history"}

HOME_SUGGESTIONS = [
    Suggestion("Daily briefing", "daily_briefing", {}, "Weather, calendar, todos and news", "Command", "sun"),
    Suggestion("What's on my screen?", "ask_about_screen", {"question": "What's on my screen? Give a short overview."},
               "Ask the vision model", "Command", "eye"),
    Suggestion("Show my todos", "list_todos", {}, "Open tasks", "Command", "check"),
    Suggestion("Start a 25-minute focus session", "start_focus", {"minutes": 25}, "Pomodoro", "Command", "target"),
    Suggestion("Clipboard history", "clipboard_history", {}, "Recently copied text", "Command", "clipboard"),
    Suggestion("Check my email", "check_email", {}, "Unread in Gmail", "Command", "mail"),
]


class _Pending:
    def __init__(self, request: ConfirmRequest):
        self.request = request
        self.event = threading.Event()
        self.decision = Decision(False)
        self.card: ConfirmCard | None = None

    def resolve(self, decision: Decision) -> None:
        self.decision = decision
        self.event.set()


class QtConfirmer(QObject):
    """Called from the agent's thread; shows a card on the UI thread and waits."""

    requested = Signal(object)  # _Pending

    def __init__(self) -> None:
        super().__init__()
        self._pending: list[_Pending] = []
        self._lock = threading.Lock()

    def confirm(self, request: ConfirmRequest) -> Decision:
        pending = _Pending(request)
        with self._lock:
            self._pending.append(pending)
        self.requested.emit(pending)
        pending.event.wait()
        with self._lock:
            if pending in self._pending:
                self._pending.remove(pending)
        return pending.decision

    def cancel_all(self) -> None:
        with self._lock:
            pending = list(self._pending)
        for p in pending:
            if p.card:
                p.card.expire()  # emits decided -> resolve
            p.resolve(Decision(False))


class Controller(QObject):
    reply_ready = Signal(object, int)  # AgentReply, request number
    call_done = Signal(object, object, str, int)  # ToolCall, ToolResult, label, request number
    status_changed = Signal(str)
    token = Signal(str)
    home_data = Signal(object)

    def __init__(self, popup: PopupWindow, confirmer: QtConfirmer):
        super().__init__()
        self.popup = popup
        self.confirmer = confirmer
        self.runtime = None  # set by the app once built
        self._busy = False
        self._generation = 0
        # The agent isn't thread-safe; a new request waits for a stopped one to wind down.
        self._agent_lock = threading.Lock()
        self._reset_pending = False
        self._pending_query = ""
        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(35)
        self._query_timer.timeout.connect(self._run_query)

        popup.submitted.connect(self.submit)
        popup.suggestion_chosen.connect(self.run_suggestion)
        popup.query_changed.connect(self._query_changed)
        popup.action_requested.connect(self.run_action)
        popup.text_action.connect(self.run_text_action)
        popup.stop_requested.connect(self.stop)
        popup.new_chat_requested.connect(self.new_chat)
        popup.mic_requested.connect(self.dictate)
        confirmer.requested.connect(self._show_card)
        self.reply_ready.connect(self._on_reply)
        self.call_done.connect(self._on_call_done)
        self.status_changed.connect(popup.set_status)
        self.token.connect(popup.stream_token)
        self.home_data.connect(self._apply_home_data)

    # ----- wiring helpers -----

    def attach(self, runtime) -> None:
        self.runtime = runtime
        if getattr(runtime.config.llm, "stream", True):
            runtime.agent.on_token = self.token.emit
        self.refresh_home()

    def on_status(self, text: str) -> None:
        """Agent status callback (any thread)."""
        self.status_changed.emit(text)

    # ----- live search -----

    def _query_changed(self, text: str) -> None:
        self._pending_query = text
        self._query_timer.start()

    def _run_query(self) -> None:
        if self.runtime is None or self.popup.mode != "results":
            return
        try:
            results = self.runtime.launcher.search(self._pending_query)
        except Exception:
            log.exception("launcher search failed")
            results = []
        self.popup.show_results(results)

    # ----- running things -----

    def _record(self, text: str) -> None:
        if not text or self.runtime is None:
            return
        try:
            db = self.runtime.db
            db.execute("DELETE FROM history WHERE text = ?", (text,))
            db.execute("INSERT INTO history(text, created_at) VALUES(?, ?)", (text, now_iso()))
            db.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 200)")
        except Exception:
            log.debug("couldn't record history", exc_info=True)

    def submit(self, text: str) -> None:
        """Send text to the assistant (quick command or AI)."""
        if self._busy or self.runtime is None:
            return
        self._record(text)
        self._start()
        gen = self._generation
        threading.Thread(target=self._work, args=(text, gen), daemon=True, name="agent").start()

    def run_suggestion(self, s: Suggestion) -> None:
        if self.runtime is None or self._busy:
            return
        typed = self.popup.input.text().strip()
        if s.tool == ASK_TOOL:
            self.popup.input.clear()
            text = s.args.get("text", typed)
            self.popup.add_user(text)
            self.submit(text)
            return
        self._record(typed or s.title)
        self.popup.input.clear()
        self._run_call(ToolCall(s.tool, dict(s.args)), s.title)

    def run_action(self, action: dict) -> None:
        if self.runtime is None or self._busy:
            return
        self._run_call(ToolCall(action["tool"], dict(action.get("args", {}))), "", quiet=True)

    def run_text_action(self, key: str) -> None:
        if self.runtime is None or self._busy:
            return
        if key.startswith("custom:"):
            args = {"action": "custom", "instruction": key[len("custom:"):]}
            label = key[len("custom:"):]
        else:
            args = {"action": key}
            from winauto.skills.textactions import ACTIONS

            label = ACTIONS.get(key, (key,))[0]
        self.popup.add_user(label)
        self._run_call(ToolCall("transform_text", args), label, quiet=True)

    def _run_call(self, call: ToolCall, label: str, quiet: bool = False) -> None:
        self._start()
        gen = self._generation

        def work() -> None:
            with self._agent_lock:
                try:
                    result = self.runtime.agent.run_tool(call)
                except Exception as exc:
                    log.exception("tool %s crashed", call.name)
                    result = ToolResult(False, f"Something went wrong: {exc}")
            self.call_done.emit(call, result, "" if quiet else label, gen)

        threading.Thread(target=work, daemon=True, name="tool").start()

    def _start(self) -> None:
        self._busy = True
        self.popup.set_busy(True)
        self.popup.set_status("Working…")

    def _work(self, text: str, gen: int) -> None:
        with self._agent_lock:
            if self._reset_pending:
                self._reset_pending = False
                self.runtime.agent.reset()
            try:
                reply = self.runtime.agent.handle(text)
            except Exception as exc:
                log.exception("Agent crashed on %r", text)
                reply = AgentReply(f"Something went wrong: {exc}", error="crash")
        self.reply_ready.emit(reply, gen)

    def _on_reply(self, reply: AgentReply, gen: int) -> None:
        if gen != self._generation:
            return  # the user pressed Stop or started a new chat meanwhile
        self._busy = False
        self.popup.set_busy(False)
        self.popup.add_reply(reply)
        self._speak(reply.text)
        if self._should_hide(reply.steps, reply.error):
            QTimer.singleShot(1000, lambda g=gen: self._auto_hide(g))
        self.refresh_home()

    def _on_call_done(self, call: ToolCall, result: ToolResult, label: str, gen: int) -> None:
        if gen != self._generation:
            return
        self._busy = False
        self.popup.set_busy(False)
        step = Step(call.name, call.arguments, result)
        if result.ok and call.name in COPY_TOOLS and not self.popup.has_chat:
            self.popup.flash("✓ Copied")
            QTimer.singleShot(650, lambda g=gen: self._auto_hide(g))
            return
        if self._should_hide([step], None) and not self.popup.has_chat:
            self.popup.flash("✓ " + (result.message or "Done"))
            QTimer.singleShot(500, lambda g=gen: self._auto_hide(g))
            return
        if label:
            self.popup.add_user(label)
        reply = AgentReply(result.message, [step], error=None if result.ok or result.cancelled else "tool")
        self.popup.add_reply(reply)
        if self.runtime and label:
            self.runtime.agent._remember(label, reply)
        self._speak(result.message)
        self.refresh_home()

    def _should_hide(self, steps: list[Step], error: str | None) -> bool:
        """After 'open spotify' the popup gets out of the way, like Start search does."""
        registry = getattr(self.runtime, "registry", None)
        if registry is None or not steps or error:
            return False
        for step in steps:
            t = registry.get(step.tool)
            if not (t and t.hides_popup and step.result.ok):
                return False
        return True

    def _auto_hide(self, gen: int) -> None:
        if gen == self._generation and not self._busy and not self.popup.input.text():
            self.popup.hide()
            if not self.popup.has_chat:
                self.popup.set_mode("home")

    def _speak(self, text: str) -> None:
        if not text or self.runtime is None or not getattr(self.runtime.config, "speak_replies", False):
            return
        voice = self.runtime.ctx.services.get("skills", {}).get("voice")
        if voice:
            threading.Thread(target=voice.say, args=(text,), daemon=True).start()

    def _show_card(self, pending: _Pending) -> None:
        card = self.popup.add_card(pending.request)
        pending.card = card
        card.decided.connect(pending.resolve)

    def stop(self) -> None:
        self._generation += 1
        if self.runtime:
            self.runtime.agent.cancel()
        self.confirmer.cancel_all()
        self.popup.chat.end_stream()
        self.popup.add_bot("Stopped. (A step that was already running may still finish.)")
        self._busy = False
        self.popup.set_busy(False)

    def new_chat(self) -> None:
        self._generation += 1
        self._busy = False
        self.popup.set_busy(False)
        if self.runtime:
            self.runtime.agent.cancel()
            self.runtime.ctx.services.pop("selection", None)
        self.confirmer.cancel_all()
        # Cleared right before the next request, once any stopped one has finished.
        self._reset_pending = True
        self.popup.clear()
        self.refresh_home()

    # ----- writing tools / dictation / briefing -----

    def open_text_mode(self, selection: str) -> None:
        if self.runtime is None:
            return
        from winauto.skills.textactions import ACTIONS

        self.runtime.ctx.services["selection"] = selection
        actions = [(k, label, ic) for k, (label, ic, _) in ACTIONS.items()]
        self.popup.show_text_mode(selection, actions)

    def dictate(self) -> None:
        """Windows' own voice typing (Win+H) types into the search box."""
        self.popup.input.setFocus()
        import sys

        if sys.platform != "win32":
            self.popup.flash("Dictation needs Windows")
            return

        def press() -> None:
            try:
                from winauto.winos.keyboard import press as press_keys

                press_keys("win+h")
            except Exception:
                log.debug("voice typing failed", exc_info=True)

        QTimer.singleShot(150, lambda: threading.Thread(target=press, daemon=True).start())

    def maybe_morning_briefing(self) -> None:
        if self.runtime is None or self._busy or self.popup.has_chat:
            return
        briefing = self.runtime.ctx.services.get("skills", {}).get("briefing")
        if briefing and briefing.due_for_morning_briefing():
            self._run_call(ToolCall("daily_briefing", {}), "Daily briefing")

    # ----- home screen -----

    def refresh_home(self) -> None:
        if self.runtime is None:
            return
        self.popup.home.refresh_greeting(self.runtime.config.user_name)
        recent = []
        try:
            for r in self.runtime.db.query("SELECT text FROM history ORDER BY id DESC LIMIT 5"):
                recent.append(Suggestion(r["text"], ASK_TOOL, {"text": r["text"]}, "", "", "history"))
        except Exception:
            pass
        available = {t.name for t in self.runtime.registry.tools}
        suggestions = [s for s in HOME_SUGGESTIONS if s.tool in available]
        self.popup.home.set_lists(suggestions, recent)
        threading.Thread(target=self._collect_home_data, daemon=True, name="home").start()

    def _collect_home_data(self) -> None:
        items: list[tuple[str, str]] = []
        rt = self.runtime
        try:
            now = datetime.now()
            end = datetime.combine(now.date(), datetime.max.time()).isoformat(sep=" ")
            due = rt.db.one("SELECT COUNT(*) AS n FROM todos WHERE done = 0 AND due_at IS NOT NULL AND due_at <= ?", (end,))["n"]
            open_n = rt.db.one("SELECT COUNT(*) AS n FROM todos WHERE done = 0")["n"]
            if open_n:
                items.append(("check", f"{due} due today" if due else f"{open_n} open todo{'s' if open_n != 1 else ''}"))
            nxt = rt.db.one("SELECT text, due_at FROM reminders WHERE active = 1 ORDER BY due_at LIMIT 1")
            if nxt:
                when = datetime.fromisoformat(nxt["due_at"])
                stamp = when.strftime("%I:%M %p").lstrip("0") if when.date() == now.date() else when.strftime("%a %I:%M %p")
                items.append(("bell", f"{nxt['text'][:28]} · {stamp}"))
            cal = rt.ctx.services.get("skills", {}).get("calendar")
            if cal and rt.config.calendar_urls:
                events, _ = cal.events_between(now, datetime.combine(now.date(), datetime.max.time()))
                upcoming = [e for e in events if not e.all_day and e.start >= now]
                if upcoming:
                    e = upcoming[0]
                    items.append(("calendar", f"{e.title[:26]} · {e.start.strftime('%I:%M %p').lstrip('0')}"))
            cached = rt.db.get_value("home_weather")
            fetched_at = float(rt.db.get_value("home_weather_at") or 0)
            if (not cached or now.timestamp() - fetched_at > 3600) and rt.ctx.services.get("skills", {}).get("web"):
                w = rt.ctx.services["skills"]["web"].get_weather("")
                if w.ok:
                    import re

                    m = re.search(r"(-?\d+)°C and ([^(]+?) \(", w.message)
                    if m:
                        cached = f"{m.group(1)}° {m.group(2).strip().capitalize()}"
                        rt.db.set_value("home_weather", cached)
                        rt.db.set_value("home_weather_at", str(now.timestamp()))
            if cached:
                items.append(("cloud", cached))
        except Exception:
            log.debug("home data failed", exc_info=True)
        self.home_data.emit(items)

    def _apply_home_data(self, items) -> None:
        self.popup.home.set_widgets(items)
