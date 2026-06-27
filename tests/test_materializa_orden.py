"""
test_materializa_orden.py -- Falsadores del paso 2 sobre una ORDEN YAML-AEC.

Prueba end-to-end: materializar baja la roca a WORM y rellena content_hash/capture_ts; es
idempotente sobre refs ya materializadas; NO puebla graph_aec; y el resultado pasa la ingesta
limpio (pipeline completo orden -> materializa -> ingesta -> graph_aec, huerfanos=0).

fetch FALSO (no toca la red). Tests del axioma que se pagan solos. Tempdirs (durable real intacto).

Correr:  python tests/test_materializa_orden.py -v
"""
from __future__ import annotations
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                       # noqa: E402
from nucleo import content_hash                      # noqa: E402
import proyeccion                                    # noqa: E402
import ingesta                                       # noqa: E402
import materializa_orden                             # noqa: E402
from materializa_orden import materializar_orden, PLACEHOLDER   # noqa: E402


# roca falsa por URL (el fetch real bajaria estos bytes de la web)
PAGINAS = {
    "https://event-driven.io/en/projections_and_read_models_in_event_driven_architecture/":
        b"<html>events are our source of truth; read models as secondary data</html>",
    "https://dev.to/godofgeeks/event-sourcing-pattern-details-1jf8":
        b"<html>Your event store is your ultimate backup.</html>",
    "https://www.inkandswitch.com/local-first-software/":
        b"<html>If a service shuts down, the software stops functioning; sync as offsite backup</html>",
}


def _fake_fetch(url):
    return PAGINAS[url]


def _orden():
    """Una orden como la del Estratega: 3 referencias en 2 consultas, 2 afirmaciones, placeholders."""
    def ref(lid, url):
        return {"local_id": lid, "url": url, "content_hash": PLACEHOLDER,
                "capture_ts": PLACEHOLDER, "fecha_fuente": "capture", "estatus": "viva"}
    urls = list(PAGINAS.keys())
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-06-27-001-Indagacion",
                 "consolidado_por": "PENDIENTE", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1",
            "premisa": "local vs nube parecia binario; ni la nube se pierde ni lo local es seguro solo",
            "busqueda": ["event sourcing rebuild read model projection from event log"],
            "resultados_crudos": [{"fuente": "event-driven.io", "texto": "events are our source of truth"}],
            "conclusion": "El log replicado es la verdad; la proyeccion es desechable.",
            "inferidor": {"model": "estratega/claude-opus-4", "ts": "2026-06-26T14:03:11"}}],
        "necesidad": {"pregunta": "donde debe vivir el lector del grafo",
                      "gatillo": "explicito:'investiga en la web soluciones similares'",
                      "origen_nodo": "decision:A/B/C"},
        "consultas": [
            {"formulacion": "event sourcing rebuild read model projection from event log",
             "referencias": [ref("r1", urls[0]), ref("r2", urls[1])]},
            {"formulacion": "local-first software principles sync survive failure",
             "referencias": [ref("r3", urls[2])]}],
        "afirmaciones": [
            {"txt": "El log replicado es la verdad; la proyeccion es desechable.",
             "tipo": "decision", "estatus": "afirmado", "survived_from": "r1", "inferida_por": "i1"},
            {"txt": "Replicar el log a >=2 sitios hace que ni la nube ni el dano fisico sean perdida total.",
             "tipo": "decision", "estatus": "afirmado", "survived_from": "r3", "inferida_por": "i1"}]}}


class MaterializaOrden(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"))
        self.db = os.path.join(self.tmp, "graph_aec.db")
        self.clock = lambda: "2026-06-27T10:15:00"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- materializa: baja la roca a WORM y rellena los campos locales ----
    def test_materializa_rellena_y_baja_roca(self):
        doc = _orden()
        res = materializar_orden(doc, self.store, fetch=_fake_fetch,
                                 consolidado_por="Guardian", clock=self.clock)
        self.assertEqual(len(res["materializadas"]), 3)
        self.assertEqual(doc["ek_chuah_aec"]["meta"]["consolidado_por"], "Guardian")
        for q in doc["ek_chuah_aec"]["consultas"]:
            for r in q["referencias"]:
                self.assertNotEqual(r["content_hash"], PLACEHOLDER)
                self.assertEqual(r["content_hash"], content_hash(PAGINAS[r["url"]]))
                self.assertEqual(r["capture_ts"], "2026-06-27T10:15:00")
                self.assertTrue(self.store.has_snapshot(r["content_hash"]))

    # ---- NO puebla graph_aec (esa es la ingesta); solo WORM + el doc ----
    def test_no_puebla_graph_aec(self):
        doc = _orden()
        materializar_orden(doc, self.store, fetch=_fake_fetch, clock=self.clock)
        # el log durable sigue sin eventos de via: materializar no emite
        self.assertEqual(sum(1 for _ in self.store.iter_events()), 0)
        # pero los snapshots SI estan en WORM
        snaps = os.listdir(os.path.join(self.store.root, "snapshots"))
        self.assertEqual(len(snaps), 3)

    # ---- idempotente: re-materializar no re-baja refs ya materializadas ----
    def test_idempotente_sobre_ya_materializadas(self):
        doc = _orden()
        materializar_orden(doc, self.store, fetch=_fake_fetch, clock=self.clock)
        bombas = {"boom": True}

        def fetch_explota(url):
            raise AssertionError("re-bajo una ref ya materializada")

        res2 = materializar_orden(doc, self.store, fetch=fetch_explota, clock=self.clock)
        self.assertEqual(len(res2["materializadas"]), 0)
        self.assertEqual(len(res2["ya_materializadas"]), 3)

    # ---- pipeline completo: orden -> materializa -> ingesta -> graph_aec ----
    def test_pipeline_completo_materializa_luego_ingesta(self):
        doc = _orden()
        # antes de materializar: la ingesta DEBE rechazar (C3/C5)
        with self.assertRaises(ingesta.IngestaError):
            ingesta.ingest_doc(_orden(), self.store)
        # materializa -> lint limpio -> ingesta puebla
        materializar_orden(doc, self.store, fetch=_fake_fetch,
                           consolidado_por="Guardian", clock=self.clock)
        self.assertEqual(ingesta.lint(doc, self.store), [])
        res = ingesta.ingest_doc(doc, self.store)
        self.assertGreater(res["appended"], 0)
        cx = proyeccion.reconstruir(self.store, self.db)
        self.assertEqual(len(proyeccion.huerfanos(cx)), 0)
        self.assertEqual(len(proyeccion.load_bearing_inseguras(cx, self.store)), 0)
        # las 2 afirmaciones quedaron con su via completa
        self.assertEqual(len(res["afirmaciones"]), 2)
        for aid in res["afirmaciones"]:
            asc = proyeccion.traza_ascendente(cx, aid)
            self.assertIsNotNone(asc["necesidad"])
            self.assertIsNotNone(asc["version"])
        cx.close()

    # ---- desde archivo: materializa IN-PLACE (un grano = un archivo) -> ingestible ----
    def test_materializar_archivo_in_place(self):
        import yaml
        path = os.path.join(self.tmp, "2026-06-27-001-Indagacion.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(_orden(), f, allow_unicode=True)
        res = materializa_orden.materializar_archivo(
            path, self.store, fetch=_fake_fetch, consolidado_por="Guardian")
        self.assertEqual(res["out"], path, "no materializo in-place")
        with open(path, encoding="utf-8") as f:
            out_doc = yaml.safe_load(f)
        self.assertEqual(ingesta.lint(out_doc, self.store), [], "el grano materializado no pasa lint")


if __name__ == "__main__":
    unittest.main(verbosity=2)
