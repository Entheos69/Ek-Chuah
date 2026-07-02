"""
test_devolucion.py -- Falsadores de G-pre (devolucion.py).

Prueba que la devolucion:
  - clasifica una ref muerta LOAD-BEARING por DNS como sospecha=fabricacion (BLOQUEANTE);
  - clasifica una ref muerta por TIMEOUT/HTTP como sospecha=degradacion;
  - adjunta a cada ref las afirmaciones que sostiene (contexto para el Estratega);
  - escribe el bloque reevaluacion: in-place y lo RETIRA cuando el grano queda limpio;
  - deja el bloque out-of-band: el grano sigue linteando en emision (ingesta lo ignora).

probe FALSO (no toca la red). Tempdirs. Correr: python tests/test_devolucion.py -v
"""
from __future__ import annotations
import os
import sys
import copy
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml                                              # noqa: E402
from devolucion import devolucion, devolucion_archivo, REEV_KEY, FABRICACION, DEGRADACION  # noqa: E402
from prevuelo import OK, DNS, TIMEOUT                    # noqa: E402
import prevuelo                                          # noqa: E402
from materializa_orden import PLACEHOLDER                # noqa: E402
from ingesta import lint                                 # noqa: E402


VIVA = "https://viva.example/a"
MUERTA = "https://muerta.example/b"      # DNS, load-bearing -> fabricacion
COLGADA = "https://colgada.example/c"    # TIMEOUT, no load-bearing -> degradacion


def _probe_falso(url):
    if url == VIVA:
        return OK, "200"
    if url == MUERTA:
        return DNS, "getaddrinfo failed"
    if url == COLGADA:
        return TIMEOUT, "read timeout"
    return prevuelo.ERROR, "?"


def _probe_todo_ok(url):
    return OK, "200"


def _grano():
    def ref(lid, url):
        return {"local_id": lid, "url": url, "content_hash": PLACEHOLDER,
                "capture_ts": PLACEHOLDER, "fecha_fuente": "capture", "estatus": "viva"}
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-07-02-001-Indagacion",
                 "consolidado_por": "PENDIENTE", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1", "premisa": "p", "busqueda": ["q"],
            "resultados_crudos": [{"fuente": "x", "texto": "t"}], "conclusion": "c",
            "inferidor": {"model": "m", "ts": "2026-07-02T00:00:00"}}],
        "necesidad": {"pregunta": "q", "gatillo": "explicito:'x'", "origen_nodo": "n"},
        "consultas": [
            {"formulacion": "f1", "referencias": [ref("r1", VIVA), ref("r2", MUERTA)]},
            {"formulacion": "f2", "referencias": [ref("r3", COLGADA)]}],
        "afirmaciones": [
            {"txt": "el log replicado es la verdad", "tipo": "claim", "estatus": "afirmado",
             "survived_from": "r2", "inferida_por": "i1"}]}}


class Devolucion(unittest.TestCase):
    def test_fabricacion_vs_degradacion(self):
        doc = _grano()
        rep = devolucion(doc, probe=_probe_falso)
        by = {r["local_id"]: r for r in rep["refs"]}
        self.assertNotIn("r1", by, "una ref viva no debe ir a reevaluacion")
        self.assertEqual(by["r2"]["sospecha"], FABRICACION)   # DNS + load-bearing
        self.assertEqual(by["r2"]["severidad"], "BLOQUEANTE")
        self.assertEqual(by["r3"]["sospecha"], DEGRADACION)   # timeout + no load-bearing
        self.assertTrue(rep["hay_sospecha_fabricacion"])

    def test_adjunta_contexto_de_afirmaciones(self):
        doc = _grano()
        rep = devolucion(doc, probe=_probe_falso)
        by = {r["local_id"]: r for r in rep["refs"]}
        self.assertIn("el log replicado es la verdad", by["r2"]["sostiene"])
        self.assertEqual(by["r3"]["sostiene"], [], "r3 no sostiene ninguna afirmacion")

    def test_escribe_bloque_in_place(self):
        doc = _grano()
        devolucion(doc, probe=_probe_falso)
        self.assertIn(REEV_KEY, doc)
        self.assertTrue(doc[REEV_KEY]["sospecha_fabricacion"])
        self.assertEqual(len(doc[REEV_KEY]["refs"]), 2)

    def test_grano_limpio_retira_bloque(self):
        doc = _grano()
        doc[REEV_KEY] = {"stale": True}                       # bloque viejo de una corrida previa
        rep = devolucion(doc, probe=_probe_todo_ok)
        self.assertEqual(rep["refs"], [])
        self.assertNotIn(REEV_KEY, doc, "un grano limpio no debe arrastrar bloque stale")

    def test_out_of_band_no_rompe_lint_emision(self):
        doc = _grano()
        devolucion(doc, probe=_probe_falso)
        # el bloque reevaluacion: es out-of-band -> el lint de emision lo ignora
        self.assertEqual(lint(doc, store=None), [],
                         "el bloque reevaluacion no debe afectar el lint del payload AEC")

    def test_archivo_in_place(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "grano.yaml")
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(_grano(), f, allow_unicode=True)
            rep = devolucion_archivo(path, probe=_probe_falso)
            self.assertEqual(rep["out"], path)
            with open(path, "r", encoding="utf-8") as f:
                reloaded = yaml.safe_load(f)
            self.assertIn(REEV_KEY, reloaded)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
