"""
exporta_log.py -- Exportador del borde local -> nube (camino B).

UNICO cruce nube <- local del camino B: empuja las lineas del log durable
`../AEC/log/inscripciones.jsonl` a la tabla `aec_log` del Postgres del MCP-AEC,
que reconstruye `graph_aec` del log replicado (no de la proyeccion empujada).

Contrato del receptor (SOL_EXPORTADOR_LOG_AEC_2026-06-27 §2; tabla en Ek-Chuah-mcp):
    aec_log(seq BIGSERIAL PK, line_sha TEXT UNIQUE, event JSONB, ingested_at TIMESTAMPTZ)
    INSERT INTO aec_log (line_sha, event) VALUES (:sha, CAST(:ev AS jsonb))
    ON CONFLICT (line_sha) DO NOTHING;

Idempotencia por line_sha = sha256 de la linea JSONL CANONICA, identica a
`aec_store.append_event` (json.dumps con ensure_ascii=False, sort_keys=True). Por eso
re-canonicalizamos del dict parseado: robusto al espaciado/orden del archivo y espeja
exactamente lo que la nube hashea (replicate_log_from_file). Re-exportar = no-op.

Membrana (no negociable): cruza SOLO el log (necesidad/consulta/URL/content_hash/lectura),
NUNCA `snapshots/` (nivel 1, bytes). El log ya lleva content_hash, no bytes: membrane-safe
por construccion. Direccion unica local -> nube (gana el local, E1).

Solo stdlib. El driver Postgres (psycopg/psycopg2) se importa PEREZOSO en el cruce real;
los tests y el --dry-run corren sin red ni driver. Sin emojis (encoding Windows).

Correr (validacion local, sin DB):
    python exporta_log.py --aec ../AEC --dry-run
Cruce real (el Guardian provee DATABASE_URL del store MCP-AEC):
    python exporta_log.py --aec ../AEC --db-url "$DATABASE_URL"
"""
from __future__ import annotations
import os
import sys
import json
import hashlib
import argparse


# ---- canonicalizacion: espejo exacto de aec_store.append_event / SOL §2 ----

def canonical_line(ev: dict) -> str:
    """La forma canonica de un evento (lo que se hashea y lo que se inserta como event)."""
    return json.dumps(ev, ensure_ascii=False, sort_keys=True)


def line_sha(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def log_path_for(aec_root: str) -> str:
    """La ruta canonica del log dentro del durable. La membrana vive aqui: SOLO el log."""
    return os.path.join(os.path.abspath(aec_root), "log", "inscripciones.jsonl")


def iter_log_events(log_path: str):
    """Yield (sha, canonical_str, ev) por cada evento del log.

    Re-canonicaliza del dict parseado (no hashea la linea cruda): asi un log con
    espaciado u orden de llaves distinto produce el MISMO sha que la nube espera.
    """
    if not os.path.exists(log_path):
        return
    with open(log_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            ev = json.loads(raw)
            canon = canonical_line(ev)
            yield line_sha(canon), canon, ev


# ---- sinks inyectables (real psycopg / fake en memoria para tests y --dry-run) ----

class MemorySink:
    """Espeja ON CONFLICT(line_sha) DO NOTHING en memoria. Para tests offline y --dry-run.

    `existing` precarga shas ya presentes en la nube (simula export incremental).
    """
    def __init__(self, existing=None):
        self.store = dict(existing or {})   # line_sha -> canonical
        self.inserted = 0
        self.conflicts = 0

    def upsert(self, sha: str, canonical: str) -> bool:
        if sha in self.store:
            self.conflicts += 1
            return False
        self.store[sha] = canonical
        self.inserted += 1
        return True

    def close(self):
        pass


class PostgresSink:
    """Cruce real a `aec_log`. Importa el driver PEREZOSO (no es dependencia de los tests)."""
    def __init__(self, db_url: str):
        try:
            import psycopg as driver            # psycopg 3
            self.driver = "psycopg"
        except ImportError:                      # pragma: no cover - depende del entorno real
            import psycopg2 as driver            # psycopg 2
            self.driver = "psycopg2"
        self.cx = driver.connect(db_url)
        self.inserted = 0
        self.conflicts = 0

    def upsert(self, sha: str, canonical: str) -> bool:
        with self.cx.cursor() as cur:
            cur.execute(
                "INSERT INTO aec_log (line_sha, event) VALUES (%s, CAST(%s AS jsonb)) "
                "ON CONFLICT (line_sha) DO NOTHING",
                (sha, canonical),
            )
            applied = cur.rowcount == 1
        if applied:
            self.inserted += 1
        else:
            self.conflicts += 1
        return applied

    def close(self):
        self.cx.commit()
        self.cx.close()


# ---- el export ----

def export_log(log_path: str, sink) -> dict:
    """Empuja cada evento del log al sink. Idempotente: el sink absorbe los repetidos.

    No abre snapshots/ jamas (membrana). Devuelve evidencia citable.
    """
    read = 0
    for sha, canon, _ev in iter_log_events(log_path):
        read += 1
        sink.upsert(sha, canon)
    return {
        "read": read,
        "inserted": sink.inserted,
        "conflicts": sink.conflicts,   # no-ops por line_sha ya presente
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Exportador del log AEC local -> aec_log (camino B).")
    p.add_argument("--aec", default="../AEC",
                   help="dir durable; lee <aec>/log/inscripciones.jsonl (default: ../AEC)")
    p.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                   help="DATABASE_URL del Postgres MCP-AEC (default: env DATABASE_URL)")
    p.add_argument("--dry-run", action="store_true",
                   help="cuenta y hashea sin escribir (sink en memoria; sin red ni driver)")
    args = p.parse_args(argv)

    log_path = log_path_for(args.aec)

    if args.dry_run:
        sink, mode = MemorySink(), "dry-run"
    elif not args.db_url:
        print("[exporta_log] ERROR: falta DATABASE_URL (o --db-url). "
              "Usa --dry-run para validar local sin la nube.", file=sys.stderr)
        return 2
    else:
        sink, mode = PostgresSink(args.db_url), "postgres"

    stats = export_log(log_path, sink)
    sink.close()

    print(f"[exporta_log] modo={mode} log={log_path}")
    print(f"  leidos={stats['read']} insertados={stats['inserted']} "
          f"conflictos_noop={stats['conflicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
