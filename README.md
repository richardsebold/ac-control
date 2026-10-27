# casa-hub

Hub de bandeja do Windows (PyQt6) para a casa: controla um split Consul (CBN09BBBNA) por um
emissor IR Tuya/Smart Life, e ver câmeras ICSee/XMEye numa segunda aba.

- **Clima:** temperatura (18–32 °C), modo, ventilador, turbo, dormir, oscilação, visor e liga/desliga.
- **Câmeras:** vídeo ao vivo pelo [go2rtc](https://github.com/AlexxIT/go2rtc) local; clique numa câmera para abrir a janela maior.

O protocolo IR do ar (Kelon168) é gerado em `ir_model.py`; só são necessários os códigos `on`, `off`
e `cool_18` gravados do emissor (em `codes.json`). O estado mostrado é presumido: o IR é só de ida,
então o botão ↻ corrige o liga/desliga se alguém usar o controle original.

## Instalação

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw ac_tray.py
```

## Arquivos que você precisa criar (ficam fora do Git)

| Arquivo | Conteúdo |
|---|---|
| `devices.json` | dispositivos do Tuya (gerado por `python -m tinytuya wizard`); o emissor deve se chamar `AC` |
| `codes.json` | `{"_control_type": 1, "on": "...", "off": "...", "cool_18": "..."}` com os códigos gravados |
| `cameras.json` | `{"cameras": [{"name": "Câmera 1", "ip": "192.168.1.5", "user": "admin", "password": "..."}]}` |

`devices.json` tem a chave local do emissor e `cameras.json` tem as senhas. Não os versione.

## Câmeras (go2rtc)

1. Baixe o `go2rtc_win64.zip` da [página de releases](https://github.com/AlexxIT/go2rtc/releases), confira o SHA256 e extraia em `go2rtc/`.
2. Rode `python gen_go2rtc.py` para gerar `go2rtc/go2rtc.yaml` a partir do `cameras.json`
   (refaça se mudar IP ou senha). Ele escuta só em `127.0.0.1`, pois não tem autenticação.
3. O app inicia o go2rtc sozinho ao abrir a aba. Sem ele, cai para RTSP direto ou fotos XMeye.
