"""
materializa_orden.py -- Paso 2 (materializacion) sobre una ORDEN YAML-AEC.

Toma una orden emitida por el Estratega (Proceso 1), con content_hash/capture_ts = MATERIALIZAR,
baja cada referencia (URL) al durable WORM (snapshot content-addressed) y RELLENA:
  - content_hash  = sha256 real de los bytes bajados (identidad de la version, I4)
  - capture_ts    = reloj sancionado en la puerta (ahora), NUNCA mtime
  - meta.consolidado_por (el actor local que materializa)
-> deja la orden lista para la ingesta (paso 3, ingesta.py).

Separacion load-bearing (CONVERGENCIA seccion 2): aqui vive la DESCARGA (red, NO idempotente,
falla/expira/404/parcial). NO puebla graph_aec (eso es la ingesta, local y determinista).
Captura-primero-luego-ingesta: la roca baja y se confirma ANTES de poblar; lo peor que queda
si la ingesta no corre es un blob WORM huerfano (inocuo, dedup), nunca una afirmacion sin roca.

Idempotente sobre refs YA materializadas: solo toca las que siguen en MATERIALIZAR (no re-baja
ni re-sella capture_ts). Materializa la orden UNA vez; el archivo resultante es el ingestible.

fetch inyectable (default urllib, stdlib) -> los tests no tocan la red. Sin emojis (Windows).
"""
from __future__ import annotations
import datetime
import urllib.request
import yaml

from nucleo import ISO
from ingesta import ROOT_KEY

PLACEHOLDER = "MATERIALIZAR"


def _fetch_urllib(url: str, timeout: int = 30) -> bytes:
    """Descarga real (la corre el actor local con web: Guardian / IA-aux). file:// tambien sirve."""
    req = urllib.request.Request(url, headers={"User-Agent": "ek-chuah-materializador/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pendiente(r) -> bool:
    return r.get("content_hash") in (None, PLACEHOLDER, "")


def materializar_orden(doc, store, fetch=_fetch_urllib, consolidado_por=None, clock=None) -> dict:
    """Baja la roca de cada referencia pendiente a WORM y rellena content_hash + capture_ts.
    Muta doc in-place. Devuelve resumen. NO toca graph_aec."""
    clock = clock or (lambda: datetime.datetime.now().strftime(ISO))
    aec = doc.get(ROOT_KEY) or {}
    if consolidado_por:
        aec.setdefault("meta", {})["consolidado_por"] = consolidado_por

    bajadas, ya = [], []
    for q in (aec.get("consultas") or []):
        for r in (q.get("referencias") or []):
            if not _pendiente(r):
                ya.append(r.get("local_id"))
                continue
            data = fetch(r["url"])                 # descarga (red)
            h = store.put_snapshot(data)           # WORM idempotente (mismo hash = no-op)
            r["content_hash"] = h
            r["capture_ts"] = clock()              # reloj sancionado en la puerta
            bajadas.append({"local_id": r.get("local_id"), "url": r["url"],
                            "content_hash": h, "bytes": len(data)})
    return {"materializadas": bajadas, "ya_materializadas": ya,
            "consolidado_por": (aec.get("meta") or {}).get("consolidado_por")}


def materializar_archivo(in_path, store, out_path=None, fetch=_fetch_urllib,
                         consolidado_por=None) -> dict:
    """Materializa una orden desde archivo, IN-PLACE por defecto: el grano evoluciona de orden
    (placeholders) a materializado (ingestible) en el MISMO archivo. Un grano = un archivo.
    Usa --out solo si quieres escribir a otra ruta."""
    with open(in_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    res = materializar_orden(doc, store, fetch=fetch, consolidado_por=consolidado_por)
    out_path = out_path or in_path
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    res["out"] = out_path
    return res


def _main(argv=None):
    import argparse
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="Paso 2: materializa una orden YAML-AEC (baja la roca a WORM + rellena hash/capture_ts).")
    ap.add_argument("orden", help="ruta de la orden YAML-AEC (con placeholders MATERIALIZAR)")
    ap.add_argument("--aec", default=os.path.join(here, "..", "AEC"),
                    help="raiz del durable WORM (default: ../AEC)")
    ap.add_argument("--out", default=None,
                    help="ruta de salida (default: in-place, el mismo archivo del grano)")
    ap.add_argument("--consolidado-por", default=None,
                    help="actor local que materializa (Guardian / IA-aux)")
    args = ap.parse_args(argv)

    from aec_store import AecStore
    store = AecStore(args.aec)
    res = materializar_archivo(args.orden, store, out_path=args.out,
                               consolidado_por=args.consolidado_por)
    print(f"MATERIALIZADAS: {len(res['materializadas'])} | ya: {len(res['ya_materializadas'])} | "
          f"consolidado_por: {res['consolidado_por']}")
    for b in res["materializadas"]:
        print(f"  {b['local_id']}: {b['content_hash'][:16]}... ({b['bytes']} bytes) <- {b['url']}")
    print(f"ingestible: {res['out']}")
    print("siguiente: python ingesta.py", res["out"], "--aec", args.aec, "--db ek_chuah.db")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
