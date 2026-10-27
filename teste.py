import json
import tinytuya

devs = json.load(open("devices.json", encoding="utf-8"))
ac = next(d for d in devs if d["name"] == "AC")

for v in (3.3, 3.4, 3.5):
    # hazard: nunca imprimir a local key
    d = tinytuya.Device(ac["id"], ac["ip"], ac["key"], version=v)
    d.set_socketTimeout(5)
    d.set_socketRetryLimit(1)
    r = d.status()
    print(v, json.dumps(r, ensure_ascii=False))
