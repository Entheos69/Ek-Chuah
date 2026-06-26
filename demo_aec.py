"""
demo_aec.py -- El substrato Q aplicado end-to-end (sobre AEC TEMPORAL, no el durable real).

D2: NO escribe en el AEC real (Scripts/AEC). Usa un directorio temporal -- inscribir en el
durable real exige sancion del Estratega, no la iniciativa de una demo.

Inscribe un intercambio (la investigacion event-sourcing/local-first que dio origen a todo
esto), reconstruye la proyeccion DEL LOG, y muestra: via ascendente (leer trae el porque),
version actual como vista derivada, huerfanos=0, y el falsador I1 (rebuild = identico).

Correr:  python demo_aec.py
"""
from __future__ import annotations
import os
import shutil
import tempfile
from aec_store import AecStore
from materializa import Materializador
from nucleo import Inscripcion, Inferidor
from normaliza_url import referente_id
import proyeccion

URL = "https://event-driven.io/projections?utm_source=x#frag"


def _linea(c="-"):
    print(c * 74)


def main():
    tmp = tempfile.mkdtemp()
    try:
        store = AecStore(os.path.join(tmp, "AEC"))
        mat = Materializador(store)
        db = os.path.join(tmp, "ek_chuah.db")

        snapshot = ("<html>event sourcing: el log de eventos es la fuente de verdad; "
                    "el read model se reconstruye reaplicando eventos.</html>").encode("utf-8")
        ins = Inscripcion(
            premisa=("local vs nube parecia binario; ni la nube se pierde si se reconstruye "
                     "ni lo local es seguro ante dano fisico"),
            busqueda=["event sourcing rebuild projection from log",
                      "local-first sync survive server and device failure"],
            resultados_crudos=[
                {"fuente": "event-driven.io", "texto": "el log es la verdad; el read model se reconstruye"},
                {"fuente": "inkandswitch", "texto": "copia primaria en el dispositivo; de ahi local mas replica"}],
            conclusion=("El log replicado es la verdad; la proyeccion (incl. el MCP) es "
                        "desechable y reconstruible."),
            inferidor=Inferidor("estratega/claude-opus", "2026-06-25T00:00:00"))

        r = mat.materializar(
            pregunta="Donde debe vivir el lector del grafo, dado que ni local ni nube son seguros solos",
            gatillo="explicito:'investiga en la web soluciones a problemas similares'",
            formulacion="event sourcing local-first projection rebuild",
            url=URL, snapshot_bytes=snapshot, inscripcion=ins,
            origen_nodo="decision:A/B/C-donde-vive-el-lector",
            txt="El log replicado es la verdad; la proyeccion es desechable.", tipo="decision")

        print("\n=== Substrato AEC (forma Q) -- end-to-end sobre AEC temporal ===\n")
        print(f"snapshot content-hash : {r['snapshot'][:16]}...")
        print(f"durable (log JSONL)   : {store.log_path}")
        print(f"eventos en el log     : {sum(1 for _ in store.iter_events())}")

        cx = proyeccion.reconstruir(store, db)
        _linea("=")
        print("VIA ASCENDENTE (afirmacion -> necesidad; leer trae el porque):")
        asc = proyeccion.traza_ascendente(cx, r["afirmacion"])
        print(f"  afirmacion : {asc['afirmacion']}")
        print(f"  inferencia : {asc['inferencia']['conclusion'][:60]}...")
        print(f"               (inferida_por {asc['inferencia']['inferida_por']})")
        print(f"  version    : {asc['version']['content_hash'][:16]}...  <- {asc['version']['url_cruda']}")
        print(f"  consulta   : {asc['consulta']}")
        print(f"  necesidad  : {asc['necesidad']['pregunta'][:58]}...")
        print(f"  gatillo    : {asc['necesidad']['gatillo']}")
        _linea()
        actual = proyeccion.version_actual(cx, referente_id(URL))
        print(f"VERSION ACTUAL (vista derivada): {actual['content_hash'][:16]}... @ {actual['capture_ts']}")
        print(f"HUERFANOS (saber sin porque)   : {len(proyeccion.huerfanos(cx))}")
        d1 = proyeccion.dump_logico(cx)
        cx.close()
        cx2 = proyeccion.reconstruir(store, db)
        d2 = proyeccion.dump_logico(cx2)
        cx2.close()
        print(f"FALSADOR I1 (rebuild=identico) : {'OK' if d1 == d2 else 'FALLA'}")
        _linea("=")
        print("AEC real (Scripts/AEC) NO tocado: inscribir en el durable exige sancion del Estratega (D2).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
