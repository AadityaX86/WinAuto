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
    QVBoxLayout,
    QWidget,
)

from winauto.config import Config
from winauto.core.llm import OllamaClient, make_client
from winauto.ui.async_util import run_async
from winauto.winos.hotkey import parse_hotkey

SUGGESTED_MODELS = ["qwen3:8b", "qwen3:14b", "qwen2.5:7b", "llama3.1:8b", "mistral-nemo:12b"]
BACKENDS = [("Ollama", "ollama"), ("OpenAI-compatible (LM Studio, llama.cpp...)", "openai")]
DEFAULT_URLS = {"ollama": "http://localhost:11434", "openai": "http://localhost:1234/v1"}


class SettingsDialog(QDialog):
    saved = Signal(object)  # Config

    def __init__(self, config: Config, parent: QWidget | None = None, extra_sections: list[QWidget] | None = None):
        super().__init__(parent)
        self.setWindowTitle("WinAuto settings")
        self.setMinimumWidth(560)
        self.config = copy.deepcopy(config)
        layout = QVBoxLayout(self)

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

        for section in extra_sections or []:
            layout.addWidget(section)

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
        return cfg

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
        self.saved.emit(cfg)
        self.accept()
