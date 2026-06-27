"""
ingesta.py -- Paso 3 del Proceso 2 (Consolidacion): la ingesta del YAML-AEC.

Lee un artefacto YAML-AEC (root key ek_chuah_aec:), lo LINTEA (C1-C7, espejo de
validate_yaml_sediment.py de concept-sediment), VERIFICA que cada content_hash ya resuelve
en WORM (gate C3, "nace confirmada", CERO red, NO escribe snapshots) y emite la via al log
durable de forma IDEMPOTENTE -> puebla graph_aec (la proyeccion regenerable).

Separacion load-bearing (CONVERGENCIA seccion 2):
  - La descarga (red, no idempotente) NO vive aqui: es el paso 2 (materializacion).
  - La ingesta es local, determinista, idempotente: mismo YAML = no-op completo (E1).
  - C3 solo VERIFICA que la roca esta en WORM; nunca la baja ni la escribe.

Idempotencia: los ids de evento son DETERMINISTAS (derivados del contenido), y antes de
appendear se verifica que el id no exista ya en el log -> re-ingerir no crece el log. No se
reusa ViaEmision (uuid aleatorio): esta es una via de emision propia y determinista, de modo
que el paso 2 (materializa.py) queda intacto.

Requiere PyYAML (consistente con el gemelo concept-sediment). El resto, stdlib.
Sin emojis (encoding Windows).
"""
from __future__ import annotations
import os
import hashlib
import datetime
import yaml

from nucleo import ISO, huella_insumos
from normaliza_url import referente_id as derivar_referente
import proyeccion


ROOT_KEY = "ek_chuah_aec"
SCHEMA_VERSION = "aec-1"


class IngestaError(Exception):
    """Lint o gate fallido: la ingesta NO toca la proyeccion (falla limpio antes de la BD)."""


# ---- helpers deterministas ----

def _canon(*parts) -> str:
    return "\x1f".join("" if p is None else str(p) for p in parts)


def _det_id(*parts) -> str:
    """Id determinista derivado del contenido (no uuid): re-ingesta = mismos ids = no-op."""
    return hashlib.sha256(_canon(*parts).encode("utf-8")).hexdigest()


def _norm_hash(h) -> str:
    """El WORM keya por sha256 hex crudo; tolera un prefijo de algoritmo ('sha256:')."""
    if not isinstance(h, str):
        return ""
    h = h.strip()
    if ":" in h:
        h = h.split(":", 1)[1]
    return h


def _iso_ok(s) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    s = s.strip()
    try:
        datetime.datetime.strptime(s, ISO)
        return True
    except ValueError:
        try:
            datetime.datetime.fromisoformat(s)   # tolera microsegundos / offset
            return True
        except ValueError:
            return False


def _gatillo_ok(g) -> bool:
    return isinstance(g, str) and (g.startswith("explicito:") or g.startswith("implicito-de:"))


# ---- lint de ingesta (C1-C7): falla limpio antes de tocar la BD ----

def lint(doc, store) -> list:
    """Devuelve la lista de errores BLOQUEANTES (vacia = limpio). store solo para C3
    (has_snapshot, read-only). Espejo del lint de concept-sediment, dominio AEC."""
    aec = doc.get(ROOT_KEY) if isinstance(doc, dict) else None
    if not isinstance(aec, dict):
        return [f"C1: falta la clave raiz '{ROOT_KEY}:'"]

    errs = []
    meta = aec.get("meta") or {}
    if meta.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"C1: meta.schema_version debe ser '{SCHEMA_VERSION}'")

    # C2: cada inscripcion con su tripleta (premisa + busqueda + resultados)
    insc_ids = set()
    for i, ins in enumerate(aec.get("inscripciones") or []):
        lid = ins.get("local_id")
        if lid:
            insc_ids.add(lid)
        premisa = (ins.get("premisa") or "").strip()
        if not premisa or len(ins.get("busqueda") or []) == 0 or len(ins.get("resultados_crudos") or []) == 0:
            errs.append(f"C2: inscripcion[{lid or i}] sin tripleta (premisa/busqueda/resultados_crudos)")

    # C3 (gate "nace confirmada") + C5 (capture_ts ISO), por referencia
    ref_ids = set()
    for q in (aec.get("consultas") or []):
        for r in (q.get("referencias") or []):
            rlid = r.get("local_id")
            if rlid:
                ref_ids.add(rlid)
            h = _norm_hash(r.get("content_hash"))
            if not h or not store.has_snapshot(h):
                errs.append(f"C3: referencia[{rlid}] content_hash no resuelve en WORM "
                            f"(snapshot no materializado -> no se ingiere)")
            if not _iso_ok(r.get("capture_ts")):
                errs.append(f"C5: referencia[{rlid}] capture_ts ausente o no-ISO (reloj sancionado, nunca mtime)")

    # C6: gatillo de la necesidad + pregunta
    nec = aec.get("necesidad") or {}
    if not _gatillo_ok(nec.get("gatillo")):
        errs.append("C6: necesidad.gatillo debe matchear 'explicito:*' o 'implicito-de:*'")
    if not (nec.get("pregunta") or "").strip():
        errs.append("C6: necesidad.pregunta vacia")

    # C4: cada afirmacion con survived_from + inferida_por que resuelven a local_ids presentes
    for a in (aec.get("afirmaciones") or []):
        sf, ip = a.get("survived_from"), a.get("inferida_por")
        if not sf or not ip:
            errs.append(f"C4: afirmacion '{(a.get('txt') or '')[:40]}' sin survived_from o inferida_por (huerfana)")
            continue
        if sf not in ref_ids:
            errs.append(f"C4: afirmacion survived_from '{sf}' no resuelve a una referencia presente")
        if ip not in insc_ids:
            errs.append(f"C4: afirmacion inferida_por '{ip}' no resuelve a una inscripcion presente")
    return errs


# ---- ingesta idempotente ----

def ingest_doc(doc, store, session_id: str = None) -> dict:
    """Lint (gate) -> emision idempotente de la via al log durable. NO escribe snapshots
    (C3 solo verifica). Devuelve resumen. Re-ingerir el mismo doc = no-op (E1)."""
    errs = lint(doc, store)
    if errs:
        raise IngestaError("lint fallido: " + "; ".join(errs))

    aec = doc[ROOT_KEY]
    meta = aec.get("meta") or {}
    sid = session_id or meta.get("session_id") or ""

    existentes = {ev.get("id") for ev in store.iter_events() if "id" in ev}
    nuevos = []

    def emit(eid, event):
        if eid not in existentes:
            ev = dict(event)
            ev["id"] = eid
            existentes.add(eid)
            nuevos.append(ev)
        return eid

    # inscripciones: id = huella (dedup por roca, cross-YAML)
    insc_gid = {}
    for ins in (aec.get("inscripciones") or []):
        premisa, busq, crudos = ins["premisa"], ins["busqueda"], ins["resultados_crudos"]
        h = huella_insumos(premisa, busq, crudos)
        inf = ins.get("inferidor") or {}
        emit(h, {"ev": "inscripcion", "premisa": premisa, "busqueda": busq,
                 "resultados_crudos": crudos, "conclusion": ins.get("conclusion", ""),
                 "inferidor_model": inf.get("model", ""), "inferidor_ts": inf.get("ts", ""),
                 "huella": h})
        insc_gid[ins.get("local_id")] = h

    # necesidad (una por YAML, D-schema-2)
    nec = aec.get("necesidad") or {}
    nec_id = _det_id(sid, "nec", nec.get("pregunta"), nec.get("gatillo"))
    emit(nec_id, {"ev": "necesidad", "pregunta": nec.get("pregunta"),
                  "gatillo": nec.get("gatillo"), "origen_nodo": nec.get("origen_nodo")})

    # consultas -> referencias (versiones), I4: version = (referente, content_hash, capture_ts)
    ref_gid = {}
    for q in (aec.get("consultas") or []):
        formulacion = q.get("formulacion")
        q_id = _det_id(sid, "consulta", nec_id, formulacion)
        emit(q_id, {"ev": "consulta", "nec_id": nec_id, "formulacion": formulacion})
        for r in (q.get("referencias") or []):
            url = r.get("url")
            ref = r.get("referente_id") or derivar_referente(url)   # D-schema-1
            h = _norm_hash(r.get("content_hash"))
            cap = r.get("capture_ts")
            vid = _det_id("ref", ref, h, cap)
            emit(vid, {"ev": "referencia", "referente_id": ref, "content_hash": h,
                       "url_cruda": url, "capture_ts": cap,
                       "fecha_fuente": r.get("fecha_fuente", "capture"), "q_id": q_id})
            ref_gid[r.get("local_id")] = vid

    # afirmaciones (I3: ancladas a referencia + inscripcion)
    af_ids = []
    for a in (aec.get("afirmaciones") or []):
        insc = insc_gid.get(a.get("inferida_por"))
        ref = ref_gid.get(a.get("survived_from"))
        aid = _det_id(sid, "af", a.get("txt"), ref, insc)
        emit(aid, {"ev": "afirmacion", "txt": a.get("txt"), "insc_id": insc, "ref_id": ref,
                   "tipo": a.get("tipo", "claim"), "estatus": a.get("estatus", "afirmado")})
        af_ids.append(aid)

    for ev in nuevos:
        store.append_event(ev)

    return {"session_id": sid, "appended": len(nuevos), "noop": len(nuevos) == 0,
            "afirmaciones": af_ids, "necesidad": nec_id}


def ingest(yaml_path: str, store, db_path: str = None) -> dict:
    """Ingiere un YAML-AEC desde archivo. Si db_path, reconstruye la proyeccion y reporta huerfanos."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    res = ingest_doc(doc, store)
    if db_path:
        cx = proyeccion.reconstruir(store, db_path)
        res["huerfanos"] = len(proyeccion.huerfanos(cx))
        cx.close()
    return res


# ---- CLI ----

def _main(argv=None):
    import argparse
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="Ingesta YAML-AEC -> graph_aec (paso 3 de la Consolidacion). CERO red.")
    ap.add_argument("yaml", help="ruta del YAML-AEC")
    ap.add_argument("--aec", default=os.path.join(here, "..", "AEC"),
                    help="raiz del durable WORM (default: ../AEC)")
    ap.add_argument("--db", default=None,
                    help="ruta de la proyeccion graph_aec a reconstruir (default: no reconstruye)")
    ap.add_argument("--lint-only", action="store_true", help="solo lintea; no escribe nada")
    args = ap.parse_args(argv)

    from aec_store import AecStore
    store = AecStore(args.aec)
    with open(args.yaml, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    if args.lint_only:
        errs = lint(doc, store)
        if errs:
            print("LINT FALLIDO:")
            for e in errs:
                print("  -", e)
            return 1
        print("LINT OK")
        return 0

    try:
        res = ingest_doc(doc, store)
    except IngestaError as e:
        print("INGESTA RECHAZADA:", e)
        return 1
    huerf = "-"
    if args.db:
        cx = proyeccion.reconstruir(store, args.db)
        huerf = len(proyeccion.huerfanos(cx))
        cx.close()
    print(f"INGESTA OK: appended={res['appended']} noop={res['noop']} "
          f"afirmaciones={len(res['afirmaciones'])} huerfanos={huerf}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
