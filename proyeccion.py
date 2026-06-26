"""
proyeccion.py -- Reconstruye la proyeccion SQLite del log durable (forma Q) + consultas.

La .db es DESECHABLE: se borra y se reconstruye SIEMPRE del log (falsador I1). Ningun
timestamp ni id se inventa aqui; todo viene del log => reconstruir N veces da el MISMO
contenido logico. Es C0 hecho codigo.

"Version actual" es VISTA DERIVADA (I4): el ultimo capture_ts por referente, no un flag
persistido que se voltea.

Lado LECTURA (CQRS): traza, huerfanos, disponibilidad I2, version_actual.

Solo stdlib.
"""
from __future__ import annotations
import sqlite3
import os
import json


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


SCHEMA = """
CREATE TABLE inscripcion(id TEXT PRIMARY KEY, premisa TEXT, busqueda TEXT,
    resultados_crudos TEXT, conclusion TEXT, inferidor_model TEXT, inferidor_ts TEXT,
    huella TEXT, ts TEXT);
CREATE TABLE necesidad(id TEXT PRIMARY KEY, pregunta TEXT, gatillo TEXT,
    origen_nodo TEXT, ts TEXT);
CREATE TABLE consulta(id TEXT PRIMARY KEY, nec_id TEXT, formulacion TEXT, ts TEXT);
CREATE TABLE referente(referente_id TEXT PRIMARY KEY, primera_captura TEXT);
CREATE TABLE version(id TEXT PRIMARY KEY, referente_id TEXT, content_hash TEXT,
    url_cruda TEXT, capture_ts TEXT, fecha_fuente TEXT, q_id TEXT, ts TEXT);
CREATE TABLE afirmacion(id TEXT PRIMARY KEY, txt TEXT, insc_id TEXT, ref_id TEXT,
    tipo TEXT, estatus TEXT, ts TEXT);
CREATE TABLE referente_assert(id TEXT, referente_a TEXT, referente_b TEXT,
    relacion TEXT, gatillo TEXT, ts TEXT);
CREATE INDEX ix_ver_ref ON version(referente_id);
CREATE INDEX ix_ins_huella ON inscripcion(huella);
"""


def reconstruir(store, db_path: str) -> sqlite3.Connection:
    """Borra y reconstruye la .db del log. Idempotente y determinista."""
    if os.path.exists(db_path):
        os.remove(db_path)
    cx = sqlite3.connect(db_path)
    cx.row_factory = sqlite3.Row
    cx.executescript(SCHEMA)
    for ev in store.iter_events():
        kind = ev.get("ev")
        ts = ev.get("ts")
        if kind == "inscripcion":
            cx.execute("INSERT OR IGNORE INTO inscripcion VALUES(?,?,?,?,?,?,?,?,?)",
                       (ev["id"], ev["premisa"], _j(ev["busqueda"]), _j(ev["resultados_crudos"]),
                        ev["conclusion"], ev["inferidor_model"], ev["inferidor_ts"],
                        ev["huella"], ts))
        elif kind == "necesidad":
            cx.execute("INSERT OR IGNORE INTO necesidad VALUES(?,?,?,?,?)",
                       (ev["id"], ev["pregunta"], ev["gatillo"], ev.get("origen_nodo"), ts))
        elif kind == "consulta":
            cx.execute("INSERT OR IGNORE INTO consulta VALUES(?,?,?,?)",
                       (ev["id"], ev["nec_id"], ev["formulacion"], ts))
        elif kind == "referencia":
            ref = ev["referente_id"]
            cx.execute("INSERT OR IGNORE INTO referente VALUES(?,?)", (ref, ev["capture_ts"]))
            # primera_captura = min(capture_ts): orden-independiente
            cx.execute("UPDATE referente SET primera_captura=? "
                       "WHERE referente_id=? AND primera_captura>?",
                       (ev["capture_ts"], ref, ev["capture_ts"]))
            cx.execute("INSERT OR IGNORE INTO version VALUES(?,?,?,?,?,?,?,?)",
                       (ev["id"], ref, ev["content_hash"], ev["url_cruda"],
                        ev["capture_ts"], ev["fecha_fuente"], ev["q_id"], ts))
        elif kind == "afirmacion":
            cx.execute("INSERT OR IGNORE INTO afirmacion VALUES(?,?,?,?,?,?,?)",
                       (ev["id"], ev["txt"], ev["insc_id"], ev.get("ref_id"),
                        ev["tipo"], ev["estatus"], ts))
        elif kind == "referente_assert":
            cx.execute("INSERT INTO referente_assert VALUES(?,?,?,?,?,?)",
                       (ev["id"], ev["referente_a"], ev["referente_b"],
                        ev["relacion"], ev["gatillo"], ts))
    cx.commit()
    return cx


# ---- vistas derivadas / consultas (lado lectura) ----

def version_actual(cx, referente_id: str):
    """I4: la version mas reciente por capture_ts. Vista derivada, no flag."""
    return cx.execute(
        "SELECT * FROM version WHERE referente_id=? ORDER BY capture_ts DESC, id DESC LIMIT 1",
        (referente_id,)).fetchone()


def huerfanos(cx):
    """Afirmaciones sin via (sin referencia o sin inscripcion): saber sin su porque."""
    return cx.execute(
        "SELECT id, txt FROM afirmacion WHERE ref_id IS NULL OR insc_id IS NULL").fetchall()


def load_bearing_inseguras(cx, store):
    """I2: afirmaciones afirmadas cuya version referida NO tiene snapshot en AEC."""
    rows = cx.execute(
        "SELECT a.id AS aid, v.content_hash AS h FROM afirmacion a "
        "JOIN version v ON a.ref_id = v.id WHERE a.estatus='afirmado'").fetchall()
    return [r["aid"] for r in rows if not store.has_snapshot(r["h"])]


def traza_ascendente(cx, af_id: str) -> dict:
    """De una afirmacion a la necesidad que la engendro (lectura trae el porque)."""
    a = cx.execute("SELECT * FROM afirmacion WHERE id=?", (af_id,)).fetchone()
    if a is None:
        raise KeyError(af_id)
    out = {"afirmacion": a["txt"], "inferencia": None, "version": None,
           "consulta": None, "necesidad": None}
    if a["insc_id"]:
        i = cx.execute("SELECT * FROM inscripcion WHERE id=?", (a["insc_id"],)).fetchone()
        if i:
            out["inferencia"] = {"conclusion": i["conclusion"],
                                 "inferida_por": f'{i["inferidor_model"]}@{i["inferidor_ts"]}',
                                 "huella": i["huella"][:12]}
    if a["ref_id"]:
        v = cx.execute("SELECT * FROM version WHERE id=?", (a["ref_id"],)).fetchone()
        if v:
            out["version"] = {"referente_id": v["referente_id"], "content_hash": v["content_hash"],
                              "url_cruda": v["url_cruda"], "capture_ts": v["capture_ts"]}
            q = cx.execute("SELECT * FROM consulta WHERE id=?", (v["q_id"],)).fetchone()
            if q:
                out["consulta"] = q["formulacion"]
                n = cx.execute("SELECT * FROM necesidad WHERE id=?", (q["nec_id"],)).fetchone()
                if n:
                    out["necesidad"] = {"pregunta": n["pregunta"], "gatillo": n["gatillo"],
                                        "ancla": n["origen_nodo"]}
    return out


def dump_logico(cx) -> list:
    """Volcado canonico (filas ordenadas) para comparar reconstrucciones (falsador I1)."""
    out = []
    tablas = ["inscripcion", "necesidad", "consulta", "referente",
              "version", "afirmacion", "referente_assert"]
    for t in tablas:
        rows = cx.execute(f"SELECT * FROM {t}").fetchall()
        out.append((t, sorted(tuple(r) for r in rows)))
    return out
