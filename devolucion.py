"""
devolucion.py -- G-pre: devolver un grano al Estratega para RE-EVALUAR el camino
epistemico, sin obligarlo a re-investigar.

El grano YA es la memoria preservada del Estratega: contiene la necesidad, las
consultas, TODAS las referencias (vivas y muertas) y que afirmacion sostiene cada
una (survived_from). El Estratega pierde esas referencias entre turnos; esta
herramienta se las DEVUELVE anotando el grano IN-PLACE con un bloque top-level
`reevaluacion:` que localiza las referencias inalcanzables por severidad y clasifica
la SOSPECHA:

  - fabricacion : ref LOAD-BEARING que falla por DNS (el host no resuelve) -> la URL
                  probablemente nunca existio. Senal de alucinacion: el Estratega
                  cumplio el compromiso con una cita fabricada (datos degradados).
  - degradacion : ref real ahora inalcanzable (TIMEOUT / HTTP / ERROR) -> la fuente
                  existio y murio/se degrado; hay que sustituirla por una roca viva
                  equivalente o quitar la afirmacion que sostiene.

Membrana: read-only respecto al WORM (no baja rocas, no escribe snapshots). Solo toca
el grano YAML. Reusa el sondeo de prevuelo (misma red, cero durable) -> probe inyectable,
los tests no tocan la red. Sin emojis (Windows).

El bloque `reevaluacion:` es out-of-band: materializa_orden e ingesta leen solo la clave
raiz ek_chuah_aec: y lo ignoran. Si el grano ya no tiene refs muertas, el bloque se
retira (grano limpio).

Uso:
    python devolucion.py granos/<grano>.yaml
    # exit 1 si hay BLOQUEANTES (refs load-bearing muertas); exit 0 si esta limpio.
"""
from __future__ import annotations
import datetime

from ingesta import ROOT_KEY
from nucleo import ISO
from prevuelo import prevuelo, OK, DNS

REEV_KEY = "reevaluacion"
FABRICACION = "fabricacion"
DEGRADACION = "degradacion"


def _afirmaciones_sostenidas(aec: dict, lid: str) -> list:
    """txt de las afirmaciones cuyo survived_from es esta referencia."""
    return [a.get("txt") for a in (aec.get("afirmaciones") or [])
            if a.get("survived_from") == lid]


def devolucion(doc: dict, probe=None, timeout: int = 12, clock=None) -> dict:
    """Sondea el grano y ARMA el bloque de reevaluacion (no escribe archivo). Muta doc
    in-place: agrega doc['reevaluacion'] si hay refs muertas, o lo retira si esta limpio.
    Devuelve el reporte {refs, bloqueantes, avisos, hay_sospecha_fabricacion}."""
    clock = clock or (lambda: datetime.datetime.now().strftime(ISO))
    aec = doc.get(ROOT_KEY) or {}
    rep = prevuelo(doc, probe=probe, timeout=timeout) if probe is not None \
        else prevuelo(doc, timeout=timeout)

    refs = []
    for it in rep["items"]:
        if it["estado"] in (OK, "YA"):
            continue
        # DNS en una ref que sostiene una afirmacion = cita probablemente fabricada.
        sospecha = FABRICACION if (it["load_bearing"] and it["estado"] == DNS) else DEGRADACION
        refs.append({"local_id": it["local_id"], "url": it["url"],
                     "estado": it["estado"], "detalle": it["detalle"],
                     "severidad": it["severidad"], "sospecha": sospecha,
                     "sostiene": _afirmaciones_sostenidas(aec, it["local_id"])})

    hay_fab = any(r["sospecha"] == FABRICACION for r in refs)
    if refs:
        doc[REEV_KEY] = {
            "generado": clock(),
            "bloqueantes": rep["bloqueantes"],
            "avisos": rep["avisos"],
            "sospecha_fabricacion": hay_fab,
            "instruccion": (
                "Re-evalua el camino epistemico SIN re-investigar de cero: el contexto "
                "esta en este grano. Para cada ref abajo: si sospecha=fabricacion, la cita "
                "probablemente no existe -> retira la afirmacion que sostiene o sustituyela "
                "con una fuente viva equivalente y verificada; si sospecha=degradacion, "
                "sustituye la URL por una roca viva equivalente. Luego re-emite el grano "
                "(pon content_hash/capture_ts = MATERIALIZAR en las refs sustituidas)."),
            "refs": refs,
        }
    else:
        doc.pop(REEV_KEY, None)   # grano limpio: no arrastrar un bloque stale

    return {"refs": refs, "bloqueantes": rep["bloqueantes"], "avisos": rep["avisos"],
            "hay_sospecha_fabricacion": hay_fab}


def devolucion_archivo(path: str, probe=None, timeout: int = 12, out_path=None) -> dict:
    """Corre la devolucion desde archivo y reescribe el grano IN-PLACE (o a out_path)."""
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rep = devolucion(doc, probe=probe, timeout=timeout)
    out_path = out_path or path
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    rep["out"] = out_path
    return rep


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="G-pre: devuelve un grano al Estratega para re-evaluar el camino "
                    "epistemico. Anota el grano in-place con el bloque reevaluacion: "
                    "(refs muertas + severidad + sospecha de fabricacion). Read-only vs WORM.")
    ap.add_argument("grano", help="ruta del grano YAML-AEC")
    ap.add_argument("--timeout", type=int, default=12, help="timeout de sondeo por URL (s)")
    ap.add_argument("--out", default=None, help="ruta de salida (default: in-place)")
    args = ap.parse_args(argv)

    rep = devolucion_archivo(args.grano, timeout=args.timeout, out_path=args.out)
    if not rep["refs"]:
        print(f"DEVOLUCION {args.grano}: limpio -- ninguna ref muerta. Nada que reevaluar.")
        return 0

    print(f"DEVOLUCION {args.grano} -> {rep['out']}")
    for r in rep["refs"]:
        marca = "SOSPECHA-FABRICACION" if r["sospecha"] == FABRICACION else "degradacion"
        print(f"  {r['local_id']:4} [{r['severidad'] or 'AVISO'}] {marca:20} "
              f"{r['estado']}: {r['url']}")
        for txt in r["sostiene"]:
            print(f"         sostiene: {txt[:70]}")
    print(f"resumen: bloqueantes={rep['bloqueantes']} avisos={rep['avisos']} "
          f"sospecha_fabricacion={rep['hay_sospecha_fabricacion']}")
    print("Bloque reevaluacion: escrito en el grano. Devuelvelo al Estratega para re-emitir.")
    return 1 if rep["bloqueantes"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
