"""Connects the popup to the agent, running requests on a background thread."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from winauto.core.agent import AgentReply, ConfirmRequest, Decision
from winauto.ui.popup import ConfirmCard, PopupWindow

log = logging.getLogger(__name__)


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
    status_changed = Signal(str)

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
        popup.submitted.connect(self.submit)
        popup.stop_requested.connect(self.stop)
        popup.new_chat_requested.connect(self.new_chat)
        confirmer.requested.connect(self._show_card)
        self.reply_ready.connect(self._on_reply)
        self.status_changed.connect(popup.set_status)

    def on_status(self, text: str) -> None:
        """Agent status callback (any thread)."""
        self.status_changed.emit(text)

    def submit(self, text: str) -> None:
        if self._busy or self.runtime is None:
            return
        self._busy = True
        self.popup.set_busy(True)
        self.popup.set_status("Working…")
        gen = self._generation
        threading.Thread(target=self._work, args=(text, gen), daemon=True, name="agent").start()

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
        if self._should_hide(reply):
            QTimer.singleShot(1200, lambda g=gen: self._auto_hide(g))

    def _should_hide(self, reply: AgentReply) -> bool:
        """After 'open spotify' the popup gets out of the way, like Start search does."""
        registry = getattr(self.runtime, "registry", None)
        if registry is None or not reply.steps or reply.error:
            return False
        for step in reply.steps:
            t = registry.get(step.tool)
            if not (t and t.hides_popup and step.result.ok):
                return False
        return True

    def _auto_hide(self, gen: int) -> None:
        if gen == self._generation and not self._busy and not self.popup.input.text():
            self.popup.hide()

    def _show_card(self, pending: _Pending) -> None:
        card = self.popup.add_card(pending.request)
        pending.card = card
        card.decided.connect(pending.resolve)

    def stop(self) -> None:
        self._generation += 1
        if self.runtime:
            self.runtime.agent.cancel()
        self.confirmer.cancel_all()
        self.popup.add_bot("Stopped. (A step that was already running may still finish.)")
        self._busy = False
        self.popup.set_busy(False)

    def new_chat(self) -> None:
        self._generation += 1
        self._busy = False
        self.popup.set_busy(False)
        if self.runtime:
            self.runtime.agent.cancel()
        self.confirmer.cancel_all()
        # Cleared right before the next request, once any stopped one has finished.
        self._reset_pending = True
        self.popup.clear()
