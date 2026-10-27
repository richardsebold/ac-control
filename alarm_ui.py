from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from alarm_core import AlarmHub, load_config

FONT = "Segoe UI"
STATE_TEXT = {
    "disarmed": ("Desarmado", "#5ad19a"),
    "armed_away": ("Armado", "#6cc7ee"),
    "armed_home": ("Armado em casa", "#6cc7ee"),
    "partial": ("Parcialmente armado", "#f0b84d"),
    "triggered": ("DISPARADO", "#ff6b6b"),
    "unknown": ("Sem informação", "#8b95a3"),
}


def _note(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:#8b95a3;font:10pt '{FONT}'")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setWordWrap(True)
    return lbl


class AlarmPage(QWidget):
    # why: o hub chama on_change numa thread de rede; o sinal leva a atualização para a thread da UI
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.hub = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 14, 0, 0)
        cfg = load_config()
        if cfg is None:
            root.addWidget(_note("Alarme não configurado.\nPreencha o alarm.json."))
            return
        self.hub = AlarmHub(cfg, self.changed.emit)
        try:
            self.hub.start()
        except OSError as e:
            self.hub = None
            root.addWidget(_note(f"Não foi possível escutar na porta {cfg['port']}.\n{e.strerror or e}"))
            return

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel()
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setStyleSheet(f"color:#8b95a3;font:9pt '{FONT}'")
        self.detail.setWordWrap(True)
        root.addStretch()
        root.addWidget(self.status)
        root.addSpacing(4)
        root.addWidget(self.detail)
        root.addSpacing(26)
        self.buttons = []
        for text, fn, accent in (("Armar", self.hub.arm_away, True),
                                 ("Armar em casa", self.hub.arm_home, False),
                                 ("Desarmar", self.hub.disarm, False)):
            b = QPushButton(text)
            b.setFixedHeight(46)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bg, fg = ("#6cc7ee", "#08202d") if accent else ("rgba(255,255,255,14)", "#e6e9ee")
            b.setStyleSheet(f"QPushButton{{background:{bg};color:{fg};border:none;border-radius:23px;"
                            f"font:600 11pt '{FONT}'}}"
                            "QPushButton:hover{background:rgba(255,255,255,30)}"
                            "QPushButton:disabled{background:rgba(255,255,255,8);color:#5a626e}")
            b.clicked.connect(lambda _, f=fn: self._send(f))
            root.addWidget(b)
            root.addSpacing(10)
            self.buttons.append(b)
        root.addStretch()
        self.changed.connect(self._refresh)
        self._refresh()

    def _send(self, fn):
        if not fn():
            self.detail.setText("Central desconectada: comando não enviado")

    def _refresh(self):
        h = self.hub
        text, col = STATE_TEXT[h.state if h.connected else "unknown"]
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{col};font:700 20pt '{FONT}'")
        if h.connected:
            self.detail.setText(h.model or "Central conectada")
        else:
            self.detail.setText("Aguardando a central conectar…")
        for b in self.buttons:
            b.setEnabled(h.connected)

    def shutdown(self):
        if self.hub:
            self.hub.stop()
