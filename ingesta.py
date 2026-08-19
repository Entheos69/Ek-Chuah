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
REVISION_ESTATUS = ("superada", "retractada")   # C8: estatus validos de una revision (G-post)


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

def lint(doc, store=None) -> list:
    """Devuelve la lista de errores BLOQUEANTES (vacia = limpio). Espejo del lint de
    concept-sediment, dominio AEC.

    Fuente UNICA de verdad del lint (emision e ingesta comparten esta funcion, nunca
    dos copias que puedan diverger):
      - store=None  -> LINT DE EMISION (aun no hay WORM): corre C1/C2/C4/C6 y EXIGE que
        content_hash/capture_ts sean el placeholder 'MATERIALIZAR' (C3/C5 en su forma de
        emision: el plano fisico no es del emisor, membrana D2). Difiere la verificacion
        de que la roca resuelva en WORM y el reloj sea sancionado a la fase de ingesta.
      - store dado  -> LINT DE INGESTA completo: C3 (roca en WORM, read-only) y C5
        (reloj sancionado) sobre el content_hash/capture_ts ya reales.
    C0 (basename==session_id) no vive aqui: `lint` es puro-sobre-doc y no conoce el
    archivo; lo aplica `basename_ok` en el borde donde el path existe (CLI, ingest())."""
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
        # La roca debe decir QUIEN la leyo: una inferencia es lectura fechada y firmada,
        # no un hecho anonimo (nucleo.Inferidor). derivar_eventos ya persiste model+ts;
        # el lint lo exige para que no entre una inscripcion sin procedencia de lectura.
        inf = ins.get("inferidor") or {}
        if not (inf.get("model") or "").strip() or not str(inf.get("ts") or "").strip():
            errs.append(f"C2: inscripcion[{lid or i}] sin inferidor (model + ts): la roca no dice quien la leyo")

    # C3 (gate "nace confirmada") + C5 (capture_ts ISO), por referencia.
    # Solo en fase de ingesta (store dado): en emision no hay WORM ni capture_ts real.
    ref_ids = set()
    for q in (aec.get("consultas") or []):
        for r in (q.get("referencias") or []):
            rlid = r.get("local_id")
            if rlid:
                ref_ids.add(rlid)
            if store is None:
                # Fase EMISION: el plano fisico aun no existe. C3/C5 (roca en WORM, reloj
                # sancionado) se difieren a la ingesta post-materializacion, PERO el
                # content_hash/capture_ts deben ser el placeholder 'MATERIALIZAR'. Un hash
                # o un ts real aqui = el Estratega cruzo la membrana D2 (fabricar procedencia
                # del plano fisico, que no es suyo): se rechaza en la fase donde nace el error.
                for campo, code in (("content_hash", "C3"), ("capture_ts", "C5")):
                    val = r.get(campo)
                    if val != "MATERIALIZAR":
                        errs.append(f"{code}: referencia[{rlid}] {campo}={val!r} en emision debe ser "
                                    f"'MATERIALIZAR' (el plano fisico no es del emisor, D2)")
                continue
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

    # C8: revisiones (G-post) bien formadas. Estructural en ambas fases; la resolucion
    # del target contra el log durable solo cuando hay store (fase ingesta).
    log_af_ids = None
    for rv in (aec.get("revisiones") or []):
        tgt = rv.get("target_af")
        ne = rv.get("nuevo_estatus")
        if not tgt:
            errs.append("C8: revision sin target_af (que afirmacion reconsidera)")
        if ne not in REVISION_ESTATUS:
            errs.append(f"C8: revision.nuevo_estatus '{ne}' invalido (validos: {REVISION_ESTATUS})")
        if not _gatillo_ok(rv.get("gatillo")):
            errs.append("C8: revision.gatillo debe matchear 'explicito:*' o 'implicito-de:*' (D2)")
        if store is not None and tgt:
            if log_af_ids is None:
                log_af_ids = {ev["id"] for ev in store.iter_events()
                              if ev.get("ev") == "afirmacion" and "id" in ev}
            if tgt not in log_af_ids:
                errs.append(f"C8: revision.target_af '{tgt[:16]}...' no resuelve a una "
                            "afirmacion en el log (no se puede reconsiderar lo que no existe)")
    return errs


# ---- ingesta idempotente ----

def session_id_de(doc, session_id: str = None) -> str:
    """El session_id efectivo del grano (arg explicito > meta.session_id > '')."""
    meta = (doc.get(ROOT_KEY) or {}).get("meta") or {} if isinstance(doc, dict) else {}
    return session_id or meta.get("session_id") or ""


def basename_ok(stem: str, doc) -> list:
    """C0: el nombre del contenedor DEBE ser la identidad que declara (session_id).

    Falla en identidad-doble: un grano llamado 'X.yaml' cuyo meta.session_id dice 'Y'
    parte el grafo en dos identidades para una sola indagacion. Es el error que el
    Guardian cazo a mano el 2026-07-18 y que motivo el changelog v2 del skill; aqui lo
    caza el codigo. Browser-independiente: solo compara nombre vs contenido, por eso
    corre en local (CLI) y la comparte el gate de emision del Estratega (aec_verify)
    -> una sola definicion de C0. `stem` es el basename sin extension."""
    sid = session_id_de(doc)
    if stem != sid:
        return [f"C0: basename '{stem}' != meta.session_id '{sid}' (identidad doble del grano)"]
    return []


def derivar_eventos(doc, session_id: str = None) -> list:
    """Deriva la LISTA COMPLETA de eventos que la ingesta emitiria para este grano, como
    pares (id, event) en orden de emision. Funcion PURA: no toca el store, no lintea, no
    filtra por existencia -- solo aplica las reglas de id determinista (huella para la roca,
    _det_id para el resto). Fuente unica de verdad de los ids: la comparten ingest_doc (que
    filtra los ya presentes y appendea) y consumido.py (que cruza contra el log). Cambiar la
    derivacion aqui la cambia en ambos -> no hay drift entre 'que se ingiere' y 'que se
    considera ingerido'."""
    aec = doc.get(ROOT_KEY) if isinstance(doc, dict) else None
    if not isinstance(aec, dict):
        return []
    sid = session_id_de(doc, session_id)
    eventos = []

    # inscripciones: id = huella (dedup por roca, cross-YAML)
    insc_gid = {}
    for ins in (aec.get("inscripciones") or []):
        premisa, busq, crudos = ins.get("premisa"), ins.get("busqueda"), ins.get("resultados_crudos")
        h = huella_insumos(premisa, busq, crudos)
        inf = ins.get("inferidor") or {}
        eventos.append((h, {"ev": "inscripcion", "premisa": premisa, "busqueda": busq,
                            "resultados_crudos": crudos, "conclusion": ins.get("conclusion", ""),
                            "inferidor_model": inf.get("model", ""), "inferidor_ts": inf.get("ts", ""),
                            "huella": h}))
        insc_gid[ins.get("local_id")] = h

    # necesidad (una por YAML, D-schema-2)
    nec = aec.get("necesidad") or {}
    nec_id = _det_id(sid, "nec", nec.get("pregunta"), nec.get("gatillo"))
    eventos.append((nec_id, {"ev": "necesidad", "pregunta": nec.get("pregunta"),
                             "gatillo": nec.get("gatillo"), "origen_nodo": nec.get("origen_nodo")}))

    # consultas -> referencias (versiones), I4: version = (referente, content_hash, capture_ts)
    ref_gid = {}
    for q in (aec.get("consultas") or []):
        formulacion = q.get("formulacion")
        q_id = _det_id(sid, "consulta", nec_id, formulacion)
        eventos.append((q_id, {"ev": "consulta", "nec_id": nec_id, "formulacion": formulacion}))
        for r in (q.get("referencias") or []):
            url = r.get("url")
            ref = r.get("referente_id") or derivar_referente(url)   # D-schema-1
            h = _norm_hash(r.get("content_hash"))
            cap = r.get("capture_ts")
            vid = _det_id("ref", ref, h, cap)
            eventos.append((vid, {"ev": "referencia", "referente_id": ref, "content_hash": h,
                                  "url_cruda": url, "capture_ts": cap,
                                  "fecha_fuente": r.get("fecha_fuente", "capture"), "q_id": q_id}))
            ref_gid[r.get("local_id")] = vid

    # afirmaciones (I3: ancladas a referencia + inscripcion)
    for a in (aec.get("afirmaciones") or []):
        insc = insc_gid.get(a.get("inferida_por"))
        ref = ref_gid.get(a.get("survived_from"))
        aid = _det_id(sid, "af", a.get("txt"), ref, insc)
        eventos.append((aid, {"ev": "afirmacion", "txt": a.get("txt"), "insc_id": insc,
                              "ref_id": ref, "tipo": a.get("tipo", "claim"),
                              "estatus": a.get("estatus", "afirmado")}))

    # revisiones (G-post): reconsideracion append-only de una afirmacion durable previa.
    # id determinista por (sid, target, nuevo_estatus) -> re-ingerir la misma revision = no-op.
    for rv in (aec.get("revisiones") or []):
        tgt, ne = rv.get("target_af"), rv.get("nuevo_estatus")
        rid = _det_id(sid, "rev", tgt, ne)
        eventos.append((rid, {"ev": "revision", "target_af": tgt, "nuevo_estatus": ne,
                              "reemplazada_por": rv.get("reemplazada_por"),
                              "motivo": rv.get("motivo"), "gatillo": rv.get("gatillo")}))
    return eventos


def ingest_doc(doc, store, session_id: str = None) -> dict:
    """Lint (gate) -> emision idempotente de la via al log durable. NO escribe snapshots
    (C3 solo verifica). Devuelve resumen. Re-ingerir el mismo doc = no-op (E1)."""
    errs = lint(doc, store)
    if errs:
        raise IngestaError("lint fallido: " + "; ".join(errs))

    sid = session_id_de(doc, session_id)
    eventos = derivar_eventos(doc, session_id)
    existentes = {ev.get("id") for ev in store.iter_events() if "id" in ev}

    nuevos, af_ids, nec_id = [], [], None
    for eid, event in eventos:
        if event["ev"] == "afirmacion":
            af_ids.append(eid)
        elif event["ev"] == "necesidad":
            nec_id = eid
        if eid not in existentes:
            ev = dict(event)
            ev["id"] = eid
            existentes.add(eid)
            nuevos.append(ev)

    for ev in nuevos:
        store.append_event(ev)

    return {"session_id": sid, "appended": len(nuevos), "noop": len(nuevos) == 0,
            "afirmaciones": af_ids, "necesidad": nec_id}


def ingest(yaml_path: str, store, db_path: str = None) -> dict:
    """Ingiere un YAML-AEC desde archivo. Si db_path, reconstruye la proyeccion y reporta huerfanos."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    b_errs = basename_ok(os.path.splitext(os.path.basename(yaml_path))[0], doc)
    if b_errs:
        raise IngestaError("lint fallido: " + "; ".join(b_errs))
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
    ap.add_argument("--emision", action="store_true",
                    help="lint de EMISION (sin WORM): corre C1/C2/C4/C6, omite C3/C5. "
                         "Mismo linter que la ingesta; para que el Estratega valide antes de entregar.")
    ap.add_argument("--init", action="store_true",
                    help="bootstrap: crea el durable WORM si no existe (uso raro; por defecto falla ruidoso)")
    ap.add_argument("--nube", action="store_true",
                    help="B realineado: tras la ingesta local, empuja el delta a aec_log y lo "
                         "proyecta a graph_aec en Railway (atomico, idempotente). Requiere "
                         "DATABASE_URL. Un comando = visible en el lector al instante.")
    args = ap.parse_args(argv)

    from aec_store import AecStore
    with open(args.yaml, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    # C0 (identidad-doble): el nombre del archivo debe ser el session_id. Se antepone a
    # todas las fases porque un grano mal nombrado esta roto antes de cualquier otro check.
    b_errs = basename_ok(os.path.splitext(os.path.basename(args.yaml))[0], doc)

    # Fase EMISION: no hay WORM todavia -> store=None -> lint subset (C0/C1/C2/C4/C6).
    if args.emision:
        errs = b_errs + lint(doc, store=None)
        if errs:
            print("LINT EMISION FALLIDO:")
            for e in errs:
                print("  -", e)
            return 1
        print("LINT EMISION OK (C0/C1/C2/C4/C6; C3/C5 se verifican tras materializar)")
        return 0

    store = AecStore(args.aec, create=args.init)

    if args.lint_only:
        errs = b_errs + lint(doc, store)
        if errs:
            print("LINT FALLIDO:")
            for e in errs:
                print("  -", e)
            return 1
        print("LINT OK")
        return 0

    if b_errs:
        print("INGESTA RECHAZADA: lint fallido:", "; ".join(b_errs))
        return 1
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

    if args.nube:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("NUBE OMITIDA: falta DATABASE_URL. La ingesta LOCAL quedo bien; "
                  "corre 'python nube.py --aec", args.aec, "' cuando tengas la URL "
                  "(idempotente, se auto-repara).")
            return 1
        import nube
        try:
            rn = nube.consolidar(args.aec, nube._connect_real(db_url))
        except Exception as e:
            print(f"NUBE FALLO ({type(e).__name__}: {e}). La ingesta LOCAL quedo bien; "
                  "re-corre con --nube o 'python nube.py' (idempotente, se auto-repara).")
            return 1
        print(f"NUBE OK: nuevos={rn['nuevos']} afirmaciones_nuevas={rn['afirmaciones_nuevas']} "
              f"embebidas={rn['embebidas']} -> visible en el lector")
        if rn["sin_embedding"]:
            print(f"  AVISO: {rn['sin_embedding']} sin embedding (busqueda ILIKE si las ve)")
    elif os.environ.get("DATABASE_URL"):
        print("HINT: DATABASE_URL presente; agrega --nube para que el grano sea visible "
              "en el lector al instante (B realineado).")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
