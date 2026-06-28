"""
test_exporta_log.py -- Falsadores del exportador del borde (camino B), offline.

Sin red ni driver Postgres: el sink es inyectable (MemorySink espeja ON CONFLICT
DO NOTHING). Tempdirs (durable real intacto). Tests del axioma que se pagan solos.

Cubre:
  - PARIDAD line_sha con aec_store.append_event (el contrato de idempotencia del SOL §2).
  - IDEMPOTENCIA: re-exportar = 0 inserciones (todas conflicto/no-op).
  - INCREMENTAL: con la nube parcialmente poblada, solo cruzan las lineas nuevas.
  - MEMBRANA: cruza SOLO el log; nunca lee snapshots; ningun evento lleva bytes.
  - CANONICO robusto: una linea con llaves desordenadas hashea al mismo sha.
  - El `event` insertado == cadena canonica (la nube reconstruye un dict identico).

Correr:  python tests/test_exporta_log.py -v
"""
from __future__ import annotations
import os
import sys
import json
import hashlib
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aec_store import AecStore                                   # noqa: E402
import exporta_log                                               # noqa: E402
from exporta_log import (                                        # noqa: E402
    MemorySink, export_log, iter_log_events, log_path_for,
    canonical_line, line_sha,
)


def _populate(store: AecStore):
    """Un grano minimo en el log: necesidad -> consulta -> referencia(version) -> afirmacion.

    La referencia apunta a un snapshot REAL (para la prueba de membrana). Devuelve la
    lista de eventos tal como quedaron en el log (con 'ts' inyectado por append_event).
    """
    rock = b"<html>events are the source of truth</html>"
    h = store.put_snapshot(rock)                  # crea snapshots/<h>; la membrana NO debe tocarlo

    evs = []
    evs.append(store.append_event({
        "ev": "necesidad", "id": "n1",
        "pregunta": "que es event sourcing", "gatillo": "diseno Ek-Chuah",
        "origen_nodo": "DISENO_EK_CHUAH",
    }))
    evs.append(store.append_event({
        "ev": "consulta", "id": "q1", "nec_id": "n1",
        "formulacion": "event sourcing projections",
    }))
    evs.append(store.append_event({
        "ev": "referencia", "id": "v1", "referente_id": "event-driven.io/projections",
        "content_hash": h, "url_cruda": "https://event-driven.io/en/projections/",
        "capture_ts": "2026-06-27T15:01:30", "fecha_fuente": "2026", "q_id": "q1",
    }))
    evs.append(store.append_event({
        "ev": "afirmacion", "id": "a1", "txt": "los eventos son la fuente de verdad",
        "insc_id": None, "ref_id": "v1", "tipo": "descriptiva", "estatus": "afirmado",
    }))
    return evs, h, rock


class ExportaLogTest(unittest.TestCase):
    def setUp(self):
        # aislar de un DATABASE_URL del entorno (el CLI lo lee por default)
        self._saved_db_url = os.environ.pop("DATABASE_URL", None)
        self.tmp = tempfile.mkdtemp(prefix="aec_export_")
        self.aec = os.path.join(self.tmp, "AEC")
        self.store = AecStore(self.aec)
        self.evs, self.snap_h, self.rock = _populate(self.store)
        self.log_path = log_path_for(self.aec)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._saved_db_url is not None:
            os.environ["DATABASE_URL"] = self._saved_db_url

    # ---- PARIDAD: line_sha == sha256 de la canonica que escribio append_event ----
    def test_line_sha_paridad_con_append_event(self):
        # lo que el writer dejo en el log, re-canonicalizado, debe dar el sha del exportador
        esperado = [
            hashlib.sha256(
                json.dumps(ev, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            for ev in self.evs
        ]
        obtenido = [sha for sha, _c, _e in iter_log_events(self.log_path)]
        self.assertEqual(obtenido, esperado)
        # y el event insertado es exactamente la cadena canonica (la nube reconstruye igual)
        for (_sha, canon, ev) in iter_log_events(self.log_path):
            self.assertEqual(canon, canonical_line(ev))

    # ---- IDEMPOTENCIA: re-exportar al mismo sink = no-op completo ----
    def test_idempotente_reexport_noop(self):
        sink = MemorySink()
        s1 = export_log(self.log_path, sink)
        self.assertEqual(s1["read"], 4)
        self.assertEqual(s1["inserted"], 4)
        self.assertEqual(s1["conflicts"], 0)

        s2 = export_log(self.log_path, sink)          # mismo sink: la nube ya los tiene
        self.assertEqual(s2["read"], 4)
        self.assertEqual(s2["inserted"], 4)           # acumulado del sink no cambia...
        self.assertEqual(sink.conflicts, 4)           # ...porque los 4 fueron conflicto en la 2a
        self.assertEqual(len(sink.store), 4)          # la nube no crecio

    # ---- INCREMENTAL: nube parcialmente poblada -> solo cruzan las nuevas ----
    def test_incremental_solo_lineas_nuevas(self):
        primeras = dict(list(_shas(self.log_path).items())[:2])  # 2 ya en la nube
        sink = MemorySink(existing=primeras)
        stats = export_log(self.log_path, sink)
        self.assertEqual(stats["read"], 4)
        self.assertEqual(stats["inserted"], 2)        # solo las 2 nuevas
        self.assertEqual(stats["conflicts"], 2)
        self.assertEqual(len(sink.store), 4)

    # ---- MEMBRANA: cruza solo el log; nunca el snapshot; ningun evento lleva bytes ----
    def test_membrana_nunca_snapshots(self):
        sink = MemorySink()
        stats = export_log(self.log_path, sink)
        self.assertEqual(stats["read"], 4)            # 4 eventos del log, no 5 (no leyo el snapshot)

        rock_txt = self.rock.decode("utf-8")
        for canon in sink.store.values():
            self.assertNotIn(rock_txt, canon)         # los bytes de la roca NUNCA cruzan
            ev = json.loads(canon)
            self.assertNotIn("snapshot", ev)
            self.assertNotIn("bytes", ev)
            self.assertNotIn("data", ev)
        # la referencia cruza el content_hash (no los bytes)
        refs = [json.loads(c) for c in sink.store.values() if json.loads(c).get("ev") == "referencia"]
        self.assertEqual(refs[0]["content_hash"], self.snap_h)
        # el snapshot local sigue intacto (export no escribe local)
        self.assertTrue(self.store.has_snapshot(self.snap_h))

    # ---- CANONICO robusto: linea con llaves desordenadas -> mismo sha ----
    def test_canonico_robusto_a_orden_de_llaves(self):
        # escribo a mano una linea con orden NO canonico y espaciado raro
        ev = {"id": "n9", "pregunta": "x", "ev": "necesidad", "gatillo": "g",
              "origen_nodo": "o", "ts": "2026-06-27T10:00:00"}
        desordenada = '{"id":"n9", "pregunta":"x", "ev":"necesidad", "gatillo":"g", ' \
                      '"origen_nodo":"o", "ts":"2026-06-27T10:00:00"}'
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(desordenada + "\n")
        shas = list(iter_log_events(self.log_path))
        sha_de_la_desordenada = shas[-1][0]
        self.assertEqual(sha_de_la_desordenada, line_sha(canonical_line(ev)))

    # ---- log vacio / ausente: read=0, sin error ----
    def test_log_vacio(self):
        vac = os.path.join(self.tmp, "VACIO")
        os.makedirs(os.path.join(vac, "log"), exist_ok=True)
        sink = MemorySink()
        stats = export_log(log_path_for(vac), sink)
        self.assertEqual(stats, {"read": 0, "inserted": 0, "conflicts": 0})

    # ---- CLI --dry-run no necesita DB ni driver ----
    def test_cli_dry_run(self):
        rc = exporta_log.main(["--aec", self.aec, "--dry-run"])
        self.assertEqual(rc, 0)

    def test_cli_sin_db_falla_limpio(self):
        rc = exporta_log.main(["--aec", self.aec])    # sin --db-url ni env
        self.assertEqual(rc, 2)                        # rechaza, no no-op silencioso


def _shas(log_path):
    return {sha: canon for sha, canon, _e in iter_log_events(log_path)}


if __name__ == "__main__":
    unittest.main(verbosity=2)
