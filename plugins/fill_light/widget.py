"""Native Qt controls for claw_ctrl fill-light protocol V1.1."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from cangui.i18n import _
from cangui.plugin_ui import FlowLayout
from . import protocol as P


class FillLightPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._status = None
        self._last_rx = None
        self._pending_level = None
        self._sent_at = None
        self._message_key = 'FillLight.Ready'
        self._message_args = {}
        self._active = False
        try:
            level = int(ctx.get_setting('fill_light.level', 500))
            last_on = int(ctx.get_setting('fill_light.last_on', 500))
        except (TypeError, ValueError, OverflowError):
            level = last_on = 500
        self._last_on = max(1, min(P.MAX_LEVEL, last_on))
        self._texts = []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._apply)
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._refresh_status)

        root = QVBoxLayout(self)
        hint = self._label('FillLight.Hint')
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._control = QGroupBox(_('FillLight.Control'))
        layout = QVBoxLayout(self._control)
        layout.addWidget(self._label('FillLight.Target'))
        row = QHBoxLayout()
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, P.MAX_LEVEL)
        self._slider.setValue(max(0, min(P.MAX_LEVEL, level)))
        self._percent = QDoubleSpinBox()
        self._percent.setDecimals(1)
        self._percent.setRange(0, 100)
        self._percent.setSingleStep(1)
        self._percent.setSuffix(' %')
        self._percent.setValue(self._slider.value() / 10)
        row.addWidget(self._slider, 1)
        row.addWidget(self._percent)
        layout.addLayout(row)
        buttons = FlowLayout()
        self._off = self._button('FillLight.Off', lambda: self._set_and_send(0))
        self._on = self._button('FillLight.On', lambda: self._set_and_send(self._last_on))
        self._apply_btn = self._button('FillLight.Apply', self._apply)
        self._send_buttons = [self._off, self._on, self._apply_btn]
        buttons.addWidget(self._off)
        buttons.addWidget(self._on)
        self._presets = []
        for percent in (25, 50, 75, 100):
            button = QPushButton(_('FillLight.Preset').format(value=percent))
            button.clicked.connect(lambda checked=False, value=percent * 10: self._set_and_send(value))
            self._presets.append((button, percent))
            self._send_buttons.append(button)
            buttons.addWidget(button)
        buttons.addWidget(self._apply_btn)
        layout.addLayout(buttons)
        self._auto = QCheckBox(_('FillLight.Auto'))
        self._texts.append((self._auto, 'FillLight.Auto'))
        self._auto.setChecked(bool(ctx.get_setting('fill_light.auto', False)))
        layout.addWidget(self._auto)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        root.addWidget(self._control)

        self._board = QGroupBox(_('FillLight.Board'))
        form = QFormLayout(self._board)
        self._connection = QLabel()
        self._connection.setWordWrap(True)
        self._accepted = QLabel()
        self._motor = QLabel()
        self._uptime = QLabel()
        for key, widget in (('Connection', self._connection), ('Accepted', self._accepted),
                            ('Motor', self._motor), ('Uptime', self._uptime)):
            form.addRow(self._label(f'FillLight.{key}'), widget)
        root.addWidget(self._board)
        note = self._label('FillLight.Note')
        note.setWordWrap(True)
        root.addWidget(note)
        root.addStretch()

        self._slider.valueChanged.connect(self._on_level_changed)
        self._percent.valueChanged.connect(lambda value: self._slider.setValue(round(value * 10)))
        self._auto.toggled.connect(self._on_auto_changed)
        self._refresh_status()

    def _label(self, key):
        widget = QLabel(_(key))
        self._texts.append((widget, key))
        return widget

    def _button(self, key, callback):
        button = QPushButton(_(key))
        button.clicked.connect(callback)
        self._texts.append((button, key))
        return button

    def _on_level_changed(self, level):
        with QSignalBlocker(self._percent):
            self._percent.setValue(level / 10)
        self._ctx.set_setting('fill_light.level', level)
        if level:
            self._last_on = level
            self._ctx.set_setting('fill_light.last_on', level)
        if self._active and self._auto.isChecked() and self._ready():
            self._debounce.start()

    def _on_auto_changed(self, checked):
        self._ctx.set_setting('fill_light.auto', checked)
        if not checked:
            self._debounce.stop()

    def _ready(self):
        return (self._ctx.is_connected() and self._ctx.is_fd_mode()
                and self._ctx.get_bitrate() == P.BITRATE)

    def _set_message(self, key, **kwargs):
        self._message_key, self._message_args = key, kwargs
        self._message.setText(_(key).format(**kwargs))

    def _set_and_send(self, level):
        self._slider.setValue(level)
        self._apply()

    def _apply(self):
        self._debounce.stop()
        if not self._active:
            return
        error = ('FillLight.Disconnected' if not self._ctx.is_connected() else
                 'FillLight.NeedFd' if not self._ctx.is_fd_mode() else
                 'FillLight.NeedBitrate' if self._ctx.get_bitrate() != P.BITRATE else None)
        if error:
            self._set_message(error)
            self._ctx.status_message(_(error), 4000)
            return
        level = self._slider.value()
        self._ctx.send_frame(P.build_light_control(level))
        self._pending_level = level
        self._sent_at = time.monotonic()
        self._set_message('FillLight.Waiting', value=level / 10)

    def on_frames(self, frames):
        if not self._active or not self._ctx.is_connected():
            return
        for frame in frames:
            status = P.parse_status(frame)
            if status is None:
                continue
            self._status, self._last_rx = status, time.monotonic()
            if self._pending_level is not None:
                if status.level == self._pending_level:
                    self._pending_level = self._sent_at = None
                    self._set_message('FillLight.Matched', value=status.level / 10)
                else:
                    self._set_message('FillLight.Mismatch', value=status.level / 10)
        self._refresh_status()

    def _refresh_status(self):
        now = time.monotonic()
        age = None if self._last_rx is None else now - self._last_rx
        connected = self._ctx.is_connected()
        key = ('FillLight.Disconnected' if not connected else
               'FillLight.Unknown' if age is None else
               'FillLight.Offline' if age >= P.HEARTBEAT_TIMEOUT else 'FillLight.Online')
        self._connection.setText(_(key).format(age=age))
        fresh = connected and age is not None and age < P.HEARTBEAT_TIMEOUT
        if fresh:
            self._accepted.setText(f'{self._status.level / 10:.1f}%')
            self._motor.setText(_(f'FillLight.Motor.{self._status.motor_state}'))
            self._uptime.setText(_('FillLight.UptimeValue').format(seconds=self._status.uptime_ms / 1000))
        else:
            for label in (self._accepted, self._motor, self._uptime):
                label.setText(_('FillLight.NoData'))
        if self._pending_level is not None and now - self._sent_at >= P.HEARTBEAT_TIMEOUT:
            self._pending_level = self._sent_at = None
            self._set_message('FillLight.Timeout')
        for button in self._send_buttons:
            button.setEnabled(self._ready())

    def on_activated(self):
        self._active = True
        self._poll.start()
        self._refresh_status()

    def _reset(self):
        self._debounce.stop()
        self._status = self._last_rx = None
        self._pending_level = self._sent_at = None
        self._set_message('FillLight.Ready')
        self._refresh_status()

    def on_connect(self):
        self._reset()

    def on_disconnect(self):
        self._reset()

    def on_deactivating(self):
        self._active = False
        self._debounce.stop()
        self._poll.stop()
        self._pending_level = self._sent_at = None

    def refresh_language(self):
        for widget, key in self._texts:
            widget.setText(_(key))
        for button, percent in self._presets:
            button.setText(_('FillLight.Preset').format(value=percent))
        self._control.setTitle(_('FillLight.Control'))
        self._board.setTitle(_('FillLight.Board'))
        self._set_message(self._message_key, **self._message_args)
        self._refresh_status()
