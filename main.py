"""Okunek Music — точка входа. При первом запуске сам подтягивает всё нужное (с окном прогресса)."""
import os
import queue
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
for _s in (sys.stdout, sys.stderr):  # консоль Windows может быть не-UTF-8 — не падать на русском тексте
    try:
        _s.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

from okunek import engine  # noqa: E402
from okunek.config import APP, APP_NAME, FROZEN, VERSION  # noqa: E402


def crash(tb):
    try:
        os.makedirs(APP, exist_ok=True)
        with open(os.path.join(APP, "log.txt"), "a", encoding="utf-8") as f:
            f.write(tb + "\n")
    except Exception:  # noqa: BLE001
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_NAME, "Программа завершилась с ошибкой.\nПодробности: " + os.path.join(APP, "log.txt") + "\n\n" + tb[-600:])
    except Exception:  # noqa: BLE001
        pass


def needs_setup():
    """Быстрая проверка: чего не хватает. Если всё есть — окно установки не показываем вовсе."""
    miss = [] if FROZEN else engine.missing_pip()
    if not miss:
        engine.load_ytdlp()
        engine.load_vlc()
    return miss, (not engine.yt_dlp), (not engine.vlc)


def run_setup(miss, need_yt, need_vlc):
    import tkinter as tk
    root = tk.Tk()
    root.title(APP_NAME)
    root.configure(bg="#120c1f")
    root.resizable(False, False)
    w, h = 460, 150
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")
    tk.Label(root, text=f"{APP_NAME} {VERSION}", bg="#120c1f", fg="#f4efff", font=("Segoe UI", 14, "bold")).pack(pady=(18, 2))
    msg = tk.Label(root, text="Готовлю первый запуск…", bg="#120c1f", fg="#a193c4", font=("Segoe UI", 10))
    msg.pack()
    bar = tk.Canvas(root, width=380, height=8, bg="#241838", highlightthickness=0)
    bar.pack(pady=16)
    fill = bar.create_rectangle(0, 0, 0, 8, fill="#a855f7", width=0)
    q = queue.Queue()
    state = {"done": False, "frac": 0.0}

    def log(m):
        q.put(("m", m))

    def prog(p):
        q.put(("p", p))

    def work():
        try:
            if miss:
                q.put(("m", "Устанавливаю библиотеки…"))
                engine.pip_install(miss, log)
                engine.load_vlc()
            if need_yt or not engine.yt_dlp:
                log("Загружаю движок поиска (yt-dlp)…")
                engine.update_ytdlp(True, log)
                engine.load_ytdlp()
            if not engine.vlc:
                engine.install_vlc(log, prog)
        except Exception:  # noqa: BLE001
            q.put(("e", traceback.format_exc()))
        q.put(("d", None))

    def poll():
        try:
            while True:
                k, v = q.get_nowait()
                if k == "m":
                    msg.configure(text=v)
                elif k == "p":
                    bar.coords(fill, 0, 0, 380 * v, 8)
                elif k == "e":
                    crash("setup: " + v)
                elif k == "d":
                    state["done"] = True
        except queue.Empty:
            pass
        if state["done"]:
            root.destroy()
        else:
            root.after(80, poll)
    threading.Thread(target=work, daemon=True).start()
    poll()
    root.mainloop()


def main():
    engine.setup_paths()
    miss, need_yt, need_vlc = needs_setup()
    if miss or need_yt or need_vlc:
        run_setup(miss, need_yt, need_vlc)
        engine.load_ytdlp()
        if not engine.vlc:
            engine.load_vlc()
    from okunek.app import App
    App().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        crash(traceback.format_exc())
    finally:
        os._exit(0)  # не ждать зависшие сетевые потоки при выходе
