"""Gera go2rtc/go2rtc.yaml a partir do cameras.json (rode de novo se mudar IP ou senha)."""
import json
from urllib.parse import quote

from ac_core import BASE

OUT = BASE / "go2rtc" / "go2rtc.yaml"

cams = json.loads((BASE / "cameras.json").read_text(encoding="utf-8"))["cameras"]
lines = [
    "# hazard: contém as senhas das câmeras; arquivo ignorado pelo git, não compartilhar",
    "api:",
    "  # why: sem autenticação, 0.0.0.0 mostraria as câmeras para toda a rede; só localhost por padrão",
    '  listen: "127.0.0.1:1984"',
    "rtsp:",
    '  listen: "127.0.0.1:8554"',
    "webrtc:",
    '  listen: "127.0.0.1:8555"',
    "streams:",
]
for i, c in enumerate(cams, 1):
    user, pw = quote(c.get("user", "admin"), safe=""), quote(c.get("password", ""), safe="")
    # why: cam{i} = fluxo principal (janela ao vivo); cam{i}_sub = fluxo leve para as miniaturas da aba
    lines.append(f"  cam{i}: dvrip://{user}:{pw}@{c['ip']}:34567?channel=0&subtype=0")
    lines.append(f"  cam{i}_sub: dvrip://{user}:{pw}@{c['ip']}:34567?channel=0&subtype=1")
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(cams)} câmeras em {OUT.relative_to(BASE)}")
