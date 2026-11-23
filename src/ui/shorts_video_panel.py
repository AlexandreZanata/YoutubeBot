"""Shorts-only AI video generation configuration, status and clip preview panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tools.ytbot.shorts_video import (
    credits,
    flow_browser,
    settings as shorts_settings,
)
from tools.ytbot.shorts_video.models import GENERATION_STATES
from tools.ytbot.shorts_video.pipeline import render_ai_short
from tools.ytbot.shorts_video.storyboard import load_storyboard

STATE_COLORS = {
    "Waiting": "#64748b",
    "Preparing storyboard": "#0284c7",
    "Generating": "#6366f1",
    "Downloading or importing": "#0ea5e9",
    "Validating": "#0d9488",
    "Rendering": "#8b5cf6",
    "Completed": "#10b981",
    "Needs login": "#f59e0b",
    "Credit limit reached": "#ea580c",
    "Failed": "#ef4444",
}


class ShortsVideoWorker(QThread):
    """Non-blocking background worker for Shorts-only AI scene generation & assembly."""

    stateChanged = Signal(str, str)
    progressChanged = Signal(int)
    completed = Signal(bool, dict)

    def __init__(
        self,
        *,
        run_dir: Path,
        channel_slug: str,
        topic: str,
        script_text: str,
        runtime_overrides: dict[str, Any],
        dry_run: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.run_dir = Path(run_dir)
        self.channel_slug = channel_slug
        self.topic = topic
        self.script_text = script_text
        self.runtime_overrides = dict(runtime_overrides)
        self.dry_run = dry_run

    def run(self):
        stage_progress = {
            "Preparing storyboard": 15,
            "Generating": 45,
            "Downloading or importing": 60,
            "Validating": 75,
            "Rendering": 90,
            "Completed": 100,
        }

        def on_progress(state: str, detail: str) -> None:
            self.stateChanged.emit(state, detail)
            if state in stage_progress:
                self.progressChanged.emit(stage_progress[state])

        try:
            result = render_ai_short(
                self.run_dir,
                self.channel_slug,
                self.topic,
                self.script_text,
                dry_run=self.dry_run,
                progress_callback=on_progress,
                **self.runtime_overrides,
            )
            self.progressChanged.emit(100)
            self.completed.emit(True, result)
        except Exception as error:
            state = "Failed"
            msg = str(error)
            lower = msg.lower()
            if "login" in lower or "verification" in lower:
                state = "Needs login"
            elif "credit" in lower or "budget" in lower:
                state = "Credit limit reached"
            self.stateChanged.emit(state, msg)
            self.completed.emit(False, {"error": msg, "state": state})


class FlowReadinessWorker(QThread):
    """Non-blocking check for Google Flow profile & provider status."""

    ready = Signal(dict)

    def __init__(self, *, probe_browser: bool = False, parent=None):
        super().__init__(parent)
        self.probe_browser = probe_browser

    def run(self):
        try:
            info = flow_browser.check_flow_readiness(probe_browser=self.probe_browser)
        except Exception as error:
            info = {
                "provider": "google-flow",
                "configured": False,
                "state": "unknown",
                "detail": str(error),
            }
        self.ready.emit(info)


class ShortsVideoPanel(QGroupBox):
    """Shorts-only AI Video (Google Flow / Veo) settings and monitoring widget."""

    def __init__(self, parent=None):
        super().__init__("🎬 Shorts AI Video (Google AI Pro / Flow · Shorts Only)", parent)
        self._worker: ShortsVideoWorker | None = None
        self._probe_worker: FlowReadinessWorker | None = None
        self._current_run_dir: Path | None = None
        self._build_ui()
        self._load_settings_into_widgets()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        note = QLabel(
            "Exclusivo para YouTube Shorts (9:16). Vídeos longos nunca usam clipes de IA."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b; font-size: 11px;")
        root.addWidget(note)

        self.enable_cb = QCheckBox("Enable AI video clips for YouTube Shorts (opt-in)")
        self.enable_cb.toggled.connect(self._save_from_ui)
        root.addWidget(self.enable_cb)

        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google Flow (Google AI Pro subscription)", "google-flow")
        self.provider_combo.addItem("Manual Video Import (Local Clips)", "manual-import")
        self.provider_combo.addItem("Gemini Video API (Paid API · Opt-in)", "gemini-api")
        self.provider_combo.currentIndexChanged.connect(self._save_from_ui)
        form.addRow("Video provider:", self.provider_combo)

        self.model_combo = QComboBox()
        for model_name in shorts_settings.VALID_MODELS:
            self.model_combo.addItem(model_name, model_name)
        self.model_combo.currentIndexChanged.connect(self._save_from_ui)
        form.addRow("Video model:", self.model_combo)

        self.quality_combo = QComboBox()
        for quality_name in shorts_settings.VALID_QUALITIES:
            self.quality_combo.addItem(quality_name.capitalize(), quality_name)
        self.quality_combo.currentIndexChanged.connect(self._save_from_ui)
        form.addRow("Preferred quality:", self.quality_combo)

        self.max_credits_short_spin = QDoubleSpinBox()
        self.max_credits_short_spin.setRange(0.0, 10000.0)
        self.max_credits_short_spin.setDecimals(1)
        self.max_credits_short_spin.setSingleStep(10.0)
        self.max_credits_short_spin.valueChanged.connect(self._save_from_ui)
        form.addRow("Max credits per Short:", self.max_credits_short_spin)

        self.max_credits_batch_spin = QDoubleSpinBox()
        self.max_credits_batch_spin.setRange(0.0, 50000.0)
        self.max_credits_batch_spin.setDecimals(1)
        self.max_credits_batch_spin.setSingleStep(20.0)
        self.max_credits_batch_spin.valueChanged.connect(self._save_from_ui)
        form.addRow("Max credits per batch:", self.max_credits_batch_spin)

        self.max_scenes_spin = QSpinBox()
        self.max_scenes_spin.setRange(1, 12)
        self.max_scenes_spin.valueChanged.connect(self._save_from_ui)
        form.addRow("Max generated scenes:", self.max_scenes_spin)

        root.addLayout(form)

        self.fallback_cb = QCheckBox("Enable still-image fallback if clips fail or budget runs out")
        self.fallback_cb.toggled.connect(self._save_from_ui)
        root.addWidget(self.fallback_cb)

        self.paid_api_cb = QCheckBox("Allow paid Gemini Video API (disabled by default)")
        self.paid_api_cb.toggled.connect(self._save_from_ui)
        root.addWidget(self.paid_api_cb)

        conn_row = QHBoxLayout()
        self.flow_status_label = QLabel("Google Flow: not checked")
        self.flow_status_label.setWordWrap(True)
        self.login_btn = QPushButton("Connect Google Flow")
        self.login_btn.clicked.connect(self.connect_google_flow)
        self.check_status_btn = QPushButton("Check Status")
        self.check_status_btn.clicked.connect(self.check_flow_status)
        conn_row.addWidget(self.flow_status_label, 1)
        conn_row.addWidget(self.login_btn)
        conn_row.addWidget(self.check_status_btn)
        root.addLayout(conn_row)

        state_row = QHBoxLayout()
        self.state_label = QLabel("Waiting")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumWidth(180)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        state_row.addWidget(QLabel("Generation state:"))
        state_row.addWidget(self.state_label)
        state_row.addWidget(self.progress_bar, 1)
        root.addLayout(state_row)

        self.clips_table = QTableWidget(0, 4)
        self.clips_table.setHorizontalHeaderLabels(["Scene", "Status", "Duration", "Clip Path"])
        self.clips_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.clips_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.clips_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.clips_table.setMaximumHeight(135)
        root.addWidget(self.clips_table)

        preview_row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview Selected Clip")
        self.preview_btn.clicked.connect(self.preview_selected_clip)
        self.credits_label = QLabel("Batch credits used: 0.0")
        preview_row.addWidget(self.preview_btn)
        preview_row.addWidget(self.credits_label, 1)
        root.addLayout(preview_row)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(80)
        self.log_output.setPlaceholderText("Shorts AI video progress and errors appear here.")
        root.addWidget(self.log_output)

        self.set_generation_state("Waiting")

    def _set_combo_by_data(self, combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_settings_into_widgets(self) -> None:
        active = shorts_settings.load_settings()
        widgets = (
            self.enable_cb,
            self.provider_combo,
            self.model_combo,
            self.quality_combo,
            self.max_credits_short_spin,
            self.max_credits_batch_spin,
            self.max_scenes_spin,
            self.fallback_cb,
            self.paid_api_cb,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.enable_cb.setChecked(bool(active["enabled"]))
            self._set_combo_by_data(self.provider_combo, active["provider"])
            self._set_combo_by_data(self.model_combo, active["model"])
            self._set_combo_by_data(self.quality_combo, active["quality"])
            self.max_credits_short_spin.setValue(float(active["max_credits_per_short"]))
            self.max_credits_batch_spin.setValue(float(active["max_credits_per_batch"]))
            self.max_scenes_spin.setValue(int(active["max_scenes_per_short"]))
            self.fallback_cb.setChecked(bool(active["fallback_to_static"]))
            self.paid_api_cb.setChecked(bool(active["allow_paid_api"]))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

        readiness = flow_browser.check_flow_readiness(probe_browser=False)
        self._apply_flow_readiness(readiness)
        summary = credits.ledger_summary()
        self.credits_label.setText(
            f"Batch credits used: {summary['batch_credits_used']:.1f} / "
            f"{summary['max_credits_per_batch']:.1f}"
        )

    def current_config(self) -> dict[str, Any]:
        enabled = self.enable_cb.isChecked()
        return {
            "enabled": enabled,
            "visual_mode": "ai-video" if enabled else "static",
            "provider": self.provider_combo.currentData() or "google-flow",
            "model": self.model_combo.currentData() or "veo-2-fast",
            "quality": self.quality_combo.currentData() or "fast",
            "max_credits_per_short": float(self.max_credits_short_spin.value()),
            "max_credits_per_batch": float(self.max_credits_batch_spin.value()),
            "max_scenes_per_short": int(self.max_scenes_spin.value()),
            "fallback_to_static": self.fallback_cb.isChecked(),
            "allow_paid_api": self.paid_api_cb.isChecked(),
        }

    def _save_from_ui(self) -> None:
        try:
            shorts_settings.save_settings(self.current_config())
        except Exception as error:
            self.append_log(f"Settings warning: {error}")

    def set_generation_state(self, state: str, detail: str = "") -> None:
        normalized = state if state in GENERATION_STATES else "Failed"
        color = STATE_COLORS.get(normalized, "#64748b")
        self.state_label.setText(normalized)
        self.state_label.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; "
            "border-radius: 4px; padding: 4px 8px;"
        )
        if detail:
            self.append_log(f"[{normalized}] {detail}")

    def append_log(self, line: str) -> None:
        self.log_output.appendPlainText(line)

    def _apply_flow_readiness(self, info: dict[str, Any]) -> None:
        state = info.get("state", "unknown")
        credits_rep = info.get("credits_reported")
        credit_txt = f" · {credits_rep:.1f} credits" if credits_rep is not None else ""
        self.flow_status_label.setText(f"Google Flow: {state}{credit_txt}")

    def connect_google_flow(self) -> None:
        try:
            pid = flow_browser.open_visible_login()
            self.flow_status_label.setText("Google Flow: visible login opened")
            self.append_log(f"Opened visible Google Flow login browser (pid={pid}).")
        except Exception as error:
            QMessageBox.warning(self, "Google Flow", str(error))
            self.append_log(f"Google Flow login error: {error}")

    def check_flow_status(self) -> None:
        if self._probe_worker and self._probe_worker.isRunning():
            return
        self.check_status_btn.setEnabled(False)
        self.flow_status_label.setText("Google Flow: checking...")
        self._probe_worker = FlowReadinessWorker(probe_browser=False, parent=self)
        self._probe_worker.ready.connect(self._on_flow_status_ready)
        self._probe_worker.start()

    def _on_flow_status_ready(self, info: dict[str, Any]) -> None:
        self.check_status_btn.setEnabled(True)
        self._apply_flow_readiness(info)
        summary = credits.ledger_summary()
        self.credits_label.setText(
            f"Batch credits used: {summary['batch_credits_used']:.1f} / "
            f"{summary['max_credits_per_batch']:.1f}"
        )

    def load_run_clips(self, run_dir: Path) -> None:
        """Populate the clip preview table from a Short run directory."""
        self._current_run_dir = Path(run_dir)
        storyboard = load_storyboard(self._current_run_dir)
        self.clips_table.setRowCount(0)
        if storyboard is None:
            return
        for row_idx, scene in enumerate(storyboard.scenes):
            self.clips_table.insertRow(row_idx)
            self.clips_table.setItem(row_idx, 0, QTableWidgetItem(scene.scene_id))
            self.clips_table.setItem(row_idx, 1, QTableWidgetItem(scene.status))
            self.clips_table.setItem(row_idx, 2, QTableWidgetItem(f"{scene.duration_sec:.1f}s"))
            self.clips_table.setItem(row_idx, 3, QTableWidgetItem(scene.output_path))

    def start_short_job(
        self,
        *,
        run_dir: Path,
        channel_slug: str,
        topic: str,
        script_text: str,
        dry_run: bool = False,
    ) -> None:
        """Start Shorts AI generation in a background QThread without blocking the UI."""
        if self._worker and self._worker.isRunning():
            self.append_log("A Shorts AI video job is already running.")
            return
        self._current_run_dir = Path(run_dir)
        cfg = self.current_config()
        overrides = {
            "visual_mode": cfg["visual_mode"],
            "video_provider": cfg["provider"],
            "video_model": cfg["model"],
            "quality": cfg["quality"],
            "max_credits_per_short": cfg["max_credits_per_short"],
            "max_credits_per_batch": cfg["max_credits_per_batch"],
            "max_scenes": cfg["max_scenes_per_short"],
            "fallback_to_static": cfg["fallback_to_static"],
            "allow_paid_api": cfg["allow_paid_api"],
        }
        self.progress_bar.setValue(0)
        self.set_generation_state("Preparing storyboard", topic)
        self._worker = ShortsVideoWorker(
            run_dir=run_dir,
            channel_slug=channel_slug,
            topic=topic,
            script_text=script_text,
            runtime_overrides=overrides,
            dry_run=dry_run,
            parent=self,
        )
        self._worker.stateChanged.connect(self.set_generation_state)
        self._worker.progressChanged.connect(self.progress_bar.setValue)
        self._worker.completed.connect(self._on_job_completed)
        self._worker.start()

    def _on_job_completed(self, ok: bool, payload: dict[str, Any]) -> None:
        if ok:
            self.set_generation_state("Completed", f"Status: {payload.get('status', 'ok')}")
        if self._current_run_dir is not None:
            self.load_run_clips(self._current_run_dir)
        summary = credits.ledger_summary()
        self.credits_label.setText(
            f"Batch credits used: {summary['batch_credits_used']:.1f} / "
            f"{summary['max_credits_per_batch']:.1f}"
        )

    def preview_selected_clip(self) -> None:
        row = self.clips_table.currentRow()
        if row < 0 and self.clips_table.rowCount() > 0:
            row = 0
        if row < 0:
            self.append_log("No generated clips available to preview.")
            return
        item = self.clips_table.item(row, 3)
        clip_path = Path(item.text()) if item and item.text() else None
        if clip_path is None or not clip_path.is_file():
            self.append_log("Selected scene does not have a local clip file yet.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(clip_path.resolve())))
