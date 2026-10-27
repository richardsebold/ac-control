import json
import queue
import select
import socket
import threading
import time
from pathlib import Path

BASE = Path(__file__).parent
ALARM_PATH = BASE / "alarm.json"

# why: protocolo JFL Active não é público; o formato abaixo vem da engenharia reversa da
# integração comunitária fernac03/JFL_ACTIVE e só foi conferido contra ela, não contra uma central real
SOF = 0x7B
CMD_AWAY, CMD_HOME, CMD_DISARM = 0x4E, 0x53, 0x4F
IDLE_DROP = 180.0
STATUS_EVERY = 30.0

PARTITION_STATE = {
    0x01: "disarmed", 0x02: "armed_away", 0x03: "armed_home", 0x04: "disarmed",
    0x81: "triggered", 0x82: "triggered", 0x83: "triggered", 0x84: "triggered",
}
EVENT_STATE = {
    "3401": "armed_away", "3403": "armed_away", "3404": "armed_away", "3407": "armed_away",
    "3408": "armed_away", "3409": "armed_away", "3441": "armed_home",
    "1401": "disarmed", "1403": "disarmed", "1407": "disarmed", "1409": "disarmed",
}
MODELS = {
    0xA0: "Active 32 Duo", 0xA1: "Active 20 Ultra/GPRS", 0xA2: "Active 8 Ultra",
    0xA3: "Active 20 Ethernet", 0xA4: "Active 100 Bus", 0xA5: "Active 20 Bus",
    0xA6: "Active Full 32", 0xA7: "Active 20", 0xA8: "Active 8W", 0x4B: "M-300+", 0x5D: "M-300 Flex",
}


def frame(*body):
    """Monta SOF, tamanho total, corpo e checksum XOR de tudo que veio antes."""
    data = bytes([SOF, len(body) + 3, *body])
    cs = 0
    for b in data:
        cs ^= b
    return data + bytes([cs])


STATUS_REQUEST = frame(0x01, 0x4D)
KEEPALIVE = frame(0x02, 0x4D)


def split_frames(chunk):
    """Separa quadros colados num mesmo recv; sem tamanho coerente, o chunk inteiro é um quadro."""
    out = []
    while len(chunk) >= 2 and chunk[0] == SOF and 5 <= chunk[1] < len(chunk):
        out.append(chunk[:chunk[1]])
        chunk = chunk[chunk[1]:]
    if chunk:
        out.append(chunk)
    return out


def load_config(path=ALARM_PATH):
    """None se o arquivo não existe ou não tem panel_ip."""
    if not Path(path).exists():
        return None
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    # hazard: sem filtro por IP, qualquer máquina da rede conectaria e controlaria o alarme
    if not cfg.get("panel_ip"):
        return None
    cfg.setdefault("bind", "0.0.0.0")
    cfg.setdefault("port", 8085)
    cfg.setdefault("partitions", [1])
    return cfg


def summarize(states):
    """Resume o estado das partições configuradas num só valor."""
    vals = list(states.values())
    if not vals:
        return "unknown"
    if "triggered" in vals:
        return "triggered"
    if all(v == "armed_away" for v in vals):
        return "armed_away"
    if all(v == "armed_home" for v in vals):
        return "armed_home"
    if any(v.startswith("armed") for v in vals):
        return "partial"
    return "disarmed"


class AlarmHub:
    """Servidor TCP: a central JFL é quem conecta aqui (IP destino/porta destino na programação dela)."""

    def __init__(self, cfg, on_change=None):
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)
        self.partitions = list(cfg["partitions"])
        self.states = {}
        self.model = ""
        self.connected = False
        self.port = cfg["port"]
        self._out = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._listener = None

    @property
    def state(self):
        return summarize({p: s for p, s in self.states.items() if p in self.partitions})

    def start(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.cfg["bind"], self.cfg["port"]))
        s.listen(1)
        self.port = s.getsockname()[1]
        self._listener = s
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        if self._listener:
            self._listener.close()

    def command(self, cmd):
        """False se a central não está conectada; o estado novo chega no próximo pacote de status."""
        if not self.connected:
            return False
        for p in self.partitions:
            self._out.put(frame(0x01, cmd, p))
        self._out.put(STATUS_REQUEST)
        return True

    def arm_away(self):
        return self.command(CMD_AWAY)

    def arm_home(self):
        return self.command(CMD_HOME)

    def disarm(self):
        return self.command(CMD_DISARM)

    def _run(self):
        self._listener.settimeout(1.0)
        while not self._stop.is_set():
            try:
                conn, addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if addr[0] != self.cfg["panel_ip"]:
                conn.close()
                continue
            with conn:
                self._set_connected(True)
                try:
                    self._serve(conn)
                except OSError:
                    pass
                finally:
                    self._set_connected(False)

    def _set_connected(self, on):
        if self.connected != on:
            self.connected = on
            if not on:
                # invariant: sem conexão o estado guardado é velho e não pode ser mostrado como atual
                self.states = {}
            self.on_change()

    def _serve(self, conn):
        conn.settimeout(1.0)
        last_rx = last_req = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            while not self._out.empty():
                conn.sendall(self._out.get())
            if now - last_req > STATUS_EVERY:
                conn.sendall(STATUS_REQUEST)
                last_req = now
            if now - last_rx > IDLE_DROP:
                return
            # why: central que reconecta enquanto a conexão velha está morta precisa ser aceita já
            if select.select([self._listener], [], [], 0)[0]:
                return
            try:
                data = conn.recv(512)
            except socket.timeout:
                continue
            if not data:
                return
            last_rx = time.monotonic()
            for f in split_frames(data):
                for reply in self._handle(f):
                    conn.sendall(reply)

    def _handle(self, f):
        n = len(f)
        if n == 5:
            return [frame(0x01, 0x40, 0x01)]
        if n == 102:
            self.model = MODELS.get(f[41], f"Desconhecida (0x{f[41]:02X})")
            self._set_states(f, 85, 16)
            self.on_change()
            return [frame(0x01, 0x21, 0x01, 0x01), STATUS_REQUEST]
        if n == 24:
            new = EVENT_STATE.get(f[8:12].decode("ascii", "replace"))
            if new:
                self._apply({p: new for p in self.partitions})
            return [frame(0x01, 0x24, 0x01, f[17], f[18], f[19], f[20])]
        if n >= 118:
            self._set_states(f, 14, 4)
        return []

    def _set_states(self, f, offset, count):
        new = {}
        for i in range(count):
            st = PARTITION_STATE.get(f[offset + i])
            if st:
                new[i + 1] = st
        self._apply(new)

    def _apply(self, new):
        before = (self.state, self.model)
        self.states.update(new)
        if (self.state, self.model) != before:
            self.on_change()
