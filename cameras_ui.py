import json
import socket
import struct
import subprocess
import threading
import time

from PyQt6.QtCore import QObject, QRectF, Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ac_core import BASE

CAMERAS_PATH = BASE / "cameras.json"
FONT = "Segoe UI"
NO_VIDEO_AFTER = 9.0


GO2RTC_EXE = BASE / "go2rtc" / "go2rtc.exe"
GO2RTC_RTSP = ("127.0.0.1", 8554)
_go2rtc_lock = threading.Lock()


def load_cameras():
    if not CAMERAS_PATH.exists():
        return []
    cams = json.loads(CAMERAS_PATH.read_text(encoding="utf-8")).get("cameras", [])
    # invariant: o nome do stream no go2rtc é cam{posição}, igual ao que o gen_go2rtc.py escreve
    for i, c in enumerate(cams, 1):
        c["stream_id"] = f"cam{i}"
    return cams


def _port_open(addr):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(addr) == 0
    finally:
        s.close()


def ensure_go2rtc():
    """True se o go2rtc está respondendo; inicia o processo (oculto) se ele não estiver rodando."""
    with _go2rtc_lock:
        if _port_open(GO2RTC_RTSP):
            return True
        if not GO2RTC_EXE.exists():
            return False
        subprocess.Popen([str(GO2RTC_EXE)], cwd=GO2RTC_EXE.parent, creationflags=subprocess.CREATE_NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.25)
            if _port_open(GO2RTC_RTSP):
                return True
        return False


def snapshot_jpeg(cam, channel=0):
    """Foto via XMeye lendo o JPEG até o marcador final.

    why: a lib python-dvr só aceita JPEG que começa com FFD8FFE0 (JFIF); a câmera X2C-WQ
    manda FFD8FFDB e a lib levanta ValueError. Lê qualquer JPEG, em um ou vários pacotes.
    """
    cam.send(cam.QCODES["OPSNAP"],
             {"Name": "OPSNAP", "SessionID": "0x%08X" % cam.session, "OPSNAP": {"Channel": channel}},
             wait_response=False)
    buf = bytearray()
    deadline = time.time() + cam.timeout
    while time.time() < deadline:
        head = cam.receive_with_timeout(20)
        (len_data,) = struct.unpack("I", head[16:20])
        buf.extend(cam.receive_with_timeout(len_data))
        if buf[:2] == b"\xff\xd8" and buf.rstrip(b"\x00\n")[-2:] == b"\xff\xd9":
            return bytes(buf)
    return None


class Source(QObject):
    """Vídeo de uma câmera: RTSP se a porta 554 abrir, senão fotos instantâneas via XMeye."""

    frame = pyqtSignal(QImage)
    status = pyqtSignal(str)
    _probed = pyqtSignal(str)

    def __init__(self, cam, stream):
        super().__init__()
        self.cam, self.stream = cam, stream
        self.running = False
        self.got_frame = False
        self.player = None
        self._probed.connect(self._begin)

    def start(self):
        self.running, self.got_frame = True, False
        self.status.emit("Conectando...")
        threading.Thread(target=self._probe, daemon=True).start()

    def stop(self):
        self.running = False
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())

    def _probe(self):
        # why: o go2rtc entrega vídeo contínuo (inclusive H.265) de todas as câmeras; os modos
        # diretos abaixo ficam só como reserva se o go2rtc não existir ou não subir
        if ensure_go2rtc():
            self._probed.emit("go2rtc")
            return
        s = socket.socket()
        s.settimeout(1.0)
        has_rtsp = s.connect_ex((self.cam["ip"], 554)) == 0
        s.close()
        self._probed.emit("rtsp" if has_rtsp else "dvrip")

    def _begin(self, mode):
        if not self.running:
            return
        if mode == "dvrip":
            threading.Thread(target=self._snapshots, daemon=True).start()
        else:
            self._start_rtsp(mode)

    def _start_rtsp(self, mode):
        c = self.cam
        self.player = QMediaPlayer(self)
        sink = QVideoSink(self)
        self.player.setVideoSink(sink)
        sink.videoFrameChanged.connect(self._on_frame)
        self.player.errorOccurred.connect(lambda *_: self._fail())
        if mode == "go2rtc":
            url = f"rtsp://{GO2RTC_RTSP[0]}:{GO2RTC_RTSP[1]}/{c['stream_id']}{'_sub' if self.stream else ''}"
        else:
            # hazard: a URL carrega a senha; nunca logar nem mostrar na interface
            url = (f"rtsp://{c['ip']}:554/user={c.get('user', 'admin')}&password={c.get('password', '')}"
                   f"&channel=1&stream={self.stream}.sdp?real_stream")
        self.player.setSource(QUrl(url))
        self.player.play()
        QTimer.singleShot(int(NO_VIDEO_AFTER * 1000), self._watchdog)

    def _on_frame(self, f):
        if not f.isValid():
            return
        img = f.toImage()
        if not img.isNull():
            self.got_frame = True
            self.frame.emit(img)

    def _watchdog(self):
        if self.running and not self.got_frame:
            self._fail()

    def _fail(self):
        if self.running and not self.got_frame:
            self.status.emit("Sem vídeo — confira a senha")

    def _snapshots(self):
        from dvrip import DVRIPCam
        c = self.cam
        while self.running:
            cam = DVRIPCam(c["ip"], user=c.get("user", "admin"), password=c.get("password", ""))
            try:
                if not cam.login():
                    self.status.emit("Senha recusada")
                    return
                while self.running:
                    img = QImage.fromData(snapshot_jpeg(cam) or b"")
                    if not img.isNull():
                        self.frame.emit(img)
                    time.sleep(1.5)
            except Exception:
                self.status.emit("Sem conexão")
                time.sleep(5)
            finally:
                try:
                    cam.close()
                except Exception:
                    pass


def draw_image(p, img, rect, cover):
    if img is None:
        return
    iw, ih = img.width(), img.height()
    scale = max(rect.width() / iw, rect.height() / ih) if cover else min(rect.width() / iw, rect.height() / ih)
    w, h = iw * scale, ih * scale
    target = QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)
    p.drawImage(target, img)


class CamView(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, cam, stream, radius=14, cover=True, clickable=True):
        super().__init__()
        self.cam, self.radius, self.cover = cam, radius, cover
        self.img, self.note = None, ""
        self.source = Source(cam, stream)
        self.source.frame.connect(self._frame)
        self.source.status.connect(self._status)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def start(self):
        self.source.start()

    def stop(self):
        self.source.stop()

    def _frame(self, img):
        self.img, self.note = img, ""
        self.update()

    def _status(self, text):
        if self.img is None:
            self.note = text
            self.update()

    def mouseReleaseEvent(self, _):
        self.clicked.emit(self.cam)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, self.width(), self.height())
        clip = QPainterPath()
        clip.addRoundedRect(rect, self.radius, self.radius)
        p.setClipPath(clip)
        p.fillRect(rect, QColor("#0b0e13"))
        draw_image(p, self.img, rect, self.cover)
        shade = QLinearGradient(0, rect.height() - 38, 0, rect.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 170))
        p.fillRect(QRectF(0, rect.height() - 38, rect.width(), 38), shade)
        p.setPen(QColor("white"))
        p.setFont(QFont(FONT, 9, QFont.Weight.DemiBold))
        p.drawText(QRectF(10, rect.height() - 24, rect.width() - 20, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.cam["name"])
        if self.img is None:
            p.setPen(QColor("#8b95a3"))
            p.setFont(QFont(FONT, 9))
            p.drawText(rect.adjusted(8, 0, -8, -20), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.note)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)


class LiveWindow(CamView):
    """Janela maior com o fluxo principal; fecha com Esc."""

    def __init__(self, cam):
        super().__init__(cam, 0, radius=0, cover=False, clickable=False)
        self.setWindowTitle(cam["name"])
        self.resize(960, 540)
        self.setMinimumSize(480, 270)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)


class CamPage(QWidget):
    def __init__(self):
        super().__init__()
        self.views, self.windows = [], []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 14, 0, 0)
        cams = load_cameras()
        if not cams:
            msg = QLabel("Nenhuma câmera configurada.\nPreencha o cameras.json.")
            msg.setStyleSheet(f"color:#8b95a3;font:10pt '{FONT}'")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(msg)
            return
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea,QScrollArea>QWidget>QWidget{background:transparent}"
            "QScrollBar:vertical{width:6px;background:transparent}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,40);border-radius:3px}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0}")
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)
        for cam in cams:
            view = CamView(cam, 1)
            view.setFixedHeight(190)  # invariant: 16:9 na largura útil, sem cortar a imagem
            view.clicked.connect(self._open_live)
            col.addWidget(view)
            self.views.append(view)
        col.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
        hint = QLabel("Clique numa câmera para ver ao vivo")
        hint.setStyleSheet(f"color:#6f7885;font:9pt '{FONT}'")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addSpacing(8)
        root.addWidget(hint)

    def start(self):
        for v in self.views:
            v.start()

    def stop(self):
        for v in self.views:
            v.stop()

    def _open_live(self, cam):
        self.windows = [w for w in self.windows if w.isVisible()]
        win = LiveWindow(cam)
        self.windows.append(win)
        win.show()
        win.start()
