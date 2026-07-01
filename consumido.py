"""
consumido.py -- Estado de consumo de un grano: ¿ya fue ingerido al durable?

Un grano esta CONSUMIDO cuando TODOS los eventos deterministas que su ingesta emitiria
(derivar_eventos) ya viven en el log durable. La comprobacion es CERO red y CERO escritura,
y -a diferencia del gate C3- NO exige que las rocas esten en WORM: solo cruza los ids
deterministas del grano contra los ids del log. Reutiliza derivar_eventos de ingesta.py:
misma fuente de verdad de ids que la ingesta -> lo que aqui se llama 'consumido' es
exactamente 'la ingesta seria un no-op'.

Estados:
  CONSUMIDO    -- todos los eventos del grano estan en el log (re-ingerir = no-op, E1).
  NO-CONSUMIDO -- ninguno esta (el grano nunca se ingirio).
  PARCIAL      -- algunos si, otros no (ingesta a medias, o el grano se edito tras ingerir:
                  las afirmaciones/refs cambiadas ya no matchean su id previo).
  VACIO        -- el grano no deriva ningun evento (no es un YAML-AEC valido).

Uso:
    python consumido.py granos/2026-06-30-002-Indagacion.yaml   # un grano
    python consumido.py                                          # escanea granos/
    python consumido.py --json                                   # salida maquinable

Solo stdlib + PyYAML. Sin emojis (encoding Windows).
"""
from __future__ import annotations
import os
import yaml

from ingesta import ROOT_KEY, derivar_eventos, session_id_de

CONSUMIDO = "CONSUMIDO"
NO_CONSUMIDO = "NO-CONSUMIDO"
PARCIAL = "PARCIAL"
VACIO = "VACIO"


def estado_doc(doc, store, session_id: str = None) -> dict:
    """Estado de consumo de un grano ya cargado. Read-only (no toca el store salvo leer el log).
    Devuelve {estado, total, presentes, faltantes:[ev...], session_id}."""
    eventos = derivar_eventos(doc, session_id)
    existentes = {ev.get("id") for ev in store.iter_events() if "id" in ev}
    faltantes = [{"id": eid, "ev": event.get("ev")}
                 for eid, event in eventos if eid not in existentes]
    total = len(eventos)
    presentes = total - len(faltantes)
    if total == 0:
        estado = VACIO
    elif presentes == 0:
        estado = NO_CONSUMIDO
    elif presentes == total:
        estado = CONSUMIDO
    else:
        estado = PARCIAL
    return {"estado": estado, "total": total, "presentes": presentes,
            "faltantes": faltantes, "session_id": session_id_de(doc, session_id)}


def estado_grano(yaml_path: str, store, session_id: str = None) -> dict:
    """Estado de consumo de un grano desde archivo. Anade 'grano' (la ruta) al reporte."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rep = estado_doc(doc, store, session_id)
    rep["grano"] = yaml_path
    return rep


def escanear_granos(granos_dir: str, store) -> list:
    """Estado de consumo de todos los granos de un directorio, ordenados por nombre."""
    rutas = sorted(os.path.join(granos_dir, n) for n in os.listdir(granos_dir)
                   if n.endswith((".yaml", ".yml")))
    reps = []
    for ruta in rutas:
        try:
            reps.append(estado_grano(ruta, store))
        except (yaml.YAMLError, OSError) as e:
            reps.append({"grano": ruta, "estado": "ERROR", "total": 0, "presentes": 0,
                         "faltantes": [], "session_id": "", "error": f"{type(e).__name__}: {e}"})
    return reps


# ---- CLI ----

def _fmt(rep: dict) -> str:
    nombre = os.path.basename(rep["grano"])
    linea = f"  {rep['estado']:12} {rep['presentes']:>2}/{rep['total']:<2}  {nombre}"
    if rep.get("error"):
        linea += f"\n            -> {rep['error']}"
    return linea


def _main(argv=None):
    import argparse
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="Estado de consumo de granos: ¿ya fueron ingeridos al durable? "
                    "CERO red, CERO escritura (no exige rocas en WORM).")
    ap.add_argument("grano", nargs="?", default=None,
                    help="ruta de un grano; si se omite, escanea el directorio de granos")
    ap.add_argument("--aec", default=os.path.join(here, "..", "AEC"),
                    help="raiz del durable WORM (default: ../AEC)")
    ap.add_argument("--granos-dir", default=os.path.join(here, "granos"),
                    help="directorio de granos a escanear (default: granos/)")
    ap.add_argument("--json", action="store_true", help="salida JSON maquinable")
    args = ap.parse_args(argv)

    from aec_store import AecStore
    store = AecStore(args.aec)

    if args.grano:
        reps = [estado_grano(args.grano, store)]
    else:
        reps = escanear_granos(args.granos_dir, store)

    if args.json:
        print(json.dumps(reps, ensure_ascii=False, indent=2))
    else:
        print(f"CONSUMO (durable: {os.path.abspath(args.aec)})")
        for rep in reps:
            print(_fmt(rep))
        n_cons = sum(1 for r in reps if r["estado"] == CONSUMIDO)
        pend = [r for r in reps if r["estado"] in (NO_CONSUMIDO, PARCIAL)]
        print(f"resumen: consumidos={n_cons}/{len(reps)} pendientes={len(pend)}")
        if pend:
            print("pendientes:", ", ".join(os.path.basename(r["grano"]) for r in pend))

    # exit 1 si algun grano pedido/escaneado no esta consumido (util en scripts/gates)
    return 0 if all(r["estado"] == CONSUMIDO for r in reps) else 1


if __name__ == "__main__":
    import sys
    sys.exit(_main())
