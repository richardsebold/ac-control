"""Pacote IR da Consul = protocolo Kelon168 (IRremoteESP8266, ir_Kelon.h/.cpp): 21 bytes em 3 blocos."""
import base64
import struct
from dataclasses import dataclass, replace

ONE_GAP, ZERO_GAP = 1620, 560
# invariant: (pulso inicial, nº de bytes) por bloco; bit n do bloco começa no pulso start+2n, espaço em +1
BLOCKS = [(2, 6), (100, 8), (230, 7)]
TEMP_MIN = 18  # medido no ar: 18°C = campo 0 (a lib fala em 16 para outros modelos)

CMD_LIGHT, CMD_POWER, CMD_TEMP, CMD_SLEEP = 0x00, 0x01, 0x02, 0x03
CMD_SUPER, CMD_MODE, CMD_SWING, CMD_FAN = 0x04, 0x06, 0x07, 0x11
MODE_BITS = {"cool": 2, "dry": 3, "fan_only": 4}
# invariant: nível -> (Fan 2 bits no byte 2, Fan2 no bit 1 do byte 16), da tabela de setFan()
FAN_BITS = {"auto": (0, 0), "min": (3, 0), "low": (3, 1), "medium": (2, 0), "high": (1, 1), "max": (1, 0)}


def to_pulses(code):
    if len(code) % 4 == 1 and code[0] == "1":
        code = code[1:]
    raw = base64.b64decode(code)
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def to_code(pulses):
    return base64.b64encode(struct.pack("<%dH" % len(pulses), *pulses)).decode("ascii")


def _slots():
    for start, size in BLOCKS:
        for n in range(size):
            yield start + 16 * n


def read_bytes(p):
    return [sum((p[s + 2 * i + 1] > 1100) << i for i in range(8)) for s in _slots()]


def write_bytes(p, data):
    for s, v in zip(_slots(), data):
        for i in range(8):
            p[s + 2 * i + 1] = ONE_GAP if (v >> i) & 1 else ZERO_GAP


def xor(data):
    out = 0
    for v in data:
        out ^= v
    return out


@dataclass(frozen=True)
class State:
    mode: str = "cool"
    temp: int = 24
    fan: str = "auto"
    sleep: bool = False
    swing: bool = False
    turbo: bool = False
    light_off: bool = False


def build(template, st, cmd, power=False):
    p = to_pulses(template)
    b = read_bytes(p)
    fan, fan2 = FAN_BITS[st.fan]
    b[2] = (b[2] & 0x70) | fan | (power << 2) | (st.sleep << 3) | (st.swing << 7)
    b[3] = (b[3] & 0x08) | MODE_BITS[st.mode] | ((st.temp - TEMP_MIN) << 4)
    b[5] = (b[5] & ~0x90 & 0xFF) | (0x90 if st.turbo else 0)
    b[6] = (b[6] & ~0x20 & 0xFF) | (0x20 if st.light_off else 0)
    b[8] = (b[8] & ~0x40 & 0xFF) | (0x40 if st.swing else 0)
    b[15] = cmd
    b[16] = (b[16] & ~0x02 & 0xFF) | (fan2 << 1)
    # why: Sum1 = XOR dos bytes 2..12; Sum2 = XOR dos bytes 14..19 (ir_Kelon.cpp, checksum())
    b[13] = xor(b[2:13])
    b[20] = xor(b[14:20])
    write_bytes(p, b)
    return to_code(p)


def decode(code):
    b = read_bytes(to_pulses(code))
    inv = {v: k for k, v in MODE_BITS.items()}
    fan_inv = {v: k for k, v in FAN_BITS.items()}
    st = State(mode=inv.get(b[3] & 7, "?"), temp=(b[3] >> 4) + TEMP_MIN,
               fan=fan_inv.get((b[2] & 3, (b[16] >> 1) & 1), "?"), sleep=bool(b[2] & 8),
               swing=bool(b[2] & 0x80), turbo=bool(b[5] & 0x90), light_off=bool(b[6] & 0x20))
    return st, b[15], bool(b[2] & 4), b
