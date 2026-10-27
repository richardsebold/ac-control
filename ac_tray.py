import math
import os
import sys
import threading
import time

from PyQt6.QtCore import QLockFile, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetricsF, QIcon, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PyQt6.QtWidgets import (QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMenu,
                             QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget)

from ac_core import AC, BASE, MODES, TEMP_MAX, TEMP_MIN
from alarm_ui import AlarmPage
from cameras_ui import CamPage

BLUE = QColor("#4cc2ff")
MODE_LABEL = {"cool": "Resfriar", "dry": "Seco", "fan_only": "Ventilar"}
FAN_LABEL = {"auto": "Auto", "min": "Mínima", "low": "Baixa", "medium": "Média",
             "high": "Alta", "max": "Máxima"}
FAN_FLOW = {"auto": 0.6, "min": 0.3, "low": 0.45, "medium": 0.65, "high": 0.85, "max": 1.0}
FLOW_RGB = {"cool": (150, 215, 255), "dry": (170, 235, 205), "fan_only": (235, 235, 235)}
FONT = "Segoe UI"


# ---------- ícones desenhados em vetor ----------

def _pen(col, w=1.6):
    return QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def icon_snow(p, r, col):
    c, R = r.center(), r.width() / 2
    p.setPen(_pen(col))
    for k in range(3):
        a = math.radians(60 * k + 90)
        d = QPointF(math.cos(a) * R, math.sin(a) * R)
        p.drawLine(c - d, c + d)
        n = QPointF(-d.y(), d.x()) * 0.2
        for s in (-1, 1):
            tip = c + d * (0.62 * s)
            back = d * (-0.2 * s)
            p.drawLine(tip, tip + back + n)
            p.drawLine(tip, tip + back - n)


def icon_fan(p, r, col, angle=0.0):
    c, R = r.center(), r.width() / 2
    p.setPen(_pen(col, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.save()
    p.translate(c)
    p.rotate(angle)
    for k in range(3):
        p.save()
        p.rotate(120 * k)
        path = QPainterPath()
        path.moveTo(0, 0)
        path.cubicTo(R * 0.95, -R * 0.15, R * 0.9, -R * 1.0, R * 0.1, -R * 0.95)
        path.cubicTo(-R * 0.25, -R * 0.6, -R * 0.1, -R * 0.3, 0, 0)
        p.drawPath(path)
        p.restore()
    p.drawEllipse(QPointF(0, 0), 1.6, 1.6)
    p.restore()


def icon_moon(p, r, col):
    big, cut = QPainterPath(), QPainterPath()
    big.addEllipse(r)
    cut.addEllipse(r.translated(r.width() * 0.38, -r.height() * 0.22))
    p.setPen(_pen(col, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(big.subtracted(cut))


def icon_swing(p, r, col):
    p.setPen(_pen(col, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for k in range(3):
        y = r.top() + r.height() * (0.2 + 0.3 * k)
        path = QPainterPath(QPointF(r.left(), y))
        for i in range(1, 21):
            path.lineTo(r.left() + r.width() * i / 20, y + 2.2 * math.sin(i / 20 * 3 * math.pi))
        p.drawPath(path)


def icon_drop(p, r, col):
    cx, top, bot = r.center().x(), r.top(), r.bottom()
    w = r.width() * 0.36
    path = QPainterPath(QPointF(cx, top))
    path.cubicTo(cx + w * 0.4, top + r.height() * 0.35, cx + w * 1.4, bot - r.height() * 0.45, cx, bot)
    path.cubicTo(cx - w * 1.4, bot - r.height() * 0.45, cx - w * 0.4, top + r.height() * 0.35, cx, top)
    p.setPen(_pen(col, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def icon_monitor(p, r, col):
    p.setPen(_pen(col, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    screen = QRectF(r.left(), r.top() + 1, r.width(), r.height() * 0.68)
    p.drawRoundedRect(screen, 2.5, 2.5)
    p.drawLine(QPointF(r.center().x(), screen.bottom()), QPointF(r.center().x(), r.bottom() - 1))
    p.drawLine(QPointF(r.left() + r.width() * 0.28, r.bottom() - 1),
               QPointF(r.right() - r.width() * 0.28, r.bottom() - 1))


def icon_bolt(p, r, col):
    pts = [(0.62, 0.0), (0.18, 0.56), (0.48, 0.56), (0.36, 1.0), (0.84, 0.40), (0.54, 0.40)]
    poly = QPolygonF([QPointF(r.left() + x * r.width(), r.top() + y * r.height()) for x, y in pts])
    p.setPen(_pen(col, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(poly)


MODE_ICON = {"cool": icon_snow, "dry": icon_drop, "fan_only": icon_fan}


# ---------- controle (envio em segundo plano) ----------

class Controller(QObject):
    busy_changed = pyqtSignal(bool)
    message = pyqtSignal(str)
    redo = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.ac = AC()
        self.busy = False
        self._dirty = False
        self.redo.connect(self.apply_soon)

    def power(self):
        if not self.busy:
            self._start(lambda: self.ac.power(not self.ac.on))

    def apply_soon(self):
        if not self.ac.on:
            return
        if self.busy:
            self._dirty = True
        else:
            self._start(self.ac.apply)

    def _start(self, fn):
        self.busy = True
        self.busy_changed.emit(True)
        threading.Thread(target=self._work, args=(fn,), daemon=True).start()

    def _work(self, fn):
        msg = ""
        try:
            fn()
            self.ac.save()
        except Exception as e:
            msg = f"Erro: {e}"
        self.busy = False
        redo, self._dirty = self._dirty, False
        self.message.emit(msg)
        self.busy_changed.emit(False)
        if redo and not msg:
            self.redo.emit()


# ---------- widgets ----------

class TempSlider(QWidget):
    moved = pyqtSignal(int)
    released = pyqtSignal()
    R = 14

    def __init__(self, value):
        super().__init__()
        self.value, self.lit = value, False
        self.setFixedHeight(40)
        self.setMinimumWidth(180)

    def set_value(self, v, lit):
        self.value, self.lit = max(TEMP_MIN, min(TEMP_MAX, v)), lit
        self.update()

    def _x(self):
        return self.R + (self.value - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * (self.width() - 2 * self.R)

    def _from_x(self, x):
        frac = (x - self.R) / max(1, self.width() - 2 * self.R)
        self.value = round(TEMP_MIN + max(0, min(1, frac)) * (TEMP_MAX - TEMP_MIN))
        self.moved.emit(self.value)
        self.update()

    def mousePressEvent(self, e):
        self._from_x(e.position().x())

    def mouseMoveEvent(self, e):
        self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self.released.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy, x = self.height() / 2, self._x()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(0, cy - 3, self.width(), 6), 3, 3)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, QColor("#2f6bff") if self.lit else QColor("#33415a"))
        g.setColorAt(1, QColor("#4cc2ff") if self.lit else QColor("#4a5a78"))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(0, cy - 3, x, 6), 3, 3)
        if self.lit:
            p.setBrush(QColor(76, 194, 255, 40))
            p.drawEllipse(QPointF(x, cy), self.R + 5, self.R + 5)
        p.setBrush(QColor("#f4f7fb") if self.lit else QColor("#8b95a3"))
        p.drawEllipse(QPointF(x, cy), self.R, self.R)


class ACArt(QWidget):
    """Split desenhado que reflete o estado: painel, vento, aleta e oscilação."""

    def __init__(self, ac):
        super().__init__()
        self.ac = ac
        self.setFixedHeight(176)
        self.t0 = time.monotonic()
        self.timer = QTimer(self, interval=33, timeout=self.update)

    def start(self):
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def paintEvent(self, _):
        ac, st = self.ac, self.ac.state
        t = time.monotonic() - self.t0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        body = QRectF(w * 0.13, 10, w * 0.74, 76)
        slot_y = body.bottom() - 15
        flow = 1.0 if st.turbo else FAN_FLOW[st.fan]
        r, g, b = FLOW_RGB[st.mode] if not st.turbo else (120, 220, 255)

        if ac.on:
            sway = math.sin(t * 1.7) * 0.38 if st.swing else 0.0
            n = 17
            for i in range(n):
                f = (i / (n - 1)) * 2 - 1
                ang = f * 0.5 + sway
                x0 = body.left() + 22 + (body.width() - 44) * (i / (n - 1))
                y0 = slot_y + 8
                length = 52 + 56 * flow
                end = QPointF(x0 + math.sin(ang) * length, y0 + math.cos(ang) * length)
                grad = QLinearGradient(QPointF(x0, y0), end)
                grad.setColorAt(0.0, QColor(r, g, b, 0))
                grad.setColorAt(0.25, QColor(r, g, b, int(120 * flow + 25)))
                grad.setColorAt(1.0, QColor(r, g, b, 0))
                pen = QPen(QBrush(grad), 1.6, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap)
                pen.setDashPattern([3.0, 5.5 + 3 * (1 - flow)])
                pen.setDashOffset(-t * (5 + 14 * flow) - i * 0.7)
                p.setPen(pen)
                p.drawLine(QPointF(x0, y0), end)

        shade = 1.0 if ac.on else 0.55
        grad = QLinearGradient(0, body.top(), 0, body.bottom())
        grad.setColorAt(0, QColor.fromRgbF(1 * shade, 1 * shade, 1 * shade))
        grad.setColorAt(1, QColor.fromRgbF(0.84 * shade, 0.86 * shade, 0.89 * shade))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(body, 18, 18)
        p.setBrush(QColor("#14161b"))
        slot = QRectF(body.left() + 12, slot_y, body.width() - 24, 7)
        p.drawRoundedRect(slot, 3.5, 3.5)
        if ac.on:
            # aleta: abre mais ou menos conforme a oscilação
            open_f = 0.5 + 0.5 * math.sin(t * 2.2) if st.swing else 0.4
            p.setBrush(QColor(236, 240, 245))
            p.drawRoundedRect(QRectF(slot.left() + 4, slot.bottom() - 1, slot.width() - 8, 2.5 + 6 * open_f),
                              1.5, 1.5)

        show_display = ac.on and not st.light_off
        if show_display:
            col = QColor(r, g, b)
            p.setBrush(col)
            p.drawEllipse(QPointF(body.left() + 24, body.top() + 22), 2, 2)
            p.setPen(col)
            f = QFont(FONT, 15, QFont.Weight.DemiBold)
            p.setFont(f)
            p.drawText(QRectF(body.right() - 82, body.top() + 10, 64, 26),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(st.temp))
            if st.sleep:
                icon_moon(p, QRectF(body.right() - 108, body.top() + 16, 13, 13), col)


class Tile(QWidget):
    clicked = pyqtSignal()

    def __init__(self, title, icon, inline=False):
        super().__init__()
        self.title, self.icon, self.inline = title, icon, inline
        self.value, self.active = "", False
        self.setFixedHeight(54 if inline else 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, value, active=False, icon=None):
        self.value, self.active = value, active
        if icon:
            self.icon = icon
        self.update()

    def mouseReleaseEvent(self, _):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(QColor(76, 194, 255, 34) if self.active else QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(76, 194, 255, 120) if self.active else QColor(255, 255, 255, 22), 1))
        p.drawRoundedRect(rect, 16, 16)
        fg = BLUE if self.active else QColor(205, 212, 222)
        dim = QColor(140, 150, 165)
        if self.inline:
            label = f"{self.title} · {self.value}"
            f = QFont(FONT, 10, QFont.Weight.DemiBold)
            tw = QFontMetricsF(f).horizontalAdvance(label)
            x = (self.width() - (22 + 10 + tw)) / 2
            self.icon(p, QRectF(x, self.height() / 2 - 11, 22, 22), fg)
            p.setPen(fg)
            p.setFont(f)
            p.drawText(QRectF(x + 32, 0, tw + 6, self.height()), Qt.AlignmentFlag.AlignVCenter, label)
            return
        self.icon(p, QRectF(14, 13, 20, 20), fg)
        p.setPen(dim)
        p.setFont(QFont(FONT, 8))
        p.drawText(QRectF(14, 40, self.width() - 16, 16), Qt.AlignmentFlag.AlignLeft, self.title)
        p.setPen(fg if self.active else QColor("white"))
        p.setFont(QFont(FONT, 9, QFont.Weight.DemiBold))
        p.drawText(QRectF(14, 56, self.width() - 16, 20), Qt.AlignmentFlag.AlignLeft, self.value)


class Spinner(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.angle = 0
        self.active = False
        self.timer = QTimer(self, interval=30, timeout=self._tick)

    def set_active(self, on):
        self.active = on
        self.timer.start() if on else self.timer.stop()
        self.update()

    def _tick(self):
        self.angle = (self.angle + 24) % 360
        self.update()

    def paintEvent(self, _):
        if not self.active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#9aa0aa"), 2))
        p.drawArc(QRectF(2, 2, 12, 12), -self.angle * 16, 260 * 16)


class Popup(QWidget):
    def __init__(self, ctl):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.ctl, self.ac = ctl, ctl.ac
        self.hidden_at = 0.0
        self.setFixedWidth(400)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(0)
        outer.addLayout(self._tab_bar())
        self.clima = QWidget()
        root = QVBoxLayout(self.clima)
        root.setContentsMargins(0, 16, 0, 0)
        root.setSpacing(0)
        outer.addWidget(self.clima)
        self.cams = CamPage()
        self.cams.setVisible(False)
        outer.addWidget(self.cams)
        self.alarm = AlarmPage()
        self.alarm.setVisible(False)
        outer.addWidget(self.alarm)
        self.tab = 0

        head = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(1)
        title = QLabel("Quarto")
        title.setStyleSheet(f"color:white;font:700 14pt '{FONT}'")
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color:#8b95a3;font:9pt '{FONT}'")
        names.addWidget(title)
        names.addWidget(self.sub)
        head.addLayout(names)
        head.addStretch()
        self.power_btn = QPushButton("⏻")
        self.power_btn.setFixedSize(54, 54)
        self.power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.power_btn.clicked.connect(ctl.power)
        self.glow = QGraphicsDropShadowEffect(blurRadius=26)
        self.glow.setOffset(0, 0)
        self.glow.setColor(BLUE)
        self.power_btn.setGraphicsEffect(self.glow)
        head.addWidget(self.power_btn)
        root.addLayout(head)

        self.art = ACArt(self.ac)
        root.addWidget(self.art)

        self.big = QLabel()
        root.addWidget(self.big)
        root.addSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(12)
        minus, plus = self._round_btn("−"), self._round_btn("+")
        minus.clicked.connect(lambda: self._step(-1))
        plus.clicked.connect(lambda: self._step(1))
        self.slider = TempSlider(self.ac.state.temp)
        self.slider.moved.connect(self._moved)
        self.slider.released.connect(ctl.apply_soon)
        row.addWidget(minus)
        row.addWidget(self.slider, 1)
        row.addWidget(plus)
        root.addLayout(row)

        scale = QHBoxLayout()
        scale.setContentsMargins(60, 0, 60, 12)
        for text, align in ((f"{TEMP_MIN}°", Qt.AlignmentFlag.AlignLeft),
                            (f"{TEMP_MAX}°", Qt.AlignmentFlag.AlignRight)):
            lab = QLabel(text)
            lab.setStyleSheet(f"color:#6f7885;font:8pt '{FONT}'")
            lab.setAlignment(align)
            scale.addWidget(lab)
        root.addLayout(scale)

        self.tiles = {
            "mode": Tile("Modo", icon_snow), "fan": Tile("Ventilação", icon_fan),
            "sleep": Tile("Dormir", icon_moon), "swing": Tile("Oscilação", icon_swing),
            "light_off": Tile("Visor", icon_monitor, inline=True),
            "turbo": Tile("Turbo", icon_bolt, inline=True),
        }
        self.tiles["mode"].clicked.connect(self._next_mode)
        self.tiles["fan"].clicked.connect(self._next_fan)
        self.tiles["turbo"].clicked.connect(lambda: self._act(self.ac.toggle_turbo))
        for flag in ("sleep", "swing", "light_off"):
            self.tiles[flag].clicked.connect(lambda f=flag: self._act(lambda: self.ac.toggle(f)))
        top = QHBoxLayout()
        top.setSpacing(8)
        for n in ("mode", "fan", "sleep", "swing"):
            top.addWidget(self.tiles[n])
        root.addLayout(top)
        root.addSpacing(8)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.tiles["light_off"])
        bottom.addWidget(self.tiles["turbo"])
        root.addLayout(bottom)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 14, 0, 0)
        self.spin = Spinner()
        self.status = QLabel()
        self.status.setStyleSheet(f"color:#8b95a3;font:9pt '{FONT}'")
        sync = QPushButton("↻")
        sync.setFixedSize(34, 34)
        sync.setCursor(Qt.CursorShape.PointingHandCursor)
        sync.setToolTip("Corrigir estado: o app não sabe se o ar foi ligado/desligado pelo controle.\n"
                        "Inverte o estado que ele acha (nada é enviado).")
        sync.setStyleSheet("QPushButton{background:rgba(255,255,255,12);color:#b4b8c0;"
                           "border:1px solid rgba(255,255,255,26);border-radius:17px;font:13pt 'Segoe UI'}"
                           "QPushButton:hover{color:white;background:rgba(255,255,255,26)}")
        sync.clicked.connect(self._sync)
        foot.addWidget(self.spin)
        foot.addWidget(self.status, 1)
        foot.addWidget(sync)
        root.addLayout(foot)

        ctl.busy_changed.connect(self._busy)
        ctl.message.connect(lambda m: self.refresh(m))
        self.refresh()
        # invariant: a aba de câmeras tem sempre a mesma altura da aba Clima
        self.cams.setFixedHeight(self.clima.sizeHint().height())
        self.alarm.setFixedHeight(self.clima.sizeHint().height())

    def _tab_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.tab_btns = []
        for i, name in enumerate(("Clima", "Câmeras", "Alarme")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setFixedHeight(38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:rgba(255,255,255,12);color:#b4b8c0;border:none;"
                            "border-radius:19px;font:600 10pt 'Segoe UI'}"
                            "QPushButton:checked{background:#6cc7ee;color:#08202d}"
                            "QPushButton:hover:!checked{background:rgba(255,255,255,24)}")
            b.clicked.connect(lambda _, n=i: self._set_tab(n))
            bar.addWidget(b)
            self.tab_btns.append(b)
        return bar

    def _set_tab(self, i):
        self.tab = i
        for n, b in enumerate(self.tab_btns):
            b.setChecked(n == i)
        self.clima.setVisible(i == 0)
        self.cams.setVisible(i == 1)
        self.alarm.setVisible(i == 2)
        self._sync_streams()
        self.adjustSize()
        self._anchor()

    def _sync_streams(self):
        # why: vídeo e animação só rodam com o pop-up aberto e a aba correspondente à vista
        shown = self.isVisible()
        (self.art.start if shown and self.tab == 0 else self.art.stop)()
        (self.cams.start if shown and self.tab == 1 else self.cams.stop)()

    def _anchor(self):
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 12, area.bottom() - self.height() - 12)

    @staticmethod
    def _round_btn(text):
        b = QPushButton(text)
        b.setFixedSize(40, 40)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet("QPushButton{background:rgba(255,255,255,12);color:#cdd4de;"
                        "border:1px solid rgba(255,255,255,26);border-radius:20px;font:16pt 'Segoe UI'}"
                        "QPushButton:hover{background:rgba(255,255,255,26)}")
        return b

    def _moved(self, v):
        self.ac.set_temp(v)
        self._update_labels()

    def _step(self, d):
        self._act(lambda: self.ac.set_temp(self.ac.state.temp + d))

    def _next_mode(self):
        modes = list(MODES)
        self._act(lambda: self.ac.set_mode(modes[(modes.index(self.ac.state.mode) + 1) % len(modes)]))

    def _next_fan(self):
        fans = list(FAN_LABEL)
        self._act(lambda: self.ac.set_fan(fans[(fans.index(self.ac.state.fan) + 1) % len(fans)]))

    def _act(self, change):
        change()
        self.ac.save()
        self.refresh()
        self.ctl.apply_soon()

    def _sync(self):
        self.ac.on = not self.ac.on
        self.ac.save()
        self.refresh("Sincronizado (nada foi enviado)")

    def _busy(self, on):
        self.spin.set_active(on)
        if on:
            self.status.setText("Atualizando...")

    def _update_labels(self):
        dim = "" if self.ac.on else "opacity:.5;"
        self.big.setText(f"<span style=\"color:{'white' if self.ac.on else '#8b95a3'};"
                         f"font:300 50pt '{FONT}'\">{self.ac.state.temp}</span>"
                         f"<span style=\"color:#8b95a3;font:14pt '{FONT}'\"> °C</span>")

    def refresh(self, msg=""):
        ac, st = self.ac, self.ac.state
        on = ac.on
        self.power_btn.setStyleSheet(
            "QPushButton{border:none;border-radius:27px;font:19pt 'Segoe UI Symbol';"
            + ("background:#4cc2ff;color:#0b2433}" if on else
               "background:rgba(255,255,255,16);color:#8b95a3}"))
        self.glow.setEnabled(on)
        self.sub.setText(f"Consul · {'Ligado' if on else 'Desligado'}")
        self._update_labels()
        self.slider.set_value(st.temp, on)
        self.tiles["mode"].set_state(MODE_LABEL[st.mode], on, MODE_ICON[st.mode])
        self.tiles["fan"].set_state(FAN_LABEL[st.fan], on and st.fan != "auto")
        self.tiles["sleep"].set_state("Ligado" if st.sleep else "Desligado", st.sleep)
        self.tiles["swing"].set_state("Ligado" if st.swing else "Desligado", st.swing)
        self.tiles["light_off"].set_state("Desligado" if st.light_off else "Ligado", not st.light_off and on)
        self.tiles["turbo"].set_state("Ligado" if st.turbo else "Desligado", st.turbo)
        self.status.setText(msg or "Pronto")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#182636"))
        g.setColorAt(0.45, QColor("#0f141c"))
        g.setColorAt(1, QColor("#0b0e13"))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 30, 30)

    def showEvent(self, e):
        self._sync_streams()
        super().showEvent(e)

    def hideEvent(self, e):
        self.art.stop()
        self.cams.stop()
        self.hidden_at = time.monotonic()
        super().hideEvent(e)

    def toggle_near_tray(self):
        # why: com Qt.Popup o clique no ícone fecha o pop-up antes do evento chegar; sem isso ele reabriria
        if self.isVisible():
            self.hide()
            return
        if time.monotonic() - self.hidden_at < 0.3:
            return
        self.refresh()
        self.adjustSize()
        self._anchor()
        self.show()
        self.activateWindow()


def tray_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(BLUE)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 16, 16)
    icon_snow(p, QRectF(14, 14, 36, 36), QColor("#0b2433"))
    p.end()
    return QIcon(pm)


def main():
    # hazard: o log do ffmpeg do Qt imprime a URL RTSP com a senha da câmera
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # invariant: uma só instância; duas teriam estados supostos diferentes do mesmo ar
    lock = QLockFile(str(BASE / "ac_tray.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        sys.exit(0)
    ctl = Controller()
    popup = Popup(ctl)
    tray = QSystemTrayIcon(tray_icon(), app)
    tray.setToolTip("Casa")
    menu = QMenu()
    open_act = QAction("Abrir", menu)
    open_act.triggered.connect(popup.toggle_near_tray)
    quit_act = QAction("Sair", menu)
    quit_act.triggered.connect(app.quit)
    app.aboutToQuit.connect(popup.alarm.shutdown)
    menu.addAction(open_act)
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: popup.toggle_near_tray()
                           if r == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    if "--show" in sys.argv:
        popup.toggle_near_tray()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
