"""
test_ingesta.py -- Falsadores del paso 3 (ingesta YAML-AEC -> graph_aec).

Prueba los axiomas operativos end-to-end (no unit del modulo): gate C3 (nace confirmada,
CERO red), idempotencia no-op (E1), huerfanos=0 (I3), I1 rebuild post-ingesta, derivacion
de referente_id (D-schema-1), y los rechazos de lint C1/C2/C4/C5/C6. Tests del axioma que
se pagan solos. NO toca el durable real (tempdirs).

Correr:  python tests/test_ingesta.py -v
"""
from __future__ import annotations
import os
import sys
import copy
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                       # noqa: E402
from nucleo import content_hash                      # noqa: E402
from normaliza_url import referente_id               # noqa: E402
import proyeccion                                    # noqa: E402
import ingesta                                       # noqa: E402
from ingesta import IngestaError, lint, ingest_doc   # noqa: E402


SNAP = b"<html>event sourcing: el log de eventos es la fuente de verdad.</html>"
URL = "https://event-driven.io/projections?utm_source=x#frag"


def _doc(hash_val):
    """YAML-AEC valido (como dict) cuya referencia apunta a hash_val."""
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-06-27-001-Indagacion",
                 "consolidado_por": "Guardian", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1",
            "premisa": "local vs nube parecia binario; ni la nube se pierde ni lo local es seguro solo",
            "busqueda": ["event sourcing rebuild read model projection from event log"],
            "resultados_crudos": [{"fuente": "event-driven.io", "texto": "el log es la verdad; el read model se reconstruye"}],
            "conclusion": "El log replicado es la verdad; la proyeccion es desechable y reconstruible.",
            "inferidor": {"model": "estratega/claude-opus-4", "ts": "2026-06-26T14:03:11"}}],
        "necesidad": {"pregunta": "donde debe vivir el lector del grafo",
                      "gatillo": "explicito:'investiga en la web soluciones similares'",
                      "origen_nodo": "decision:A/B/C-donde-vive-el-lector"},
        "consultas": [{"formulacion": "event sourcing rebuild read model projection from event log",
                       "referencias": [{"local_id": "r1", "url": URL,
                                        "content_hash": hash_val,
                                        "capture_ts": "2026-06-26T14:02:50",
                                        "fecha_fuente": "capture", "estatus": "viva"}]}],
        "afirmaciones": [{"txt": "El log replicado es la verdad; la proyeccion es desechable.",
                          "tipo": "decision", "estatus": "afirmado",
                          "survived_from": "r1", "inferida_por": "i1"}]}}


class Ingesta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"))
        self.db = os.path.join(self.tmp, "ek_chuah.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _materializar(self):
        """Simula el paso 2: la roca baja al WORM. Devuelve su content-hash."""
        return self.store.put_snapshot(SNAP)

    def _n_eventos(self):
        return sum(1 for _ in self.store.iter_events())

    # ---- C3: gate "nace confirmada" -- hash sin snapshot => rechaza, NO toca la BD ----
    def test_C3_gate_rechaza_hash_sin_snapshot(self):
        doc = _doc("sha256:" + "0" * 64)            # nunca se materializo
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)
        self.assertEqual(self._n_eventos(), 0, "fallo C3 pero appendeo eventos (no fallo limpio)")

    # ---- ingesta puebla graph_aec y la via queda completa (I3: huerfanos=0) ----
    def test_ingesta_puebla_graph_aec(self):
        h = self._materializar()
        res = ingest_doc(_doc(h), self.store)
        self.assertGreater(res["appended"], 0)
        cx = proyeccion.reconstruir(self.store, self.db)
        self.assertEqual(len(proyeccion.huerfanos(cx)), 0, "quedo saber sin porque")
        asc = proyeccion.traza_ascendente(cx, res["afirmaciones"][0])
        self.assertEqual(asc["necesidad"]["pregunta"], "donde debe vivir el lector del grafo")
        self.assertEqual(asc["version"]["content_hash"], h)
        self.assertEqual(len(proyeccion.load_bearing_inseguras(cx, self.store)), 0)
        cx.close()

    # ---- C3 tolera el prefijo de algoritmo 'sha256:' ----
    def test_C3_acepta_prefijo_sha256(self):
        h = self._materializar()
        res = ingest_doc(_doc("sha256:" + h), self.store)
        self.assertGreater(res["appended"], 0)
        cx = proyeccion.reconstruir(self.store, self.db)
        # la version persiste el hash crudo (matchea has_snapshot)
        row = cx.execute("SELECT content_hash FROM version").fetchone()
        self.assertEqual(row["content_hash"], h)
        cx.close()

    # ---- E1: re-ingerir el mismo YAML = no-op completo (el log NO crece) ----
    def test_idempotencia_noop(self):
        h = self._materializar()
        doc = _doc(h)
        r1 = ingest_doc(doc, self.store)
        n1 = self._n_eventos()
        cx = proyeccion.reconstruir(self.store, self.db)
        d1 = proyeccion.dump_logico(cx)
        cx.close()

        r2 = ingest_doc(copy.deepcopy(doc), self.store)   # segunda pasada
        self.assertTrue(r2["noop"], "la re-ingesta no fue no-op")
        self.assertEqual(r2["appended"], 0)
        self.assertEqual(self._n_eventos(), n1, "el log crecio en la re-ingesta (no idempotente)")
        cx = proyeccion.reconstruir(self.store, self.db)
        d2 = proyeccion.dump_logico(cx)
        cx.close()
        self.assertEqual(d1, d2, "la proyeccion difirio tras re-ingerir")
        self.assertEqual(r1["afirmaciones"], r2["afirmaciones"], "ids no deterministas")

    # ---- I1: borrar graph_aec y reconstruir del log = identico, tras ingesta ----
    def test_I1_rebuild_post_ingesta(self):
        h = self._materializar()
        ingest_doc(_doc(h), self.store)
        cx1 = proyeccion.reconstruir(self.store, self.db)
        d1 = proyeccion.dump_logico(cx1)
        cx1.close()
        os.remove(self.db)
        cx2 = proyeccion.reconstruir(self.store, self.db)
        d2 = proyeccion.dump_logico(cx2)
        cx2.close()
        self.assertEqual(d1, d2)

    # ---- D-schema-1: referente_id se DERIVA si el YAML no lo declara ----
    def test_referente_id_derivado(self):
        h = self._materializar()
        ingest_doc(_doc(h), self.store)               # r1 omite referente_id
        cx = proyeccion.reconstruir(self.store, self.db)
        row = cx.execute("SELECT referente_id FROM version").fetchone()
        self.assertEqual(row["referente_id"], referente_id(URL),
                         "la ingesta no derivo el referente canonico")
        cx.close()

    # ---- C1: sin la clave raiz ----
    def test_C1_rechaza_sin_root_key(self):
        self.assertTrue(any(e.startswith("C1") for e in lint({}, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc({"otro": {}}, self.store)

    # ---- C2: inscripcion sin tripleta ----
    def test_C2_rechaza_inscripcion_sin_tripleta(self):
        h = self._materializar()
        doc = _doc(h)
        doc["ek_chuah_aec"]["inscripciones"][0]["busqueda"] = []
        self.assertTrue(any(e.startswith("C2") for e in lint(doc, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)
        self.assertEqual(self._n_eventos(), 0)

    # ---- C4: afirmacion huerfana (survived_from no resuelve) ----
    def test_C4_rechaza_afirmacion_huerfana(self):
        h = self._materializar()
        doc = _doc(h)
        doc["ek_chuah_aec"]["afirmaciones"][0]["survived_from"] = "rX"
        self.assertTrue(any(e.startswith("C4") for e in lint(doc, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)

    # ---- C5: capture_ts malformado (no-ISO / mtime disfrazado) ----
    def test_C5_rechaza_capture_ts_malformado(self):
        h = self._materializar()
        doc = _doc(h)
        doc["ek_chuah_aec"]["consultas"][0]["referencias"][0]["capture_ts"] = "ayer"
        self.assertTrue(any(e.startswith("C5") for e in lint(doc, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)

    # ---- C6: gatillo malformado (sin sello de sancion D2) ----
    def test_C6_rechaza_gatillo_malformado(self):
        h = self._materializar()
        doc = _doc(h)
        doc["ek_chuah_aec"]["necesidad"]["gatillo"] = "haz esto"
        self.assertTrue(any(e.startswith("C6") for e in lint(doc, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)

    # ---- ingesta desde archivo (camino yaml.safe_load + CLI) ----
    def test_ingest_desde_archivo(self):
        import yaml
        h = self._materializar()
        path = os.path.join(self.tmp, "grano.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(_doc(h), f, allow_unicode=True)
        res = ingesta.ingest(path, self.store, self.db)
        self.assertEqual(res["huerfanos"], 0)
        self.assertGreater(res["appended"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
