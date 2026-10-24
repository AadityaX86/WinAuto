"""Settings window."""

from __future__ import annotations

import copy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from winauto.config import Config
from winauto.core.llm import OllamaClient, make_client
from winauto.secrets import get_secret, set_secret
from winauto.ui.async_util import run_async
from winauto.winos.hotkey import parse_hotkey

SUGGESTED_MODELS = ["qwen3:8b", "qwen3:14b", "qwen2.5:7b", "llama3.1:8b", "mistral-nemo:12b"]
BACKENDS = [("Ollama", "ollama"), ("OpenAI-compatible (LM Studio, llama.cpp...)", "openai")]
DEFAULT_URLS = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234/v1"}
GMAIL_SECRET = "gmail-app-password"  # same name the Gmail skill reads


class SettingsDialog(QDialog):
    saved = Signal(object)  # Config

    def __init__(self, config: Config, parent: QWidget | None = None, extra_sections: list[QWidget] | None = None):
        super().__init__(parent)
        self.setWindowTitle("WinAuto settings")
        self.setMinimumWidth(560)
        self.config = copy.deepcopy(config)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        def page(title: str) -> QVBoxLayout:
            w = QWidget()
            v = QVBoxLayout(w)
            self.tabs.addTab(w, title)
            return v

        general_page = page("General")
        ai_page = page("AI model")
        accounts_page = page("Email && messages")
        layout = ai_page

        # --- AI model ---
        ai = QGroupBox("Local AI model")
        form = QFormLayout(ai)
        self.backend = QComboBox()
        for label, value in BACKENDS:
            self.backend.addItem(label, value)
        values = [v for _, v in BACKENDS]
        self.backend.setCurrentIndex(values.index(self.config.llm.backend) if self.config.llm.backend in values else 0)
        self.backend.currentIndexChanged.connect(self._backend_changed)
        form.addRow("Server type", self.backend)
        self.url = QLineEdit(self.config.llm.base_url)
        form.addRow("Server address", self.url)
        model_row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(SUGGESTED_MODELS)
        self.model.setCurrentText(self.config.llm.model)
        refresh = QPushButton("Find installed")
        refresh.clicked.connect(self._refresh_models)
        model_row.addWidget(self.model, 1)
        model_row.addWidget(refresh)
        form.addRow("Model", model_row)
        self.num_ctx = QSpinBox()
        self.num_ctx.setRange(2048, 131072)
        self.num_ctx.setSingleStep(2048)
        self.num_ctx.setValue(self.config.llm.num_ctx)
        form.addRow("Context size", self.num_ctx)
        test_row = QHBoxLayout()
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(test)
        test_row.addWidget(self.test_result, 1)
        form.addRow("", test_row)
        layout.addWidget(ai)
        layout.addStretch(1)
        layout = general_page

        # --- General ---
        general = QGroupBox("General")
        gform = QFormLayout(general)
        self.user_name = QLineEdit(self.config.user_name)
        self.user_name.setPlaceholderText("Used to sign emails and messages")
        gform.addRow("Your name", self.user_name)
        self.hotkey = QLineEdit(self.config.hotkey)
        self.hotkey.setPlaceholderText("ctrl+alt+space")
        gform.addRow("Hotkey", self.hotkey)
        self.start_with_windows = QCheckBox("Start WinAuto when I sign in")
        self.start_with_windows.setChecked(self.config.start_with_windows)
        gform.addRow("", self.start_with_windows)
        self.quick = QCheckBox("Handle simple commands instantly without the AI")
        self.quick.setChecked(self.config.use_quick_commands)
        gform.addRow("", self.quick)
        self.search_engine = QComboBox()
        self.search_engine.addItems(["google", "bing", "duckduckgo"])
        self.search_engine.setCurrentText(self.config.search_engine)
        gform.addRow("Browser searches use", self.search_engine)
        self.weather = QLineEdit(self.config.weather_location)
        self.weather.setPlaceholderText("City for weather, e.g. Kathmandu (blank = auto)")
        gform.addRow("Weather location", self.weather)
        layout.addWidget(general)
        layout.addStretch(1)
        layout = accounts_page

        # --- Email ---
        mail = QGroupBox("Email (Gmail)")
        mform = QFormLayout(mail)
        self.email_address = QLineEdit(self.config.email.address)
        self.email_address.setPlaceholderText("you@gmail.com")
        mform.addRow("Gmail address", self.email_address)
        self.email_password = QLineEdit()
        self.email_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._had_password = bool(get_secret(GMAIL_SECRET))
        self.email_password.setPlaceholderText("saved (type to change)" if self._had_password else "16-letter app password")
        mform.addRow("App password", self.email_password)
        help_label = QLabel(
            'Create one at <a href="https://myaccount.google.com/apppasswords">myaccount.google.com/apppasswords</a>'
            "<br>(needs 2-Step Verification). Saved in Windows Credential Manager."
        )
        help_label.setOpenExternalLinks(True)
        help_label.setObjectName("Muted")
        mform.addRow("", help_label)
        self.email_signature = QLineEdit(self.config.email.signature)
        self.email_signature.setPlaceholderText("Optional, added to the end of emails")
        mform.addRow("Signature", self.email_signature)
        mail_test_row = QHBoxLayout()
        mail_test = QPushButton("Test Gmail")
        mail_test.clicked.connect(self._test_mail)
        self.mail_result = QLabel("")
        self.mail_result.setWordWrap(True)
        mail_test_row.addWidget(mail_test)
        mail_test_row.addWidget(self.mail_result, 1)
        mform.addRow("", mail_test_row)
        layout.addWidget(mail)

        # --- Messaging ---
        msg = QGroupBox("Messaging")
        msgform = QFormLayout(msg)
        self.country_code = QLineEdit(self.config.messaging.default_country_code)
        self.country_code.setPlaceholderText("e.g. 977 for Nepal, 91 for India")
        msgform.addRow("Your country code", self.country_code)
        self.wa_auto = QCheckBox("Press Send in WhatsApp for me after I approve")
        self.wa_auto.setChecked(self.config.messaging.whatsapp_auto_send)
        msgform.addRow("", self.wa_auto)
        self.discord_auto = QCheckBox("Press Send in Discord for me after I approve")
        self.discord_auto.setChecked(self.config.messaging.discord_auto_send)
        msgform.addRow("", self.discord_auto)
        layout.addWidget(msg)

        for section in extra_sections or []:
            layout.addWidget(section)
        layout.addStretch(1)
        layout = outer

        self.error = QLabel("")
        self.error.setObjectName("Muted")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _backend_changed(self) -> None:
        value = self.backend.currentData()
        if self.url.text().strip() in DEFAULT_URLS.values():
            self.url.setText(DEFAULT_URLS[value])

    def _collect(self) -> Config:
        cfg = copy.deepcopy(self.config)
        cfg.llm.backend = self.backend.currentData()
        cfg.llm.base_url = self.url.text().strip() or DEFAULT_URLS[cfg.llm.backend]
        cfg.llm.model = self.model.currentText().strip() or "qwen3:8b"
        cfg.llm.num_ctx = self.num_ctx.value()
        cfg.user_name = self.user_name.text().strip()
        cfg.hotkey = self.hotkey.text().strip().lower() or "ctrl+alt+space"
        cfg.start_with_windows = self.start_with_windows.isChecked()
        cfg.use_quick_commands = self.quick.isChecked()
        cfg.search_engine = self.search_engine.currentText()
        cfg.weather_location = self.weather.text().strip()
        cfg.email.address = self.email_address.text().strip()
        cfg.email.signature = self.email_signature.text().strip()
        cfg.messaging.default_country_code = self.country_code.text().strip().lstrip("+")
        cfg.messaging.whatsapp_auto_send = self.wa_auto.isChecked()
        cfg.messaging.discord_auto_send = self.discord_auto.isChecked()
        return cfg

    def _test_mail(self) -> None:
        from winauto.skills.gmail import GmailBackend

        address = self.email_address.text().strip()
        password = self.email_password.text().strip() or get_secret(GMAIL_SECRET) or ""
        if not address or not password:
            self.mail_result.setText("Enter your Gmail address and app password first.")
            return
        self.mail_result.setText("Signing in…")

        def done(result, error):
            self.mail_result.setText(f"✓ {result}" if not error else f"✗ {error}")

        run_async(lambda: GmailBackend(address, password).check(), done)

    def _refresh_models(self) -> None:
        cfg = self._collect()
        if cfg.llm.backend != "ollama":
            self.test_result.setText("Model list is only available for Ollama.")
            return
        client = OllamaClient(base_url=cfg.llm.base_url)
        self.test_result.setText("Looking…")

        def done(models, error):
            if error or not models:
                self.test_result.setText("No installed models found. Is Ollama running?")
                return
            current = self.model.currentText()
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentText(current if current in models else models[0])
            self.test_result.setText(f"Found {len(models)} model(s).")

        run_async(client.list_models, done)

    def _test(self) -> None:
        client = make_client(self._collect().llm)
        self.test_result.setText("Testing…")

        def done(result, error):
            if error:
                self.test_result.setText(f"✗ {error}")
                return
            ok, msg = result
            self.test_result.setText(("✓ " if ok else "✗ ") + msg)

        run_async(client.check, done)

    def _save(self) -> None:
        cfg = self._collect()
        try:
            parse_hotkey(cfg.hotkey)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        new_password = self.email_password.text().strip()
        if new_password and not set_secret(GMAIL_SECRET, new_password.replace(" ", "")):
            self.error.setText("Couldn't save the app password in Windows Credential Manager.")
            return
        self.saved.emit(cfg)
        self.accept()
