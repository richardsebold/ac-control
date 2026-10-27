import json
import math
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).parent
ZONES_PATH = BASE / "zones.json"

VEHICLE, PERSON = "vehicle", "person"
IOU_MATCH = 0.3
# why: o detector perde o alvo por alguns quadros (sombra, ônibus na frente); sem folga o mesmo carro vira dois e alerta de novo
MAX_AGE = 15.0
STILL_FRAC = 0.2
BASELINE = 12.0
COOLDOWN = 30.0
DEFAULT_SECONDS = {VEHICLE: 10, PERSON: 5}


@dataclass
class Det:
    box: tuple  # x1, y1, x2, y2 normalizados em 0..1
    kind: str
    score: float = 1.0


@dataclass
class Alert:
    camera: str
    zone: str
    kind: str
    seconds: float
    box: tuple
    at: float


@dataclass
class Track:
    id: int
    box: tuple
    kind: str
    first: float
    last: float
    anchor: tuple
    since: float
    ignored: bool = False
    alerted: bool = False
    enter: dict = field(default_factory=dict)


def load_zones(path=ZONES_PATH):
    if not Path(path).exists():
        return {"enabled": False, "cameras": {}}
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg.setdefault("enabled", True)
    cfg.setdefault("cameras", {})
    return cfg


def save_zones(cfg, path=ZONES_PATH):
    Path(path).write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def in_polygon(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _size(b):
    return max(b[2] - b[0], b[3] - b[1])


class ZoneWatcher:
    """Acompanha os alvos de uma câmera e avisa quando um fica parado dentro de uma zona."""

    def __init__(self, camera, zones, now):
        self.camera = camera
        self.zones = [z for z in zones if len(z.get("points", [])) >= 3]
        self.start = now
        self.tracks = []
        self.next_id = 1
        self.last_alert = {}

    def update(self, dets, now):
        free = list(dets)
        for t in self.tracks:
            best = max((d for d in free if d.kind == t.kind), key=lambda d: iou(t.box, d.box), default=None)
            if best is not None and iou(t.box, best.box) >= IOU_MATCH:
                free.remove(best)
                self._move(t, best.box, now)
        for d in free:
            t = Track(self.next_id, d.box, d.kind, now, now, _center(d.box), now)
            # invariant: o que já estava parado na zona quando o vigia ligou é ignorado até sair (carro estacionado)
            t.ignored = now - self.start < BASELINE
            self.next_id += 1
            self.tracks.append(t)
        self.tracks = [t for t in self.tracks if now - t.last <= MAX_AGE]
        return [a for t in self.tracks if t.last == now for a in self._check(t, now)]

    def _move(self, t, box, now):
        t.box, t.last = box, now
        c = _center(box)
        if math.dist(c, t.anchor) > STILL_FRAC * _size(box):
            t.anchor, t.since = c, now
            # why: carro que passou na zona durante a linha de base e depois parou deve alertar; só o que nunca se mexeu fica ignorado
            if now - self.start >= BASELINE:
                t.ignored = False

    def _check(self, t, now):
        foot = ((t.box[0] + t.box[2]) / 2, t.box[3])
        out = []
        for z in self.zones:
            name = z["name"]
            if t.kind not in z.get("kinds", [VEHICLE]) or not in_polygon(foot, z["points"]):
                t.enter.pop(name, None)
                continue
            t.enter.setdefault(name, now)
            need = z.get("seconds", DEFAULT_SECONDS[t.kind])
            dwell = now - max(t.since, t.enter[name])
            if t.ignored or t.alerted or dwell < need:
                continue
            if now - self.last_alert.get(name, -COOLDOWN) < COOLDOWN:
                continue
            t.alerted = True
            self.last_alert[name] = now
            out.append(Alert(self.camera, name, t.kind, dwell, t.box, now))
        return out
