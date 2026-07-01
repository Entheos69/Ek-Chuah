"""
test_consumido.py -- Falsadores del estado de consumo (¿un grano ya fue ingerido?).

Prueba los tres estados (CONSUMIDO / NO-CONSUMIDO / PARCIAL) contra el log real, y el
axioma que sostiene la utilidad: 'consumido' == 'la ingesta seria no-op'. Read-only, no
toca la red. Reusa el _doc valido de test_ingesta (misma roca). NO toca el durable real.

Correr:  python tests/test_consumido.py -v
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
from ingesta import ingest_doc                       # noqa: E402
from consumido import (estado_doc, CONSUMIDO,        # noqa: E402
                       NO_CONSUMIDO, PARCIAL, VACIO)
from test_ingesta import _doc, SNAP                  # noqa: E402


class Consumido(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ingerir(self):
        h = self.store.put_snapshot(SNAP)            # simula el paso 2
        doc = _doc(h)
        ingest_doc(doc, self.store)
        return doc

    # ---- un grano nunca ingerido: NO-CONSUMIDO, presentes=0 ----
    def test_no_consumido(self):
        rep = estado_doc(_doc("sha256:" + "0" * 64), self.store)
        self.assertEqual(rep["estado"], NO_CONSUMIDO)
        self.assertEqual(rep["presentes"], 0)
        self.assertGreater(rep["total"], 0)
        self.assertEqual(len(rep["faltantes"]), rep["total"])

    # ---- tras ingerir: CONSUMIDO, sin faltantes ----
    def test_consumido_tras_ingerir(self):
        doc = self._ingerir()
        rep = estado_doc(doc, self.store)
        self.assertEqual(rep["estado"], CONSUMIDO)
        self.assertEqual(rep["presentes"], rep["total"])
        self.assertEqual(rep["faltantes"], [])

    # ---- AXIOMA: consumido <=> la ingesta es no-op (misma fuente de ids) ----
    def test_consumido_sii_ingesta_noop(self):
        doc = self._ingerir()
        self.assertEqual(estado_doc(doc, self.store)["estado"], CONSUMIDO)
        r2 = ingest_doc(copy.deepcopy(doc), self.store)
        self.assertTrue(r2["noop"], "consumido pero la ingesta no fue no-op: los ids driftan")
        self.assertEqual(r2["appended"], 0)

    # ---- editar el grano tras ingerir rompe el match de esa afirmacion: PARCIAL ----
    def test_parcial_tras_editar_afirmacion(self):
        doc = self._ingerir()
        editado = copy.deepcopy(doc)
        editado["ek_chuah_aec"]["afirmaciones"][0]["txt"] = "texto distinto tras ingerir"
        rep = estado_doc(editado, self.store)
        self.assertEqual(rep["estado"], PARCIAL)
        self.assertGreater(rep["presentes"], 0)
        self.assertEqual(len(rep["faltantes"]), 1)
        self.assertEqual(rep["faltantes"][0]["ev"], "afirmacion")

    # ---- doc no-AEC no deriva eventos: VACIO (no explota) ----
    def test_vacio_no_aec(self):
        rep = estado_doc({"otra_cosa": {}}, self.store)
        self.assertEqual(rep["estado"], VACIO)
        self.assertEqual(rep["total"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
