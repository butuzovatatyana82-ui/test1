"""Хранилище библиотеки: JSON с атомарной записью и индексами для быстрого поиска."""
import json
import os
import uuid

from .config import ALIAS, APP, DATA, DEFAULT_SETTINGS, OLD, SOURCES


class Store:
    def __init__(self):
        self.d = {"tracks": [], "pls": [], "set": {}, "follow": []}
        for p in (DATA, os.path.join(OLD, "data.json")):  # поддержка библиотеки старых версий
            try:
                with open(p, encoding="utf-8") as f:
                    self.d.update(json.load(f))
                break
            except Exception:  # noqa: BLE001
                pass
        s = self.d["set"]
        for k, v in DEFAULT_SETTINGS.items():
            s.setdefault(k, v)
        s["theme"] = ALIAS.get(s["theme"], s["theme"])
        if s["src"] not in SOURCES:
            s["src"] = DEFAULT_SETTINGS["src"]
        self.reindex()

    # индексы: поиск трека по id / источнику за O(1) вместо перебора списка
    def reindex(self):
        self.by_id = {t["id"]: t for t in self.d["tracks"]}
        self.by_src = {t["src"]: t for t in self.d["tracks"]}

    @property
    def tracks(self):
        return self.d["tracks"]

    @property
    def settings(self):
        return self.d["set"]

    def get(self, i):
        return self.by_id.get(i)

    def ensure(self, t):
        x = self.by_id.get(t["id"]) or self.by_src.get(t["src"])
        if x:
            return x
        self.d["tracks"].append(t)
        self.by_id[t["id"]] = t
        self.by_src[t["src"]] = t
        return t

    def remove(self, ids):
        self.d["tracks"] = [t for t in self.d["tracks"] if t["id"] not in ids]
        for p in self.d["pls"]:
            p["ids"] = [i for i in p["ids"] if i not in ids]
        self.reindex()

    def new_playlist(self, name):
        p = {"id": uuid.uuid4().hex[:10], "name": name, "ids": []}
        self.d["pls"].append(p)
        return p

    def playlist(self, i):
        return next((p for p in self.d["pls"] if p["id"] == i), None)

    def save(self):
        os.makedirs(APP, exist_ok=True)
        keep = {k: v for k, v in self.d.items()}
        with open(DATA + ".tmp", "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False)
        os.replace(DATA + ".tmp", DATA)
