"""
test_aec_verify.py -- Falsadores del gate pre-emision del Estratega.

Dos ejes:
  1. VERBATIM (V1/V2/V3): lo unico que aec_verify puede hacer y la ingesta no -- cotejar el
     texto del grano contra los BYTES capturados. Replica el Caso A (disciplinado, APTO) y
     el Caso B (anti-patrones sembrados, RETENIDO) del dictamen 2026-08-19.
  2. DELEGACION sin drift: los checks estructurales (C0/C2/C3-emision) NO se reimplementan;
     salen de ingesta.lint/basename_ok. Los tests lo prueban forzando cada uno y exigiendo
     que aec_verify los reporte -- si la delegacion se rompe, estos fallan.

NO toca red ni durable (tempdirs). Correr: python tests/test_aec_verify.py -v
"""
from __future__ import annotations
import os
import sys
import copy
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml                          # noqa: E402
import aec_verify                    # noqa: E402
from aec_verify import verificar     # noqa: E402

SID = "2026-08-18-001-Indagacion"
URL = "https://railway.com/pricing"
# La captura del DOM: los extractos verbatim deben ser substring de esto (con ruido alrededor).
CAPTURA = ("Railway pricing. Hobby $5 minimum usage per month. Pro plan available. "
           "99.9% Availability Target for production workloads.")


def _doc():
    """Grano pre-emision disciplinado (placeholders MATERIALIZAR, extractos literales)."""
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": SID,
                 "consolidado_por": "PENDIENTE", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1",
            "premisa": "verificar si el tier de precios Railway sigue vigente antes de pesarlo",
            "busqueda": ["railway pricing hobby pro minimum usage 2026"],
            "resultados_crudos": [
                {"fuente": "railway.com/pricing", "texto": "Hobby $5 minimum usage"},
                {"fuente": "railway.com/pricing", "texto": "99.9% Availability Target"}],
            "conclusion": "Los dos componentes del claim siguen publicados sin cambio.",
            "inferidor": {"model": "estratega/claude-opus-5", "ts": "2026-08-18T22:52:00-06:00"}}],
        "necesidad": {"pregunta": "sigue vigente el tier de precios Railway del claim previo?",
                      "gatillo": "explicito:'podemos mejorar su alcance'", "origen_nodo": None},
        "consultas": [{"formulacion": "railway pricing hobby pro minimum usage 2026",
                       "referencias": [{"local_id": "r1", "url": URL,
                                        "content_hash": "MATERIALIZAR",
                                        "capture_ts": "MATERIALIZAR",
                                        "fecha_fuente": "capture", "estatus": "viva"}]}],
        "afirmaciones": [{"txt": "Railway mantiene Hobby en $5 con target 99.9% al 2026-08-19.",
                          "tipo": "claim", "estatus": "afirmado",
                          "survived_from": "r1", "inferida_por": "i1"}]}}


class AecVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _escribir(self, doc, stem=SID):
        """Escribe el grano a <stem>.yaml (el stem importa para C0)."""
        path = os.path.join(self.tmp, f"{stem}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(doc, f, allow_unicode=True)
        return path

    def _codes(self, rep):
        return {c for c, _ in rep.fallos}

    # ---- la delegacion esta activa (sin ella, la mitad de estos tests no probaria nada) ----
    def test_repo_importable(self):
        self.assertTrue(aec_verify._HAS_REPO, "ingesta no importable: la delegacion estructural no corre")

    # ---- CASO A: disciplinado + captura literal -> APTO, con testigo ----
    def test_caso_A_disciplinado_apto(self):
        rep = verificar(self._escribir(_doc()), {URL: CAPTURA})
        self.assertTrue(rep.ok, f"Caso A deberia ser APTO; fallos={rep.fallos}")
        self.assertTrue(rep.testigos, "un extracto literal debe dejar testigo (sha de la captura)")

    # ---- V1: extracto NO literal en la captura -> sintesis (anti-patron #1) ----
    def test_V1_verbatim_caza_sintesis(self):
        doc = _doc()
        doc["ek_chuah_aec"]["inscripciones"][0]["resultados_crudos"][0]["texto"] = \
            "Railway cuesta alrededor de cinco dolares"   # parafrasis, no esta en el DOM
        rep = verificar(self._escribir(doc), {URL: CAPTURA})
        self.assertIn("V1", self._codes(rep), "el extracto sintetizado debe fallar V1")

    # ---- V1 sin captura: no puede afirmar verbatim -> aviso, no fallo ----
    def test_V1_sin_captura_es_aviso(self):
        rep = verificar(self._escribir(_doc()), None)
        self.assertTrue(any(c == "V1" for c, _ in rep.avisos), "sin captura V1 debe avisar")
        self.assertNotIn("V1", self._codes(rep), "sin captura V1 no debe FALLAR")

    # ---- V2: extracto de >=15 palabras (copyright) ----
    def test_V2_extracto_largo(self):
        doc = _doc()
        largo = " ".join(f"palabra{k}" for k in range(20))
        doc["ek_chuah_aec"]["inscripciones"][0]["resultados_crudos"][0]["texto"] = largo
        rep = verificar(self._escribir(doc), {URL: CAPTURA + " " + largo})
        self.assertIn("V2", self._codes(rep), "un extracto de 20 palabras debe fallar V2")

    # ---- DELEGACION C0: basename != session_id (viene de basename_ok) ----
    def test_delegacion_C0_identidad_doble(self):
        rep = verificar(self._escribir(_doc(), stem="otro-nombre"), {URL: CAPTURA})
        self.assertIn("C0", self._codes(rep), "C0 debe delegarse a basename_ok")

    # ---- DELEGACION C2: sin inferidor (viene de ingesta.lint; era el drift de la v1) ----
    def test_delegacion_C2_inferidor(self):
        doc = _doc()
        del doc["ek_chuah_aec"]["inscripciones"][0]["inferidor"]
        rep = verificar(self._escribir(doc), {URL: CAPTURA})
        self.assertIn("C2", self._codes(rep),
                      "C2 (inferidor) debe delegarse a ingesta.lint, no reimplementarse")

    # ---- DELEGACION C3-emision: hash real cruza la membrana MATERIALIZAR ----
    def test_delegacion_C3_membrana_materializar(self):
        doc = _doc()
        doc["ek_chuah_aec"]["consultas"][0]["referencias"][0]["content_hash"] = "a" * 64
        rep = verificar(self._escribir(doc), {URL: CAPTURA})
        self.assertIn("C3", self._codes(rep),
                      "un content_hash real en emision debe fallar C3 via ingesta.lint")

    # ---- AVISO coherencia: formulacion sin busqueda literal gemela (no bloquea) ----
    def test_aviso_coherencia_formulacion(self):
        doc = _doc()
        doc["ek_chuah_aec"]["consultas"][0]["formulacion"] = "una formulacion totalmente distinta"
        rep = verificar(self._escribir(doc), {URL: CAPTURA})
        self.assertTrue(any(c == "coherencia" for c, _ in rep.avisos),
                        "formulacion divergente debe AVISAR")
        self.assertTrue(rep.ok, "la coherencia es aviso, no debe retener el grano")

    # ---- AVISO derivado: declarar referente_id (ingesta lo tolera) -> aviso, no fallo ----
    def test_aviso_campo_derivado(self):
        doc = _doc()
        doc["ek_chuah_aec"]["consultas"][0]["referencias"][0]["referente_id"] = "https://railway.com/pricing"
        rep = verificar(self._escribir(doc), {URL: CAPTURA})
        self.assertTrue(any(c == "D2" for c, _ in rep.avisos), "referente_id debe AVISAR (D2)")
        self.assertTrue(rep.ok, "un derivado tolerado por ingesta no debe RETENER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
