import threading

import cv2
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from cameras_ui import load_cameras
from watch_core import PERSON, VEHICLE, load_zones, save_zones
from watch_runner import grab_frame

FONT = "Segoe UI"
GREEN, AMBER = QColor("#5ad19a"), QColor("#f0b84d")


class Canvas(QWidget):
    """Mostra o quadro da câmera e recebe os cliques que formam o polígono."""
    point_added = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 360)
        self.image = None
        self.zones, self.selected, self.drawing = [], -1, None
        self.message = "Carregando imagem…"

    def _rect(self):
        if self.image is None:
            return QRectF(0, 0, self.width(), self.height())
        s = min(self.width() / self.image.width(), self.height() / self.image.height())
        w, h = self.image.width() * s, self.image.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _poly(self, pts, r):
        return QPolygonF([QPointF(r.x() + x * r.width(), r.y() + y * r.height()) for x, y in pts])

    def mousePressEvent(self, e):
        if self.drawing is None or self.image is None:
            return
        if e.button() == Qt.MouseButton.RightButton:
            if self.drawing:
                self.drawing.pop()
        else:
            r = self._rect()
            x, y = (e.position().x() - r.x()) / r.width(), (e.position().y() - r.y()) / r.height()
            if 0 <= x <= 1 and 0 <= y <= 1:
                self.drawing.append([round(x, 4), round(y, 4)])
        self.update()
        self.point_added.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b0e13"))
        r = self._rect()
        if self.image is None:
            p.setPen(QColor("#8b95a3"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        p.drawImage(r, self.image)
        for i, z in enumerate(self.zones):
            col = GREEN if i == self.selected else AMBER
            poly = self._poly(z["points"], r)
            p.setPen(QPen(col, 2))
            fill = QColor(col)
            fill.setAlpha(55)
            p.setBrush(fill)
            p.drawPolygon(poly)
            p.setPen(col)
            p.drawText(poly.boundingRect().topLeft() + QPointF(4, 14), z["name"])
        if self.drawing:
            pts = self._poly(self.drawing, r)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(pts)
            for pt in pts:
                p.drawEllipse(pt, 3, 3)


class ZoneEditor(QDialog):
    frame_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zonas do vigia")
        self.setStyleSheet(
            f"QDialog{{background:#0f141c}}QLabel,QCheckBox{{color:#e6e9ee;font:10pt '{FONT}'}}"
            "QPushButton{background:rgba(255,255,255,18);color:#e6e9ee;border:none;border-radius:8px;padding:7px 12px}"
            "QPushButton:hover{background:rgba(255,255,255,32)}QPushButton:disabled{color:#5a626e}"
            "QLineEdit,QSpinBox,QComboBox,QListWidget{background:#182636;color:#e6e9ee;border:1px solid #2a3a4d;"
            "border-radius:6px;padding:4px}QListWidget::item:selected{background:#6cc7ee;color:#08202d}")
        self.cams = load_cameras()
        self.cfg = load_zones()
        self.cfg.setdefault("enabled", True)
        self.key = None
        self.frame_ready.connect(self._show_frame)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.combo = QComboBox()
        for i, c in enumerate(self.cams, 1):
            self.combo.addItem(c["name"], f"cam{i}")
        reload_btn = QPushButton("Atualizar imagem")
        reload_btn.clicked.connect(self._load_image)
        top.addWidget(self.combo)
        top.addWidget(reload_btn)
        top.addStretch()
        root.addLayout(top)

        body = QHBoxLayout()
        self.canvas = Canvas()
        self.canvas.point_added.connect(self._sync_buttons)
        body.addWidget(self.canvas, 1)
        side = QVBoxLayout()
        self.listw = QListWidget()
        self.listw.setFixedWidth(210)
        self.listw.currentRowChanged.connect(self._select)
        side.addWidget(self.listw)
        self.new_btn = QPushButton("Nova zona")
        self.new_btn.clicked.connect(self._new)
        self.done_btn = QPushButton("Concluir zona")
        self.done_btn.clicked.connect(self._finish)
        self.del_btn = QPushButton("Excluir zona")
        self.del_btn.clicked.connect(self._delete)
        for b in (self.new_btn, self.done_btn, self.del_btn):
            side.addWidget(b)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nome da zona")
        self.name_edit.textEdited.connect(self._edit_name)
        self.secs = QSpinBox()
        self.secs.setRange(1, 600)
        self.secs.setSuffix(" s parado")
        self.secs.valueChanged.connect(self._edit_secs)
        self.chk_car = QCheckBox("Veículos")
        self.chk_person = QCheckBox("Pessoas")
        for c in (self.chk_car, self.chk_person):
            c.toggled.connect(self._edit_kinds)
        for w in (self.name_edit, self.secs, self.chk_car, self.chk_person):
            side.addWidget(w)
        side.addStretch()
        self.hint = QLabel("Nova zona: clique na imagem para marcar os cantos\n(botão direito desfaz o último).")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:#8b95a3;font:9pt '{FONT}'")
        side.addWidget(self.hint)
        body.addLayout(side)
        root.addLayout(body)

        bottom = QHBoxLayout()
        bottom.addStretch()
        save = QPushButton("Salvar")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        root.addLayout(bottom)

        self.combo.currentIndexChanged.connect(self._switch)
        if self.cams:
            self._switch()
        else:
            self.canvas.message = "Nenhuma câmera configurada."

    def _zones(self):
        return self.cfg["cameras"].setdefault(self.key, {"zones": []})["zones"]

    def _switch(self):
        self.key = self.combo.currentData()
        self.canvas.zones = self._zones()
        self.canvas.drawing = None
        self._fill_list(-1)
        self._load_image()

    def _load_image(self):
        self.canvas.image = None
        self.canvas.message = "Carregando imagem…"
        self.canvas.update()
        key = self.key

        def work():
            frame = grab_frame(f"{key}")
            self.frame_ready.emit((key, frame))
        threading.Thread(target=work, daemon=True).start()

    def _show_frame(self, payload):
        key, frame = payload
        if key != self.key:
            return
        if frame is None:
            self.canvas.message = "Não foi possível abrir a câmera (go2rtc rodando?)."
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            self.canvas.image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.canvas.update()

    def _fill_list(self, select):
        self.listw.blockSignals(True)
        self.listw.clear()
        self.listw.addItems([z["name"] for z in self._zones()])
        self.listw.blockSignals(False)
        self.listw.setCurrentRow(select)
        self._select(select)

    def _select(self, row):
        zs = self._zones()
        self.canvas.selected = row
        z = zs[row] if 0 <= row < len(zs) else None
        for w in (self.name_edit, self.secs, self.chk_car, self.chk_person):
            w.blockSignals(True)
            w.setEnabled(z is not None)
        if z:
            self.name_edit.setText(z["name"])
            self.secs.setValue(z.get("seconds", 10))
            self.chk_car.setChecked(VEHICLE in z.get("kinds", [VEHICLE]))
            self.chk_person.setChecked(PERSON in z.get("kinds", [VEHICLE]))
        for w in (self.name_edit, self.secs, self.chk_car, self.chk_person):
            w.blockSignals(False)
        self._sync_buttons()
        self.canvas.update()

    def _sync_buttons(self):
        drawing = self.canvas.drawing is not None
        self.new_btn.setEnabled(not drawing)
        self.done_btn.setEnabled(drawing and len(self.canvas.drawing) >= 3)
        self.del_btn.setEnabled(not drawing and self.listw.currentRow() >= 0)
        self.listw.setEnabled(not drawing)

    def _new(self):
        self.canvas.drawing = []
        self.canvas.selected = -1
        self._sync_buttons()
        self.canvas.update()

    def _finish(self):
        zs = self._zones()
        zs.append({"name": f"Zona {len(zs) + 1}", "points": self.canvas.drawing,
                   "kinds": [VEHICLE], "seconds": 10})
        self.canvas.drawing = None
        self._fill_list(len(zs) - 1)

    def _delete(self):
        row = self.listw.currentRow()
        if row >= 0:
            del self._zones()[row]
            self._fill_list(-1)

    def _current(self):
        zs = self._zones()
        row = self.listw.currentRow()
        return zs[row] if 0 <= row < len(zs) else None

    def _edit_name(self, text):
        z = self._current()
        if z and text.strip():
            z["name"] = text.strip()
            self.listw.currentItem().setText(z["name"])
            self.canvas.update()

    def _edit_secs(self, v):
        z = self._current()
        if z:
            z["seconds"] = v

    def _edit_kinds(self):
        z = self._current()
        if z:
            kinds = [k for k, c in ((VEHICLE, self.chk_car), (PERSON, self.chk_person)) if c.isChecked()]
            z["kinds"] = kinds or [VEHICLE]

    def _save(self):
        # invariant: câmera sem zonas não fica no arquivo, para o vigia não abrir stream à toa
        self.cfg["cameras"] = {k: v for k, v in self.cfg["cameras"].items() if v.get("zones")}
        save_zones(self.cfg)
        self.accept()
