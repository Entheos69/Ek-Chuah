"""
test_revision.py -- Falsadores de G-post: reconsideracion del camino epistemico.

Prueba que una revision (evento append-only, emitida via bloque revisiones: del YAML o via
ViaEmision.revision):
  - voltea el estatus efectivo de la afirmacion target al reconstruir (superada/retractada);
  - NO borra la afirmacion (Forma-vs-Valor): la fila persiste, sale de la vista vigente;
  - es idempotente (re-ingerir la misma revision = no-op) y respeta I1 (rebuild identico);
  - C8 rechaza revisiones malformadas y las que apuntan a una afirmacion inexistente.

Tempdirs (durable real intacto). Correr: python tests/test_revision.py -v
"""
from __future__ import annotations
import os
import sys
import copy
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                                 # noqa: E402
from via_epistemica import ViaEmision                          # noqa: E402
import proyeccion                                              # noqa: E402
from ingesta import lint, ingest_doc, IngestaError            # noqa: E402


SNAP = b"<html>event sourcing: el log es la verdad.</html>"
URL = "https://event-driven.io/projections"


def _grano_base(hash_val):
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-07-02-base-Indagacion",
                 "consolidado_por": "Guardian", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1", "premisa": "local vs nube parecia binario",
            "busqueda": ["event sourcing rebuild read model"],
            "resultados_crudos": [{"fuente": "event-driven.io", "texto": "el log es la verdad"}],
            "conclusion": "El log es la verdad; la proyeccion es desechable.",
            "inferidor": {"model": "estratega/opus", "ts": "2026-07-02T10:00:00"}}],
        "necesidad": {"pregunta": "donde vive el lector", "gatillo": "explicito:'investiga'",
                      "origen_nodo": "decision:donde-vive"},
        "consultas": [{"formulacion": "event sourcing rebuild read model",
                       "referencias": [{"local_id": "r1", "url": URL, "content_hash": hash_val,
                                        "capture_ts": "2026-07-02T09:59:00",
                                        "fecha_fuente": "capture", "estatus": "viva"}]}],
        "afirmaciones": [{"txt": "El log replicado es la verdad.", "tipo": "decision",
                          "estatus": "afirmado", "survived_from": "r1", "inferida_por": "i1"}]}}


def _grano_revision(target_af, nuevo_estatus="superada", gatillo="explicito:'reconsidera'"):
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-07-02-rev-Indagacion",
                 "consolidado_por": "Guardian", "project": "ek-chuah"},
        "necesidad": {"pregunta": "la fuente sigue viva?", "gatillo": "explicito:'revisa la roca'",
                      "origen_nodo": "reconsideracion"},
        "revisiones": [{"target_af": target_af, "nuevo_estatus": nuevo_estatus,
                        "motivo": "la fuente murio; sustituida", "gatillo": gatillo}]}}


class Revision(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"), create=True)
        self.db = os.path.join(self.tmp, "ek_chuah.db")
        h = self.store.put_snapshot(SNAP)
        self.base = ingest_doc(_grano_base(h), self.store)
        self.af_id = self.base["afirmaciones"][0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rebuild(self):
        return proyeccion.reconstruir(self.store, self.db)

    def test_revision_voltea_estatus_sin_borrar(self):
        ingest_doc(_grano_revision(self.af_id, "superada"), self.store)
        cx = self._rebuild()
        row = cx.execute("SELECT estatus FROM afirmacion WHERE id=?", (self.af_id,)).fetchone()
        self.assertEqual(row["estatus"], "superada", "la revision no volteo el estatus")
        # NO se borro (Forma-vs-Valor)
        self.assertIsNotNone(row, "la afirmacion superada no debe desaparecer")
        vigentes = [r["id"] for r in proyeccion.afirmaciones_vigentes(cx)]
        self.assertNotIn(self.af_id, vigentes, "la superada no debe estar en la vista vigente")
        # historial auditado disponible
        hist = proyeccion.revisiones_de(cx, self.af_id)
        self.assertEqual(hist[0]["nuevo_estatus"], "superada")
        cx.close()

    def test_traza_expone_estatus(self):
        ingest_doc(_grano_revision(self.af_id, "retractada"), self.store)
        cx = self._rebuild()
        asc = proyeccion.traza_ascendente(cx, self.af_id)
        self.assertEqual(asc["estatus"], "retractada")
        cx.close()

    def test_idempotente_y_I1(self):
        doc = _grano_revision(self.af_id, "superada")
        ingest_doc(doc, self.store)
        n1 = sum(1 for _ in self.store.iter_events())
        cx = self._rebuild(); d1 = proyeccion.dump_logico(cx); cx.close()
        r2 = ingest_doc(copy.deepcopy(doc), self.store)          # re-ingesta
        self.assertTrue(r2["noop"], "re-ingerir la revision no fue no-op")
        self.assertEqual(sum(1 for _ in self.store.iter_events()), n1, "el log crecio")
        os.remove(self.db)
        cx = self._rebuild(); d2 = proyeccion.dump_logico(cx); cx.close()
        self.assertEqual(d1, d2, "I1: rebuild difirio tras re-ingesta")

    def test_C8_rechaza_estatus_invalido(self):
        doc = _grano_revision(self.af_id, "borrada")             # no valido
        self.assertTrue(any(e.startswith("C8") for e in lint(doc, self.store)))
        with self.assertRaises(IngestaError):
            ingest_doc(doc, self.store)

    def test_C8_rechaza_gatillo_malformado(self):
        doc = _grano_revision(self.af_id, "superada", gatillo="hazlo")
        self.assertTrue(any(e.startswith("C8") for e in lint(doc, self.store)))

    def test_C8_rechaza_target_inexistente(self):
        doc = _grano_revision("af_que_no_existe", "superada")
        errs = lint(doc, self.store)                             # fase ingesta: resuelve target
        self.assertTrue(any(e.startswith("C8") and "no resuelve" in e for e in errs))
        # en emision (sin store) NO se puede resolver el target -> estructural pasa
        self.assertFalse(any("no resuelve" in e for e in lint(doc, store=None)))

    def test_via_revision_valida_estatus(self):
        via = ViaEmision(self.store)
        with self.assertRaises(ValueError):
            via.revision(self.af_id, "borrada", gatillo="explicito:'x'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
