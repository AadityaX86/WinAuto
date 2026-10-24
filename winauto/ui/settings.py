"""Settings window: sidebar navigation with card-style pages (Windows 11 look)."""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from winauto.config import Config
from winauto.services.settings import SettingsService
from winauto.ui.async_util import run_async
from winauto.ui.hotkey_edit import HotkeyEdit
from winauto.ui.icons import icon
from winauto.ui.theme import DARK, LIGHT, Palette, is_dark
from winauto.ui.widgets import ToggleSwitch

SUGGESTED_MODELS = ["qwen3:8b", "qwen3:14b", "qwen3:32b", "qwen2.5:7b", "llama3.1:8b", "mistral-nemo:12b"]
VISION_MODELS = ["qwen2.5vl:7b", "gemma3:4b", "gemma3:12b", "llama3.2-vision:11b", "llava:7b"]
BACKENDS = [("Built-in (recommended)", "builtin"), ("Ollama", "ollama"),
            ("OpenAI-compatible (LM Studio, llama.cpp…)", "openai")]
DEFAULT_URLS = {"builtin": "http://localhost:11434", "ollama": "http://localhost:11434", "openai": "http://localhost:1234/v1"}
THEMES = [("Match Windows", "system"), ("Dark", "dark"), ("Light", "light")]


class SettingsDialog(QDialog):
    saved = Signal(object)  # Config

    def __init__(self, config: Config, parent: QWidget | None = None,
                 skills: list[tuple[str, ...]] | None = None, extra_sections: list[QWidget] | None = None,
                 palette: Palette | None = None, service: SettingsService | None = None):
        super().__init__(parent)
        self.service = service or SettingsService()
        self.setWindowTitle("WinAuto settings")
        self.resize(900, 640)
        self.config = copy.deepcopy(config)
        self.p: Palette = palette or (DARK if (config.theme == "dark" or (config.theme == "system" and is_dark())) else LIGHT)
        self._skill_toggles: dict[str, ToggleSwitch] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.setFixedWidth(210)
        self.nav.setIconSize(QSize(18, 18))
        body.addWidget(self.nav)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)

        self._build_general()
        self._build_ai()
        self._build_accounts()
        self._build_focus()
        self._build_skills(skills or [])
        self._build_about()
        for section in extra_sections or []:
            self.pages.widget(0).layout().addWidget(section)
        self.nav.setCurrentRow(0)

        # Bottom bar
        bar = QFrame()
        bar.setObjectName("SettingsPage")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 12, 20, 14)
        self.error = QLabel("")
        self.error.setObjectName("RowHelp")
        self.error.setStyleSheet(f"color: {self.p.danger};")
        h.addWidget(self.error, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        h.addWidget(cancel)
        h.addWidget(save)
        root.addWidget(bar)

    # ----- page building helpers -----

    def _page(self, title: str, icon_name: str, subtitle: str = "") -> QVBoxLayout:
        item = QListWidgetItem(icon(icon_name, self.p.text, 18), "  " + title)
        item.setSizeHint(QSize(190, 38))
        self.nav.addItem(item)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setObjectName("SettingsPage")
        v = QVBoxLayout(page)
        v.setContentsMargins(28, 24, 28, 16)
        v.setSpacing(12)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        v.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("RowHelp")
            s.setWordWrap(True)
            v.addWidget(s)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return v

    def _card(self, layout: QVBoxLayout, title: str = "") -> QVBoxLayout:
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            layout.addSpacing(6)
            layout.addWidget(label)
        card = QFrame()
        card.setObjectName("SettingsCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 6, 16, 6)
        v.setSpacing(0)
        layout.addWidget(card)
        return v

    def _row(self, card: QVBoxLayout, title: str, help_text: str, control: QWidget | None,
             stretch_control: bool = False) -> QWidget:
        if card.count():
            line = QFrame()
            line.setObjectName("RowDivider")
            card.addWidget(line)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 10, 0, 10)
        h.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("RowTitle")
        text.addWidget(t)
        if help_text:
            hl = QLabel(help_text)
            hl.setObjectName("RowHelp")
            hl.setWordWrap(True)
            hl.setOpenExternalLinks(True)
            hl.setTextFormat(Qt.TextFormat.RichText)
            text.addWidget(hl)
        h.addLayout(text, 1)
        if control is not None:
            if not stretch_control and not isinstance(control, ToggleSwitch):
                control.setMinimumWidth(260)
                control.setMaximumWidth(320)
            h.addWidget(control, 1 if stretch_control else 0, Qt.AlignmentFlag.AlignVCenter)
        card.addWidget(row)
        return row

    def _toggle(self, value: bool) -> ToggleSwitch:
        return ToggleSwitch(self.p, value)

    # ----- pages -----

    def _build_general(self) -> None:
        v = self._page("General", "home")
        c = self._card(v)
        self.user_name = QLineEdit(self.config.user_name)
        self.user_name.setPlaceholderText("Used to greet you and sign emails")
        self._row(c, "Your name", "", self.user_name)
        self.theme = QComboBox()
        for label, value in THEMES:
            self.theme.addItem(label, value)
        theme_values = [value for _, value in THEMES]
        self.theme.setCurrentIndex(theme_values.index(self.config.theme) if self.config.theme in theme_values else 0)
        self._row(c, "Appearance", "Takes effect next time WinAuto starts.", self.theme)

        c = self._card(v, "Shortcuts")
        self.hotkey = HotkeyEdit(self.config.hotkey)
        self._row(c, "Open WinAuto", "Works from any app. Click the box, then press new keys.", self.hotkey)
        self.text_hotkey = HotkeyEdit(self.config.text_hotkey, can_clear=True)
        self._row(c, "Writing tools", "Select text in any app, then press this. Backspace turns it off.",
                  self.text_hotkey)

        c = self._card(v, "Behaviour")
        self.start_with_windows = self._toggle(self.config.start_with_windows)
        self._row(c, "Start with Windows", "Run quietly in the tray when you sign in.", self.start_with_windows)
        self.hide_on_click = self._toggle(self.config.hide_on_click_away)
        self._row(c, "Hide when you click elsewhere", "Like the Start menu. Stays open while it's working or waiting "
                  "for your approval.", self.hide_on_click)
        self.quick = self._toggle(self.config.use_quick_commands)
        self._row(c, "Instant commands", "Handle simple commands like “volume 30” without the AI.", self.quick)
        self.briefing = self._toggle(self.config.morning_briefing)
        self._row(c, "Morning briefing", "Show weather, calendar and todos the first time you open WinAuto each morning.", self.briefing)
        self.speak = self._toggle(self.config.speak_replies)
        self._row(c, "Read answers aloud", "Uses Windows' built-in voices.", self.speak)

        c = self._card(v, "Web & media")
        self.search_engine = QComboBox()
        self.search_engine.addItems(["google", "bing", "duckduckgo"])
        self.search_engine.setCurrentText(self.config.search_engine)
        self._row(c, "Browser searches", "Where “search …” opens.", self.search_engine)
        self.music = QComboBox()
        self.music.addItems(["youtube", "spotify"])
        self.music.setCurrentText(self.config.music_service)
        self._row(c, "Play music with", "“play lofi beats” uses this.", self.music)
        self.weather = QLineEdit(self.config.weather_location)
        self.weather.setPlaceholderText("e.g. Kathmandu (blank = automatic)")
        self._row(c, "Weather location", "", self.weather)
        v.addStretch(1)

    def _section(self, layout: QVBoxLayout, title: str) -> tuple[QWidget, QVBoxLayout]:
        """A titled card that can be shown or hidden as a whole."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        card = self._card(v, title)
        layout.addWidget(box)
        return box, card

    def _build_ai(self) -> None:
        v = self._page("AI model", "sparkles", "WinAuto's AI runs on your own PC. Nothing is sent to an AI company.")
        c = self._card(v)
        self.backend = QComboBox()
        for label, value in BACKENDS:
            self.backend.addItem(label, value)
        values = [v_ for _, v_ in BACKENDS]
        self.backend.setCurrentIndex(values.index(self.config.llm.backend) if self.config.llm.backend in values else 0)
        self.backend.currentIndexChanged.connect(self._backend_changed)
        self._row(c, "AI engine", "Built-in needs no setup. Pick Ollama or another server if you already use one.",
                  self.backend)

        # Built-in AI
        self.builtin_box, c = self._section(v, "Built-in AI")
        self.builtin_model = QComboBox()
        for model_id, label in self.service.builtin_models():
            self.builtin_model.addItem(label, model_id)
        current = self.config.llm.builtin_model or self.service.builtin_default()
        index = self.builtin_model.findData(current)
        self.builtin_model.setCurrentIndex(max(index, 0))
        self._row(c, "Model", "Downloaded once, then works offline. Both understand screenshots.",
                  self.builtin_model)
        hardware = self.service.hardware()
        if hardware:
            self._row(c, "This PC", hardware, None)

        # Ollama / OpenAI-compatible server
        self.server_box, c = self._section(v, "Server")
        self.url = QLineEdit(self.config.llm.base_url)
        self._row(c, "Server address", "", self.url)
        model_box = QWidget()
        mh = QHBoxLayout(model_box)
        mh.setContentsMargins(0, 0, 0, 0)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(SUGGESTED_MODELS)
        self.model.setCurrentText(self.config.llm.model)
        find = QPushButton("Find installed")
        find.clicked.connect(self._refresh_models)
        mh.addWidget(self.model, 1)
        mh.addWidget(find)
        self._row(c, "Chat model", "Needs tool support. 8 GB VRAM: qwen3:8b · 12 GB+: qwen3:14b.", model_box)
        self.vision = QComboBox()
        self.vision.setEditable(True)
        self.vision.addItems(VISION_MODELS)
        self.vision.setCurrentText(self.config.llm.vision_model)
        self._row(c, "Vision model", "For “what's on my screen?”. Run: ollama pull qwen2.5vl:7b", self.vision)

        c = self._card(v, "Options")
        self.num_ctx = QSpinBox()
        self.num_ctx.setRange(2048, 131072)
        self.num_ctx.setSingleStep(2048)
        self.num_ctx.setValue(self.config.llm.num_ctx)
        self._row(c, "Context size", "How much the model can read at once (Ollama). Bigger uses more memory.", self.num_ctx)
        self.stream = self._toggle(self.config.llm.stream)
        self._row(c, "Stream answers", "Show answers word by word as they're written.", self.stream)
        test_box = QWidget()
        th = QHBoxLayout(test_box)
        th.setContentsMargins(0, 0, 0, 0)
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setObjectName("RowHelp")
        self.test_result.setWordWrap(True)
        th.addWidget(test)
        th.addWidget(self.test_result, 1)
        self._row(c, "Check", "", test_box, stretch_control=True)
        v.addStretch(1)
        self._backend_changed()

    def _build_accounts(self) -> None:
        v = self._page("Accounts", "mail")
        c = self._card(v, "Gmail")
        self.email_address = QLineEdit(self.config.email.address)
        self.email_address.setPlaceholderText("you@gmail.com")
        self._row(c, "Gmail address", "", self.email_address)
        self.email_password = QLineEdit()
        self.email_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._had_password = self.service.gmail_password_saved()
        self.email_password.setPlaceholderText("saved (type to change)" if self._had_password else "16-letter app password")
        self._row(c, "App password",
                  'Create one at <a href="https://myaccount.google.com/apppasswords">myaccount.google.com/apppasswords</a> '
                  "(needs 2-Step Verification). Kept in Windows Credential Manager.", self.email_password)
        self.email_signature = QLineEdit(self.config.email.signature)
        self.email_signature.setPlaceholderText("Optional, added to the end of emails")
        self._row(c, "Signature", "", self.email_signature)
        mail_box = QWidget()
        mh = QHBoxLayout(mail_box)
        mh.setContentsMargins(0, 0, 0, 0)
        mail_test = QPushButton("Test Gmail")
        mail_test.clicked.connect(self._test_mail)
        self.mail_result = QLabel("")
        self.mail_result.setObjectName("RowHelp")
        self.mail_result.setWordWrap(True)
        mh.addWidget(mail_test)
        mh.addWidget(self.mail_result, 1)
        self._row(c, "Check", "", mail_box, stretch_control=True)

        c = self._card(v, "Messaging")
        self.country_code = QLineEdit(self.config.messaging.default_country_code)
        self.country_code.setPlaceholderText("e.g. 977 for Nepal, 91 for India")
        self._row(c, "Your country code", "Added to numbers saved without one.", self.country_code)
        self.wa_auto = self._toggle(self.config.messaging.whatsapp_auto_send)
        self._row(c, "Press Send in WhatsApp", "After you approve the message.", self.wa_auto)
        self.discord_auto = self._toggle(self.config.messaging.discord_auto_send)
        self._row(c, "Press Send in Discord", "After you approve the message.", self.discord_auto)

        c = self._card(v, "Calendar")
        self.calendars = QPlainTextEdit("\n".join(self.config.calendar_urls))
        self.calendars.setPlaceholderText("https://calendar.google.com/calendar/ical/…/basic.ics")
        self.calendars.setFixedHeight(80)
        self._row(c, "Calendar links (one per line)",
                  "Google Calendar: Settings → your calendar → <i>Secret address in iCal format</i>. "
                  "Outlook: Settings → Shared calendars → Publish → ICS. Read-only.", None)
        c.addWidget(self.calendars)
        c.addSpacing(10)
        v.addStretch(1)

    def _build_focus(self) -> None:
        v = self._page("Focus", "target", "During a focus session these apps are minimised whenever they open.")
        c = self._card(v)
        self.focus_apps = QLineEdit(", ".join(self.config.focus_block_apps))
        self.focus_apps.setPlaceholderText("discord, steam, whatsapp")
        self._row(c, "Apps to keep away", "Comma separated app names.", self.focus_apps, stretch_control=True)
        v.addStretch(1)

    def _build_skills(self, skills: list[tuple[str, ...]]) -> None:
        """skills: (name, description) or (name, description, icon) for each loaded skill."""
        v = self._page("Skills", "puzzle", "Turn off abilities you don't use. Changes apply after restarting WinAuto.")
        c = self._card(v)
        disabled = set(self.config.disabled_skills)
        for name, description, *extra in sorted(skills):
            toggle = self._toggle(name not in disabled)
            self._skill_toggles[name] = toggle
            row = self._row(c, name.replace("textactions", "writing tools").capitalize(), description, toggle)
            ic = QLabel()
            ic.setPixmap(icon(extra[0] if extra else "puzzle", self.p.accent, 18).pixmap(18, 18))
            row.layout().insertWidget(0, ic)
        if not skills:
            self._row(c, "No skills loaded", "", None)
        v.addStretch(1)

    def _build_about(self) -> None:
        v = self._page("About", "info")
        c = self._card(v)
        self._row(c, f"WinAuto {self.service.version}", "A private assistant for Windows that runs on your own AI model.", None)
        gh = QPushButton("Open on GitHub")
        gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/AadityaX86/WinAuto")))
        self._row(c, "Source code", "Updates, issues and the README.", gh)
        data_btn = QPushButton("Open data folder")
        data_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.data_dir))))
        self._row(c, "Your data", str(self.service.data_dir), data_btn)
        c = self._card(v, "Tips")
        for title, text in (
            ("Prefixes", "<b>&gt;</b> runs a terminal command · <b>:</b> finds emoji · <b>/</b> finds files · <b>clip</b> shows clipboard history"),
            ("Keys", "↑↓ choose a result · Enter opens it · Ctrl+Enter asks the AI · Esc hides"),
        ):
            self._row(c, title, text, None)
        v.addStretch(1)

    # ----- behaviour -----

    def _backend_changed(self) -> None:
        value = self.backend.currentData()
        self.builtin_box.setVisible(value == "builtin")
        self.server_box.setVisible(value != "builtin")
        if value != "builtin" and self.url.text().strip() in DEFAULT_URLS.values():
            self.url.setText(DEFAULT_URLS[value])

    def _collect(self) -> Config:
        cfg = copy.deepcopy(self.config)
        cfg.llm.backend = self.backend.currentData()
        if cfg.llm.backend == "builtin":
            cfg.llm.builtin_model = self.builtin_model.currentData() or cfg.llm.builtin_model
        cfg.llm.base_url = self.url.text().strip() or DEFAULT_URLS[cfg.llm.backend]
        cfg.llm.model = self.model.currentText().strip() or "qwen3:8b"
        cfg.llm.vision_model = self.vision.currentText().strip()
        cfg.llm.num_ctx = self.num_ctx.value()
        cfg.llm.stream = self.stream.isChecked()
        cfg.user_name = self.user_name.text().strip()
        cfg.theme = self.theme.currentData()
        cfg.hotkey = self.hotkey.combo() or "ctrl+alt+space"
        cfg.text_hotkey = self.text_hotkey.combo()
        cfg.start_with_windows = self.start_with_windows.isChecked()
        cfg.hide_on_click_away = self.hide_on_click.isChecked()
        cfg.use_quick_commands = self.quick.isChecked()
        cfg.morning_briefing = self.briefing.isChecked()
        cfg.speak_replies = self.speak.isChecked()
        cfg.search_engine = self.search_engine.currentText()
        cfg.music_service = self.music.currentText()
        cfg.weather_location = self.weather.text().strip()
        cfg.email.address = self.email_address.text().strip()
        cfg.email.signature = self.email_signature.text().strip()
        cfg.messaging.default_country_code = self.country_code.text().strip().lstrip("+")
        cfg.messaging.whatsapp_auto_send = self.wa_auto.isChecked()
        cfg.messaging.discord_auto_send = self.discord_auto.isChecked()
        cfg.calendar_urls = [u.strip() for u in self.calendars.toPlainText().splitlines() if u.strip()]
        cfg.focus_block_apps = [a.strip() for a in self.focus_apps.text().split(",") if a.strip()]
        cfg.disabled_skills = sorted(n for n, t in self._skill_toggles.items() if not t.isChecked())
        return cfg

    def _refresh_models(self) -> None:
        cfg = self._collect()
        if cfg.llm.backend != "ollama":
            self.test_result.setText("Model list is only available for Ollama.")
            return
        self.test_result.setText("Looking…")

        def done(models, error):
            if error or not models:
                self.test_result.setText("No installed models found. Is Ollama running?")
                return
            current, vision = self.model.currentText(), self.vision.currentText()
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentText(current if current in models else models[0])
            self.vision.clear()
            self.vision.addItems(models)
            self.vision.setCurrentText(vision)
            self.test_result.setText(f"Found {len(models)} model(s).")

        run_async(lambda: self.service.list_models(cfg.llm), done)

    def _test(self) -> None:
        llm = self._collect().llm
        self.test_result.setText("Testing…")

        def done(result, error):
            if error:
                self.test_result.setText(f"✗ {error}")
                return
            ok, msg = result
            self.test_result.setText(("✓ " if ok else "✗ ") + msg)

        run_async(lambda: self.service.check_model(llm), done)

    def _test_mail(self) -> None:
        address = self.email_address.text().strip()
        password = self.email_password.text().strip()
        if not address or not (password or self._had_password):
            self.mail_result.setText("Enter your Gmail address and app password first.")
            return
        self.mail_result.setText("Signing in…")

        def done(result: Any, error: Any) -> None:
            self.mail_result.setText(f"✓ {result}" if not error else f"✗ {error}")

        run_async(lambda: self.service.test_gmail(address, password), done)

    def _save(self) -> None:
        cfg = self._collect()
        for label, combo in (("Open WinAuto", cfg.hotkey), ("Writing tools", cfg.text_hotkey)):
            if not combo:
                continue
            problem = self.service.hotkey_error(combo)
            if problem:
                self.error.setText(f"{label}: {problem}")
                self.nav.setCurrentRow(0)
                return
        if cfg.text_hotkey and cfg.text_hotkey == cfg.hotkey:
            self.error.setText("The two shortcuts must be different.")
            return
        new_password = self.email_password.text().strip()
        if new_password and not self.service.save_gmail_password(new_password):
            self.error.setText("Couldn't save the app password in Windows Credential Manager.")
            return
        self.saved.emit(cfg)
        self.accept()
