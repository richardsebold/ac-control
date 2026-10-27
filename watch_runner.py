import os
import threading
import time

# hazard: precisa vir antes de importar o cv2, que lê a variável uma vez; sem TCP o RTSP perde pacotes e o HEVC quebra
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

from detector import MODEL_PATH, Detector
from watch_core import BASE, PERSON, ZoneWatcher

RTSP = "rtsp://127.0.0.1:8554/{}_sub"
# why: o HEVC só decodifica certo a partir do primeiro quadro-chave; antes disso o decodificador entrega imagem cinza corrompida
WARMUP = 4.0
PERIOD = 0.5
RETRY = 8.0
ALERTS_DIR = BASE / "alertas"
KEEP_ALERTS = 50
KIND_LABEL = {"vehicle": "Veículo", PERSON: "Pessoa"}


def open_stream(stream_id):
    cap = cv2.VideoCapture(RTSP.format(stream_id), cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
    return cap


def grab_frame(stream_id, warmup=WARMUP):
    """Último quadro após o aquecimento; None se o stream não abriu."""
    cap = open_stream(stream_id)
    frame, end = None, time.monotonic() + warmup
    while time.monotonic() < end:
        ok, f = cap.read()
        if ok:
            frame = f
        elif not cap.isOpened():
            break
        else:
            # why: antes do primeiro quadro-chave o read falha; insistir em vez de desistir do stream
            time.sleep(0.05)
    cap.release()
    return frame


def save_alert_frame(alert, frame):
    """Grava o quadro do alerta com a caixa desenhada; devolve o caminho."""
    ALERTS_DIR.mkdir(exist_ok=True)
    h, w = frame.shape[:2]
    img = frame.copy()
    x1, y1, x2, y2 = alert.box
    cv2.rectangle(img, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), (0, 80, 255), 2)
    path = ALERTS_DIR / time.strftime(f"%Y%m%d-%H%M%S-{alert.camera}.jpg")
    cv2.imwrite(str(path), img)
    for old in sorted(ALERTS_DIR.glob("*.jpg"))[:-KEEP_ALERTS]:
        old.unlink()
    return path


class CameraWorker(threading.Thread):
    def __init__(self, cam_key, zones, detector, on_alert, stop):
        super().__init__(daemon=True)
        self.cam_key, self.zones, self.detector = cam_key, zones, detector
        self.on_alert, self.stop_event = on_alert, stop
        self.last_error = ""

    def run(self):
        while not self.stop_event.is_set():
            try:
                self._watch()
            except Exception as e:
                # why: um erro numa câmera (decodificador, ONNX) não pode derrubar o vigia das outras
                self.last_error = repr(e)
            self.stop_event.wait(RETRY)

    def _watch(self):
        cap = open_stream(self.cam_key)
        try:
            ready_at = time.monotonic() + WARMUP
            watcher, last = None, 0.0
            while not self.stop_event.is_set():
                if not cap.grab():
                    return
                now = time.monotonic()
                if now < ready_at or now - last < PERIOD:
                    continue
                ok, frame = cap.retrieve()
                if not ok:
                    continue
                last = now
                if watcher is None:
                    # invariant: a linha de base conta a partir do primeiro quadro bom, não da abertura do stream
                    watcher = ZoneWatcher(self.cam_key, self.zones, now)
                for alert in watcher.update(self.detector.detect(frame), now):
                    self.on_alert(alert, frame)
        finally:
            cap.release()


class Watcher:
    """Um worker por câmera com zonas; o modelo é carregado uma vez e compartilhado."""

    def __init__(self, zones_cfg, on_alert, ensure):
        self.cfg, self.on_alert, self.ensure = zones_cfg, on_alert, ensure
        self.stop_event = threading.Event()
        self.error = ""
        self.workers = []

    def start(self):
        threading.Thread(target=self._boot, daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def _boot(self):
        cams = {k: v["zones"] for k, v in self.cfg["cameras"].items() if v.get("zones")}
        if not cams:
            self.error = "Nenhuma zona definida."
            return
        if not MODEL_PATH.exists():
            self.error = f"Modelo ausente: {MODEL_PATH.name} (rode gen_model.py)."
            return
        if not self.ensure():
            self.error = "go2rtc não está disponível."
            return
        detector = Detector()
        for key, zones in cams.items():
            w = CameraWorker(key, zones, detector, self.on_alert, self.stop_event)
            self.workers.append(w)
            w.start()
