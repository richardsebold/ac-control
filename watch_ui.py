import winsound

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QSystemTrayIcon

from cameras_ui import LiveWindow, ensure_go2rtc, load_cameras
from watch_core import Alert, load_zones, save_zones


class Vigia(QObject):
    # why: o alerta nasce numa thread de câmera; o sinal leva a notificação para a thread da UI
    alerted = pyqtSignal(object, str)

    def __init__(self, tray, menu):
        super().__init__()
        self.tray, self.watcher, self.windows, self.last = tray, None, [], None
        self.cams = {f"cam{i}": c for i, c in enumerate(load_cameras(), 1)}
        self.toggle = QAction("Vigia de câmeras", menu)
        self.toggle.setCheckable(True)
        edit = QAction("Zonas do vigia…", menu)
        edit.triggered.connect(self.edit_zones)
        test = QAction("Testar alerta", menu)
        test.triggered.connect(self.test_alert)
        for a in (self.toggle, edit, test):
            menu.addAction(a)
        self.alerted.connect(self._show)
        tray.messageClicked.connect(self._open_live)
        self.toggle.toggled.connect(self._toggled)
        cfg = load_zones()
        if cfg["enabled"] and any(v.get("zones") for v in cfg["cameras"].values()):
            self.toggle.setChecked(True)

    def _toggled(self, on):
        cfg = load_zones()
        if on and not any(v.get("zones") for v in cfg["cameras"].values()):
            self.tray.showMessage("Vigia", "Defina ao menos uma zona antes de ligar.",
                                  QSystemTrayIcon.MessageIcon.Information, 6000)
            self.toggle.setChecked(False)
            return
        cfg["enabled"] = on
        save_zones(cfg)
        self.stop()
        if on:
            self._start(cfg)

    def _start(self, cfg):
        self.watcher = w = _make_watcher(cfg, self._on_alert)
        w.start()
        QTimer.singleShot(10000, lambda: self._report_error(w))

    def _report_error(self, w):
        if w.error and w is self.watcher:
            self.tray.showMessage("Vigia", w.error, QSystemTrayIcon.MessageIcon.Warning, 8000)

    def stop(self):
        if self.watcher:
            self.watcher.stop()
            self.watcher = None

    def edit_zones(self):
        from zone_editor import ZoneEditor
        if ZoneEditor().exec() and self.toggle.isChecked():
            self.stop()
            self._start(load_zones())

    def _on_alert(self, alert, frame):
        from watch_runner import save_alert_frame
        self.alerted.emit(alert, str(save_alert_frame(alert, frame)))

    def test_alert(self):
        # why: o teste deve mostrar a câmera e a zona que o vigia realmente usa, não a primeira da lista
        cams = load_zones()["cameras"]
        key, zone = next(((k, v["zones"][0]["name"]) for k, v in cams.items() if v.get("zones")),
                         (next(iter(self.cams), "cam1"), "nenhuma zona definida"))
        self._show(Alert(key, zone, "vehicle", 0, (0, 0, 1, 1), 0), "", test=True)

    def _show(self, alert, _path, test=False):
        from watch_runner import KIND_LABEL
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        self.last = alert.camera
        name = self.cams.get(alert.camera, {}).get("name", alert.camera)
        if test:
            title = f"TESTE · {name}: {alert.zone}"
            text = "Isto é só um teste; nenhum veículo foi detectado. Clique para ver a câmera ao vivo."
        else:
            title = f"{name}: {alert.zone}"
            text = f"{KIND_LABEL[alert.kind]} parado há {int(alert.seconds)} s. Clique para ver ao vivo."
        self.tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Warning, 20000)

    def _open_live(self):
        cam = self.cams.get(self.last)
        if not cam:
            return
        self.windows = [w for w in self.windows if w.isVisible()]
        win = LiveWindow(cam)
        self.windows.append(win)
        win.show()
        win.start()


def _make_watcher(cfg, on_alert):
    from watch_runner import Watcher
    return Watcher(cfg, on_alert, ensure_go2rtc)
