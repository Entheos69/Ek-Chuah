"""
test_prevuelo.py -- Falsadores del pre-flight (prevuelo.py) y de la resiliencia del paso 2.

Prueba que el prevuelo:
  - clasifica una ref inalcanzable LOAD-BEARING como BLOQUEANTE (sostiene una afirmacion);
  - clasifica una ref inalcanzable NO load-bearing como AVISO (se puede quitar);
  - marca OK las que bajan y no sondea las YA materializadas;
  - devuelve exit 1 solo cuando hay bloqueantes.
Y que materializar_orden es RESILIENTE: una URL muerta no aborta el grano, persiste el
progreso de las demas y deja la fallida en MATERIALIZAR con su severidad.

probe/fetch FALSOS (no tocan la red). Tempdirs (durable real intacto).

Correr:  python tests/test_prevuelo.py -v
"""
from __future__ import annotations
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                                   # noqa: E402
from materializa_orden import materializar_orden, PLACEHOLDER    # noqa: E402
import prevuelo                                                  # noqa: E402
from prevuelo import prevuelo as correr_prevuelo, BLOQUEANTE, AVISO, OK, DNS, TIMEOUT  # noqa: E402


# r1 baja; r2 DNS muerto (load-bearing -> BLOQUEANTE); r3 timeout (no load-bearing -> AVISO)
VIVA = "https://viva.example/a"
MUERTA = "https://muerta.example/b"
COLGADA = "https://colgada.example/c"


def _probe_falso(url):
    if url == VIVA:
        return OK, "200"
    if url == MUERTA:
        return DNS, "getaddrinfo failed"
    if url == COLGADA:
        return TIMEOUT, "read timeout"
    return prevuelo.ERROR, "?"


def _orden():
    def ref(lid, url):
        return {"local_id": lid, "url": url, "content_hash": PLACEHOLDER,
                "capture_ts": PLACEHOLDER, "fecha_fuente": "capture", "estatus": "viva"}
    return {"ek_chuah_aec": {
        "meta": {"schema_version": "aec-1", "session_id": "2026-07-01-001-Indagacion",
                 "consolidado_por": "PENDIENTE", "project": "ek-chuah"},
        "inscripciones": [{
            "local_id": "i1", "premisa": "p", "busqueda": ["q"],
            "resultados_crudos": [{"fuente": "x", "texto": "t"}], "conclusion": "c",
            "inferidor": {"model": "m", "ts": "2026-07-01T00:00:00"}}],
        "necesidad": {"pregunta": "q", "gatillo": "explicito:'x'", "origen_nodo": "n"},
        "consultas": [
            {"formulacion": "f1", "referencias": [ref("r1", VIVA), ref("r2", MUERTA)]},
            {"formulacion": "f2", "referencias": [ref("r3", COLGADA)]}],
        # r2 sostiene una afirmacion (load-bearing); r3 no.
        "afirmaciones": [
            {"txt": "a1", "tipo": "claim", "estatus": "afirmado",
             "survived_from": "r2", "inferida_por": "i1"}]}}


class Prevuelo(unittest.TestCase):
    def test_clasifica_por_severidad(self):
        rep = correr_prevuelo(_orden(), probe=_probe_falso)
        by = {it["local_id"]: it for it in rep["items"]}
        self.assertIsNone(by["r1"]["severidad"])          # baja -> OK
        self.assertEqual(by["r1"]["estado"], OK)
        self.assertEqual(by["r2"]["severidad"], BLOQUEANTE)   # muerta + load-bearing
        self.assertTrue(by["r2"]["load_bearing"])
        self.assertEqual(by["r3"]["severidad"], AVISO)        # colgada + no load-bearing
        self.assertFalse(by["r3"]["load_bearing"])
        self.assertEqual(rep["bloqueantes"], 1)
        self.assertEqual(rep["avisos"], 1)
        self.assertEqual(rep["ok"], 1)

    def test_no_sondea_las_ya_materializadas(self):
        doc = _orden()
        # marca r1 como ya materializada
        doc["ek_chuah_aec"]["consultas"][0]["referencias"][0]["content_hash"] = "abc123"
        sondeadas = []

        def probe_registra(url):
            sondeadas.append(url)
            return _probe_falso(url)

        rep = correr_prevuelo(doc, probe=probe_registra)
        self.assertNotIn(VIVA, sondeadas)                 # ya materializada: no se sondea
        self.assertEqual(rep["ya"], 1)


class ResilienciaPaso2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = AecStore(os.path.join(self.tmp, "AEC"), create=True)
        self.clock = lambda: "2026-07-01T10:00:00"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_una_url_muerta_no_aborta_el_grano(self):
        doc = _orden()

        def fetch_parcial(url):
            if url == VIVA:
                return b"<html>viva</html>"
            raise ConnectionError("host muerto")   # r2 y r3 fallan

        res = materializar_orden(doc, self.store, fetch=fetch_parcial, clock=self.clock)
        # la buena bajo y persistio; las muertas quedan pendientes (no revento)
        self.assertEqual(len(res["materializadas"]), 1)
        self.assertEqual(len(res["fallidas"]), 2)
        refs = {r["local_id"]: r for q in doc["ek_chuah_aec"]["consultas"]
                for r in q["referencias"]}
        self.assertNotEqual(refs["r1"]["content_hash"], PLACEHOLDER)
        self.assertEqual(refs["r2"]["content_hash"], PLACEHOLDER)   # sigue pendiente
        self.assertEqual(refs["r3"]["content_hash"], PLACEHOLDER)
        # la severidad viaja en el reporte: r2 load-bearing, r3 no
        fall = {f["local_id"]: f for f in res["fallidas"]}
        self.assertTrue(fall["r2"]["load_bearing"])
        self.assertFalse(fall["r3"]["load_bearing"])


class _FakeResp:
    """Respuesta falsa (context manager) para capturar el Request sin tocar la red."""
    def __init__(self, body=b"ok", status=200):
        self._b, self.status = body, status

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UserAgentNavegador(unittest.TestCase):
    """Falsador: tanto la descarga (paso 2) como el sondeo (pre-flight) se presentan como
    NAVEGADOR. Varios hosts canonicos (digikey, st.com) devuelven 403 o cuelgan ante un UA
    no-navegador, dejando la roca real inalcanzable. Ambos pasos DEBEN usar el MISMO UA
    (BROWSER_UA, fuente unica en materializa_orden): si el sondeo usara uno y la descarga
    otro, el pre-flight daria OK y el paso 2 fallaria. No toca la red: captura el Request."""

    @staticmethod
    def _capturar_request(modulo, fn):
        real = modulo.urllib.request.urlopen
        capturado = {}

        def fake(req, *a, **k):
            capturado["req"] = req
            return _FakeResp()

        modulo.urllib.request.urlopen = fake
        try:
            fn()
        finally:
            modulo.urllib.request.urlopen = real
        return capturado["req"]

    def test_fetch_y_probe_usan_el_mismo_ua_de_navegador(self):
        import materializa_orden as mo
        req_fetch = self._capturar_request(mo, lambda: mo._fetch_urllib("https://x.example/a"))
        req_probe = self._capturar_request(prevuelo, lambda: prevuelo._probe_urllib("https://x.example/a"))
        ua_fetch = req_fetch.get_header("User-agent")
        ua_probe = req_probe.get_header("User-agent")
        self.assertEqual(ua_fetch, mo.BROWSER_UA)
        self.assertEqual(ua_probe, mo.BROWSER_UA)        # misma fuente de verdad -> sin drift
        self.assertIn("Mozilla", ua_fetch)
        self.assertNotIn("ek-chuah", ua_fetch.lower())   # ya no el UA que digikey/st rechazan


if __name__ == "__main__":
    unittest.main(verbosity=2)
