import json
import time
from dataclasses import asdict, replace
from pathlib import Path

from tinytuya.Contrib.IRRemoteControlDevice import IRRemoteControlDevice

from ir_model import (CMD_FAN, CMD_LIGHT, CMD_MODE, CMD_SLEEP, CMD_SUPER, CMD_SWING, CMD_TEMP,
                      TEMP_MIN, State, build)

BASE = Path(__file__).parent
CODES_PATH = BASE / "codes.json"
STATE_PATH = BASE / "state.json"
MODES = {"cool": "Frio", "dry": "Seco", "fan_only": "Ventilar"}
TEMP_MAX = 32
TOGGLE_CMD = {"sleep": CMD_SLEEP, "swing": CMD_SWING, "light_off": CMD_LIGHT}


def load_codes():
    if CODES_PATH.exists():
        return json.loads(CODES_PATH.read_text(encoding="utf-8"))
    return {"_control_type": 0, "codes": {}}


def save_codes(data):
    CODES_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def open_device(control_type=0, persist=False):
    devs = json.loads((BASE / "devices.json").read_text(encoding="utf-8"))
    ac = next(d for d in devs if d["name"] == "AC")
    # hazard: ac["key"] é a local key; nunca logar
    dev = IRRemoteControlDevice(
        ac["id"], ac["ip"], ac["key"], version=float(ac["version"] or 3.5),
        control_type=control_type, persist=persist,
    )
    # why: sem timeout curto, emissor que ignora a conexão deixa a interface em "Atualizando..." para sempre
    dev.set_socketTimeout(3)
    dev.set_socketRetryLimit(1)
    return dev


class AC:
    def __init__(self):
        self.data = load_codes()
        self.on = False
        self.state = State()
        self.saved = None
        self.cmd = CMD_TEMP
        if STATE_PATH.exists():
            try:
                s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                self.on = s["on"]
                self.state = State(**s["state"])
                self.saved = State(**s["saved"]) if s.get("saved") else None
            except (KeyError, TypeError, ValueError):
                pass

    def save(self):
        STATE_PATH.write_text(json.dumps(
            {"on": self.on, "state": asdict(self.state),
             "saved": asdict(self.saved) if self.saved else None}), encoding="utf-8")

    def _leave_turbo(self):
        # why: o turbo do ar força 18°C/ventoinha máxima; qualquer outra mudança volta ao estado anterior
        if self.state.turbo:
            self.state = replace(self.saved or State(), turbo=False)

    def set_temp(self, t):
        self._leave_turbo()
        self.state = replace(self.state, temp=max(TEMP_MIN, min(TEMP_MAX, t)))
        self.cmd = CMD_TEMP

    def set_mode(self, mode):
        self._leave_turbo()
        self.state = replace(self.state, mode=mode)
        self.cmd = CMD_MODE

    def set_fan(self, fan):
        self._leave_turbo()
        self.state = replace(self.state, fan=fan)
        self.cmd = CMD_FAN

    def toggle(self, name):
        self._leave_turbo()
        value = not getattr(self.state, name)
        self.state = replace(self.state, **{name: value})
        if name == "sleep" and value:
            self.state = replace(self.state, fan="low")
        self.cmd = TOGGLE_CMD[name]

    def toggle_turbo(self):
        if self.state.turbo:
            self._leave_turbo()
            self.cmd = CMD_TEMP
        else:
            self.saved = self.state
            self.state = replace(self.state, turbo=True, temp=TEMP_MIN, mode="cool", fan="max")
            self.cmd = CMD_SUPER

    def _send_code(self, code, attempts=3):
        command = {"control": "send_ir", "type": 0, "head": "", "key1": "1" + code}
        for _ in range(attempts):
            # why: sessão nova por envio; a persistente falhava com 914 após ociosidade
            dev = open_device(self.data["_control_type"])
            # hazard: send_button da lib descarta o resultado; falha de conexão passava como sucesso
            r = dev.set_value(dev.DP_SEND_IR, json.dumps(command), nowait=True)
            if not (isinstance(r, dict) and r.get("Err")):
                return
            time.sleep(1)
        raise RuntimeError(f"emissor não respondeu ({r.get('Error', r.get('Err'))})")

    def _send(self, key):
        code = self.data["codes"].get(key)
        if not code:
            raise KeyError(f"código '{key}' não gravado (rode learn.py)")
        self._send_code(code)

    def power(self, on):
        # invariant: self.on só muda depois do envio dar certo, para não divergir do ar em caso de erro
        if on:
            self._send("on")
            self.on = True
            # why: o ar ignora pacotes de temperatura/modo enquanto desligado e ainda ignorava 1,5 s após o on
            time.sleep(4)
            self.cmd = CMD_TEMP
            self.apply()
        else:
            self._send("off")
            self.on = False

    def apply(self):
        # hazard: com o ar desligado o pacote de estado só faz bip e é ignorado
        if self.on:
            cmd, self.cmd = self.cmd, CMD_TEMP
            st = self.state
            if cmd == CMD_SWING:
                # why: medido no ar: a tecla de oscilação alterna só com o bit ligado; com o bit desligado ele ignora
                st = replace(st, swing=True)
            self._send_code(build(self.data["codes"]["cool_18"], st, cmd))
