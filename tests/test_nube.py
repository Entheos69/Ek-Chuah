"""
test_nube.py -- Falsadores de B realineado (nube.py: push + proyeccion atomica).

Prueba, SIN Postgres ni red (conexion DB-API fake):
  - idempotencia: 2a corrida = 0 nuevos y CERO proyeccion (referente_assert no se duplica);
  - solo-lo-nuevo: con shas precargados, los eventos viejos no se re-proyectan;
  - atomicidad: si la proyeccion falla, el push se revierte (rollback, no commit);
  - embeddings: af nuevas se embeben con embed_fn inyectado; sin embed_fn quedan
    contadas en sin_embedding;
  - revision (G-post) genera el UPDATE de estatus tambien en el camino incremental.

Correr:  python tests/test_nube.py -v
"""
from __future__ import annotations
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                   # noqa: E402
from nube import consolidar, embed_gemini, embed_missing   # noqa: E402


# ---- conexion DB-API fake (espeja lo minimo: tx + ON CONFLICT de aec_log) ----

class FakeCursor:
    def __init__(self, cx):
        self.cx = cx
        self.rowcount = 0

    def execute(self, sql, params=None):
        if self.cx.fail_on and self.cx.fail_on in sql:
            raise RuntimeError(f"fallo inyectado en: {self.cx.fail_on}")
        self.cx.tx_executed.append((sql, params))
        if sql.startswith("INSERT INTO aec_log"):
            sha = params[0]
            if sha in self.cx.shas or sha in self.cx.tx_shas:
                self.rowcount = 0
            else:
                self.cx.tx_shas.add(sha)
                self.rowcount = 1
        else:
            self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeCx:
    """Conexion DB-API con semantica psycopg2: `with cx:` = commit al salir bien,
    rollback si hubo excepcion (sin cerrar). Solo simula el UNIQUE de aec_log."""
    def __init__(self, existing_shas=None, fail_on=None):
        self.shas = set(existing_shas or [])     # committed
        self.executed = []                        # committed
        self.tx_shas, self.tx_executed = set(), []
        self.commits = self.rollbacks = 0
        self.fail_on = fail_on
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def __enter__(self):
        self.tx_shas, self.tx_executed = set(), []
        return self

    def __exit__(self, exc_type, *exc):
        if exc_type is None:
            self.shas |= self.tx_shas
            self.executed += self.tx_executed
            self.commits += 1
        else:
            self.rollbacks += 1
        self.tx_shas, self.tx_executed = set(), []
        return False                              # no tragar la excepcion

    def close(self):
        self.closed = True


# ---- log de prueba con todos los tipos de evento ----

def _mk_aec(tmp):
    store = AecStore(os.path.join(tmp, "AEC"), create=True)
    evs = [
        {"ev": "inscripcion", "id": "i1", "premisa": "p", "busqueda": ["q"],
         "resultados_crudos": [{"f": "x"}], "conclusion": "c",
         "inferidor_model": "m", "inferidor_ts": "t", "huella": "h1"},
        {"ev": "necesidad", "id": "n1", "pregunta": "?", "gatillo": "explicito:'x'",
         "origen_nodo": None},
        {"ev": "consulta", "id": "q1", "nec_id": "n1", "formulacion": "f"},
        {"ev": "referencia", "id": "v1", "referente_id": "https://a/", "content_hash": "abc",
         "url_cruda": "https://a/?u=1", "capture_ts": "2026-07-02T10:00:00",
         "fecha_fuente": "capture", "q_id": "q1", "estatus": "viva"},
        {"ev": "afirmacion", "id": "a1", "txt": "el log es la verdad", "insc_id": "i1",
         "ref_id": "v1", "tipo": "claim", "estatus": "afirmado"},
        {"ev": "referente_assert", "id": "ra1", "referente_a": "https://a/",
         "referente_b": "https://b/", "relacion": "mirror", "gatillo": "explicito:'x'"},
        {"ev": "revision", "id": "rv1", "target_af": "a1", "nuevo_estatus": "superada",
         "reemplazada_por": None, "motivo": "m", "gatillo": "explicito:'x'"},
    ]
    for e in evs:
        store.append_event(e)
    return os.path.join(tmp, "AEC"), len(evs)


def _sqls(cx, prefix):
    return [s for s, _ in cx.executed if s.startswith(prefix)]


class Nube(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.aec, self.n = _mk_aec(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_primera_corrida_proyecta_todo(self):
        cx = FakeCx()
        res = consolidar(self.aec, lambda: cx, embed_fn=lambda t: [0.1, 0.2])
        self.assertEqual(res["leidos"], self.n)
        self.assertEqual(res["nuevos"], self.n)
        self.assertEqual(res["afirmaciones_nuevas"], 1)
        self.assertEqual(res["embebidas"], 1)
        self.assertEqual(len(_sqls(cx, "INSERT INTO referente_assert")), 1)
        # revision genero su UPDATE de estatus (G-post por camino incremental)
        ups = [p for s, p in cx.executed if s.startswith("UPDATE afirmacion SET estatus")]
        self.assertEqual(ups, [("superada", "a1")])
        self.assertTrue(cx.closed)

    def test_idempotencia_segunda_corrida_cero(self):
        cx = FakeCx()
        consolidar(self.aec, lambda: cx, embed_fn=None)
        antes = len(cx.executed)
        cx2 = FakeCx(existing_shas=cx.shas)       # misma nube, re-corrida
        res2 = consolidar(self.aec, lambda: cx2, embed_fn=None)
        self.assertEqual(res2["nuevos"], 0, "re-correr no debe empujar nada")
        self.assertEqual(res2["afirmaciones_nuevas"], 0)
        # cero proyeccion en la 2a: en particular referente_assert NO se duplica
        self.assertEqual(len(_sqls(cx2, "INSERT INTO referente_assert")), 0)
        self.assertEqual(len(_sqls(cx2, "INSERT INTO afirmacion")), 0)
        self.assertGreater(antes, 0)

    def test_atomicidad_fallo_en_proyeccion_revierte_push(self):
        cx = FakeCx(fail_on="INSERT INTO referente_assert")
        with self.assertRaises(RuntimeError):
            consolidar(self.aec, lambda: cx, embed_fn=None)
        self.assertEqual(cx.rollbacks, 1)
        self.assertEqual(cx.commits, 0)
        self.assertEqual(cx.shas, set(), "el push debe revertirse con la proyeccion")
        self.assertTrue(cx.closed, "la conexion se cierra aun con fallo")
        # y la re-corrida (nube reparada) recupera TODO -> auto-reparacion
        cx2 = FakeCx()
        res = consolidar(self.aec, lambda: cx2, embed_fn=None)
        self.assertEqual(res["nuevos"], self.n)

    def test_sin_embed_fn_reporta_sin_embedding(self):
        cx = FakeCx()
        res = consolidar(self.aec, lambda: cx, embed_fn=None)
        self.assertEqual(res["embebidas"], 0)
        self.assertEqual(res["sin_embedding"], 1)
        # NO silencioso: el id de la afirmacion sin vector sale nombrado (dir. 8/12)
        self.assertEqual(res["ids_sin_embedding"], ["a1"])
        self.assertEqual(len(_sqls(cx, "UPDATE afirmacion SET embedding")), 0)

    def test_solo_lo_nuevo_se_proyecta(self):
        # 1a corrida con la mitad del log ya en la nube: simular con corrida previa parcial
        cx = FakeCx()
        consolidar(self.aec, lambda: cx, embed_fn=None)
        # agregar un evento NUEVO al log local (grano incremental)
        store = AecStore(self.aec)
        store.append_event({"ev": "afirmacion", "id": "a2", "txt": "nueva", "insc_id": "i1",
                            "ref_id": "v1", "tipo": "claim", "estatus": "afirmado"})
        cx2 = FakeCx(existing_shas=cx.shas)
        res = consolidar(self.aec, lambda: cx2, embed_fn=lambda t: [0.5])
        self.assertEqual(res["nuevos"], 1, "solo el evento nuevo cruza")
        self.assertEqual(res["afirmaciones_nuevas"], 1)
        ins_af = _sqls(cx2, "INSERT INTO afirmacion")
        self.assertEqual(len(ins_af), 1)


# ---- reintento del embed: un flake transitorio NO debe dejar NULL (HANDOFF 2026-11-12) ----

class EmbedReintento(unittest.TestCase):
    def setUp(self):
        self._key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "k-de-prueba"   # pasar el gate permanente

    def tearDown(self):
        if self._key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = self._key

    def test_flake_transitorio_se_recupera(self):
        llamadas = {"n": 0}

        def flaky(text):
            llamadas["n"] += 1
            if llamadas["n"] < 3:
                raise RuntimeError("503 transitorio")
            return [0.1, 0.2]

        out = embed_gemini("hola", attempt=flaky, retries=3, backoff=0)
        self.assertEqual(out, [0.1, 0.2])
        self.assertEqual(llamadas["n"], 3, "reintenta hasta exito")

    def test_fallo_persistente_agota_y_devuelve_none(self):
        llamadas = {"n": 0}

        def siempre_falla(text):
            llamadas["n"] += 1
            raise RuntimeError("Gemini caido")

        out = embed_gemini("hola", attempt=siempre_falla, retries=3, backoff=0)
        self.assertIsNone(out)
        self.assertEqual(llamadas["n"], 3, "agota exactamente los reintentos")

    def test_fallo_permanente_sin_key_no_reintenta(self):
        os.environ.pop("GEMINI_API_KEY", None)
        llamadas = {"n": 0}

        def no_deberia(text):
            llamadas["n"] += 1
            return [9.9]

        out = embed_gemini("hola", attempt=no_deberia, retries=3, backoff=0)
        self.assertIsNone(out)
        self.assertEqual(llamadas["n"], 0, "sin key es permanente: no toca la red")

    def test_texto_vacio_es_permanente(self):
        out = embed_gemini("   ", attempt=lambda t: [1.0], retries=3, backoff=0)
        self.assertIsNone(out)


# ---- backfill embed_missing: solo-NULL, sin TRUNCATE, idempotente, reporta ids ----

class _EmbCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []

    def execute(self, sql, params=None):
        if sql.startswith("SELECT id, txt FROM afirmacion WHERE embedding IS NULL"):
            self._rows = [(i, t) for i, (t, emb) in self.db.rows.items() if emb is None]
        elif sql.startswith("UPDATE afirmacion SET embedding"):
            vec, af_id = params
            t, emb = self.db.rows[af_id]
            if emb is None:                        # AND embedding IS NULL -> idempotente/seguro
                self.db.rows[af_id] = (t, vec)
                self.db.updates += 1

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeEmbCx:
    """DB fake minima para embed_missing: afirmacion id -> (txt, embedding|None)."""
    def __init__(self, rows):
        self.rows = dict(rows)
        self.updates = 0
        self.closed = False

    def cursor(self):
        return _EmbCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self.closed = True


class EmbedMissing(unittest.TestCase):
    def _rows(self):
        return {"a1": ("uno", None), "a2": ("dos", "[0.1]"), "a3": ("tres", None)}

    def test_rellena_solo_los_null(self):
        cx = FakeEmbCx(self._rows())
        res = embed_missing(lambda: cx, embed_fn=lambda t: [0.9])
        self.assertEqual(res["candidatas"], 2, "solo a1 y a3 estaban NULL")
        self.assertEqual(res["embebidas"], 2)
        self.assertEqual(res["fallidas"], 0)
        self.assertEqual(res["ids_fallidas"], [])
        self.assertEqual(cx.rows["a2"][1], "[0.1]", "no toca el que ya tenia vector")
        self.assertNotEqual(cx.rows["a1"][1], None)
        self.assertTrue(cx.closed)

    def test_idempotente_segunda_corrida_cero(self):
        rows = self._rows()
        cx = FakeEmbCx(rows)
        embed_missing(lambda: cx, embed_fn=lambda t: [0.9])
        cx2 = FakeEmbCx(cx.rows)                    # misma DB, re-corrida
        res2 = embed_missing(lambda: cx2, embed_fn=lambda t: [0.9])
        self.assertEqual(res2["candidatas"], 0, "ya no quedan NULL")
        self.assertEqual(res2["embebidas"], 0)
        self.assertEqual(cx2.updates, 0)

    def test_fallo_parcial_reporta_ids(self):
        cx = FakeEmbCx(self._rows())
        res = embed_missing(lambda: cx,
                            embed_fn=lambda t: None if t == "tres" else [0.5])
        self.assertEqual(res["candidatas"], 2)
        self.assertEqual(res["embebidas"], 1)
        self.assertEqual(res["fallidas"], 1)
        self.assertEqual(res["ids_fallidas"], ["a3"], "nombra el que fallo, no mudo")
        self.assertIsNone(cx.rows["a3"][1], "el que fallo sigue NULL (no se inventa vector)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
