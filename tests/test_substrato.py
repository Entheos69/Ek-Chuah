"""
test_substrato.py -- Falsadores del substrato AEC greenfield (forma Q).

Prueba los axiomas operativos end-to-end (no unit del modulo): I1, I2, I4, WORM,
invariante de la tripleta, huerfanos. Tests del axioma que se pagan solos.

Correr:  python tests/test_substrato.py -v
"""
from __future__ import annotations
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                      # noqa: E402
from via_epistemica import ViaEmision               # noqa: E402
from nucleo import Inscripcion, Inferidor           # noqa: E402
from normaliza_url import canonical, referente_id   # noqa: E402
import proyeccion                                   # noqa: E402


class Substrato(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"))
        self.db = os.path.join(self.tmp, "ek_chuah.db")
        self.via = ViaEmision(self.store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _inferidor(self):
        return Inferidor("modelo-x", "2026-06-26T00:00:00")

    def _sembrar(self):
        nec = self.via.necesidad("donde vive el lector", "explicito:'investiga'", "decision:ABC")
        q = self.via.consulta(nec, "event sourcing rebuild projection")
        h = self.store.put_snapshot(b"<html>event sourcing v1</html>")
        ref = self.via.referencia(q, "https://event-driven.io/projections?utm_source=x#frag",
                                  h, capture_ts="2026-06-01T00:00:00")
        ins = self.via.inscripcion(Inscripcion(
            "premisa X", ["q1"], [{"fuente": "a", "texto": "b"}], "lectura Y", self._inferidor()))
        af = self.via.afirmacion("el log es la verdad", ins, ref, "decision")
        return nec, q, ref, ins, af, h

    # ---- I1: borrar y reconstruir = identico (el falsador que DEFINE C0) ----
    def test_I1_rebuild_identico(self):
        self._sembrar()
        cx1 = proyeccion.reconstruir(self.store, self.db)
        d1 = proyeccion.dump_logico(cx1)
        cx1.close()
        cx2 = proyeccion.reconstruir(self.store, self.db)   # borra la .db y rehace
        d2 = proyeccion.dump_logico(cx2)
        cx2.close()
        self.assertEqual(d1, d2, "reconstruir dos veces difiere")
        os.remove(self.db)                                  # borrado explicito del archivo
        cx3 = proyeccion.reconstruir(self.store, self.db)
        d3 = proyeccion.dump_logico(cx3)
        cx3.close()
        self.assertEqual(d1, d3, "reconstruir tras borrar el archivo difiere")

    # ---- I4: afirmacion anclada a una VERSION; version actual = vista derivada ----
    def test_I4_pin_a_version(self):
        nec = self.via.necesidad("p", "explicito:'g'")
        q = self.via.consulta(nec, "f")
        url = "https://site.com/doc"
        h1 = self.store.put_snapshot(b"contenido v1")
        ref1 = self.via.referencia(q, url, h1, capture_ts="2026-06-01T00:00:00")
        ins = self.via.inscripcion(Inscripcion("p", ["q"], [{"x": 1}], "lect", self._inferidor()))
        af = self.via.afirmacion("claim sobre v1", ins, ref1)
        # nueva VERSION del MISMO referente (contenido distinto, mas reciente)
        h2 = self.store.put_snapshot(b"contenido v2 distinto")
        self.via.referencia(q, url, h2, capture_ts="2026-06-10T00:00:00")
        cx = proyeccion.reconstruir(self.store, self.db)
        # la afirmacion SIGUE pinneada a la version h1, no salta a h2
        row = cx.execute("SELECT v.content_hash AS h FROM afirmacion a "
                         "JOIN version v ON a.ref_id=v.id WHERE a.id=?", (af,)).fetchone()
        self.assertEqual(row["h"], h1, "la afirmacion no quedo pinneada a su version")
        # version actual del referente = la mas reciente (vista derivada) = h2
        actual = proyeccion.version_actual(cx, referente_id(url))
        self.assertEqual(actual["content_hash"], h2, "version_actual no es la mas reciente")
        cx.close()

    # ---- I2: load-bearing seguro solo si su version tiene snapshot ----
    def test_I2_disponibilidad(self):
        nec = self.via.necesidad("p", "explicito:'g'")
        q = self.via.consulta(nec, "f")
        h = self.store.put_snapshot(b"real")
        ref_ok = self.via.referencia(q, "https://x.com/ok", h, capture_ts="2026-06-01T00:00:00")
        ref_no = self.via.referencia(q, "https://x.com/no", "0" * 64,
                                     capture_ts="2026-06-01T00:00:00")
        ins = self.via.inscripcion(Inscripcion("p", ["q"], [{"x": 1}], "l", self._inferidor()))
        a_ok = self.via.afirmacion("segura", ins, ref_ok)
        a_no = self.via.afirmacion("insegura (sin snapshot)", ins, ref_no)
        cx = proyeccion.reconstruir(self.store, self.db)
        inseg = proyeccion.load_bearing_inseguras(cx, self.store)
        self.assertIn(a_no, inseg)
        self.assertNotIn(a_ok, inseg)
        cx.close()

    # ---- WORM: snapshot idempotente; sin update/delete ----
    def test_WORM_snapshot_idempotente(self):
        h1 = self.store.put_snapshot(b"abc")
        h2 = self.store.put_snapshot(b"abc")
        self.assertEqual(h1, h2)
        snaps = os.listdir(os.path.join(self.store.root, "snapshots"))
        self.assertEqual(snaps.count(h1), 1, "el snapshot se duplico")
        self.assertFalse(hasattr(self.store, "update"))
        self.assertFalse(hasattr(self.store, "delete"))

    # ---- invariante de la tripleta: conclusion sin insumos NO se inscribe ----
    def test_invariante_rechaza_huerfano(self):
        with self.assertRaises(ValueError):
            self.via.inscripcion(Inscripcion("", [], [], "sin tripleta", self._inferidor()))

    # ---- huerfanos: afirmacion sin via detectada ----
    def test_huerfanos(self):
        ins = self.via.inscripcion(Inscripcion("p", ["q"], [{"x": 1}], "l", self._inferidor()))
        a = self.via.afirmacion("sin via", ins, None)   # ref_id None -> huerfana
        cx = proyeccion.reconstruir(self.store, self.db)
        ids = [r["id"] for r in proyeccion.huerfanos(cx)]
        self.assertIn(a, ids)
        cx.close()

    # ---- materializador: aterriza una solicitud sancionada en una via coherente ----
    def test_materializador_via_coherente(self):
        from materializa import Materializador
        mat = Materializador(self.store)
        ins = Inscripcion("premisa", ["q"], [{"x": 1}], "conclusion", self._inferidor())
        r = mat.materializar(pregunta="pp", gatillo="explicito:'g'", formulacion="ff",
                             url="https://x.com/a", snapshot_bytes=b"data",
                             inscripcion=ins, txt="claim")
        cx = proyeccion.reconstruir(self.store, self.db)
        asc = proyeccion.traza_ascendente(cx, r["afirmacion"])
        self.assertEqual(asc["necesidad"]["pregunta"], "pp")
        self.assertEqual(len(proyeccion.huerfanos(cx)), 0)
        self.assertTrue(self.store.has_snapshot(r["snapshot"]))
        cx.close()

    # ---- D-ver-1: normalizacion conservadora ----
    def test_normaliza_url(self):
        a = canonical("http://site.com/path/?utm_source=x&b=2&a=1#frag")
        b = canonical("https://site.com/path?a=1&b=2")
        self.assertEqual(a, b, "variantes de forma no colapsaron")
        self.assertEqual(referente_id(a), referente_id(b))
        # paginas distintas NO se fusionan (bajo-normalizar)
        self.assertNotEqual(canonical("https://site.com/p1"), canonical("https://site.com/p2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
