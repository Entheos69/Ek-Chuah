"""
aec_store.py -- El materializador: UNICO escritor append-only del durable AEC (forma Q).

Durable = log JSONL append-only (la verdad) + snapshots content-addressed (las rocas).
WORM POR CONSTRUCCION: solo existen verbos de APPEND; NO hay update ni delete. El snapshot
se escribe solo si no existe (idempotente: mismo content-hash = no-op). El log solo se abre
en modo append ('a').

AEC vive FUERA de todo repo (hermano del repo: ../AEC) -> "no committeable/pusheable" por topologia,
no por .gitignore.

Solo stdlib. Sin emojis (encoding Windows).
"""
from __future__ import annotations
import os
import json
import datetime
from nucleo import ISO, content_hash


class AecStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.log_dir = os.path.join(self.root, "log")
        self.snap_dir = os.path.join(self.root, "snapshots")
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.snap_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "inscripciones.jsonl")

    # ---- append-only: el unico verbo de escritura del log ----
    def append_event(self, event: dict) -> dict:
        ev = dict(event)
        if "ts" not in ev:
            ev["ts"] = datetime.datetime.now().strftime(ISO)
        line = json.dumps(ev, ensure_ascii=False, sort_keys=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return ev

    # ---- snapshot content-addressed: WORM idempotente ----
    def put_snapshot(self, data: bytes) -> str:
        h = content_hash(data)
        path = os.path.join(self.snap_dir, h)
        if not os.path.exists(path):           # nunca sobre-escribe
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)              # publicacion atomica
        return h

    def has_snapshot(self, h: str) -> bool:
        return os.path.exists(os.path.join(self.snap_dir, h))

    def read_snapshot(self, h: str) -> bytes:
        with open(os.path.join(self.snap_dir, h), "rb") as f:
            return f.read()

    # ---- lectura del log (para reconstruir la proyeccion) ----
    def iter_events(self):
        if not os.path.exists(self.log_path):
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
