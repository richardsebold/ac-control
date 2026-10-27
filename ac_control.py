import threading
import tkinter as tk
from tkinter import ttk

from ac_core import AC, MODES, TEMP_MAX, TEMP_MIN

ac = AC()
root = tk.Tk()
root.title("Ar-condicionado")
root.configure(bg="#1c1c1e", padx=16, pady=16)

status = tk.StringVar(value="Pronto (ar desligado)")
temp_var = tk.IntVar(value=ac.temp)
mode_var = tk.StringVar(value=ac.mode)
busy = threading.Lock()


def describe():
    return f"{'Ligado' if ac.on else 'Desligado'} · {MODES[ac.mode]} · {ac.temp}°C"


def run(action, done=None):
    """Envia em segundo plano; o on leva ~4 s e travaria a janela."""
    def worker():
        if not busy.acquire(blocking=False):
            root.after(0, status.set, "Aguarde o envio anterior...")
            return
        try:
            action()
            root.after(0, status.set, describe())
            if done:
                root.after(0, done)
        except Exception as e:
            root.after(0, status.set, f"Erro: {e}")
        finally:
            busy.release()
    status.set("Enviando...")
    threading.Thread(target=worker, daemon=True).start()


def refresh_power_label():
    power_btn.config(text="Desligar" if ac.on else "Ligar")


def toggle():
    run(lambda: ac.power(not ac.on), refresh_power_label)


def sync():
    """Corrige o estado suposto do app sem enviar nada (o IR não tem retorno)."""
    ac.on = not ac.on
    refresh_power_label()
    status.set(describe() + " (sincronizado)")


def set_temp(t):
    ac.temp = max(TEMP_MIN, min(TEMP_MAX, int(float(t))))
    temp_var.set(ac.temp)
    lbl.config(text=f"{ac.temp}°C")


def step(d):
    set_temp(ac.temp + d)
    if ac.on:
        run(ac.apply)


def set_mode():
    ac.mode = mode_var.get()
    if ac.on:
        run(ac.apply)


lbl = tk.Label(root, text=f"{ac.temp}°C", font=("Segoe UI", 40), fg="white", bg="#1c1c1e")
lbl.grid(row=0, column=0, columnspan=3)
tk.Button(root, text="−", width=4, command=lambda: step(-1)).grid(row=1, column=0)
sl = ttk.Scale(root, from_=TEMP_MIN, to=TEMP_MAX, variable=temp_var, command=set_temp, length=160)
sl.bind("<ButtonRelease-1>", lambda e: ac.on and run(ac.apply))
sl.grid(row=1, column=1)
tk.Button(root, text="+", width=4, command=lambda: step(1)).grid(row=1, column=2)
for i, (k, v) in enumerate(MODES.items()):
    tk.Radiobutton(root, text=v, value=k, variable=mode_var, command=set_mode,
                   fg="white", bg="#1c1c1e", selectcolor="#333", indicatoron=False,
                   width=8).grid(row=2, column=i, pady=8)
power_btn = tk.Button(root, text="Ligar", command=toggle, width=20)
power_btn.grid(row=3, column=0, columnspan=3)
tk.Button(root, text="Sincronizar (ar ligou/desligou sem o app)", command=sync,
          bg="#1c1c1e", fg="#aaa", relief="flat").grid(row=4, column=0, columnspan=3, pady=(6, 0))
tk.Label(root, textvariable=status, fg="#aaa", bg="#1c1c1e").grid(row=5, column=0, columnspan=3)
root.mainloop()
