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
import os
import datetime
import urllib.request
import yaml

from nucleo import ISO
from ingesta import ROOT_KEY

PLACEHOLDER = "MATERIALIZAR"

# UA de navegador. Varios hosts canonicos (digikey, st.com, fabricantes) responden 403 o
# cuelgan la conexion ante un cliente que no se presenta como navegador; con esto bajan la
# roca real. NO afecta ninguna identidad: el content_hash se calcula sobre los BYTES de la
# respuesta, no sobre el UA. prevuelo.py REUSA esta constante (import) para que el sondeo del
# pre-flight y la descarga del paso 2 apliquen el MISMO criterio de alcance: si difirieran, el
# prevuelo daria OK y el paso 2 fallaria (o al reves). Fuente unica -> sin drift.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _fetch_urllib(url: str, timeout: int = 45) -> bytes:
    """Descarga real (la corre el actor local con web: Guardian / IA-aux). file:// tambien sirve."""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _leer_archivo_local(origen: str, base_dir: str = None) -> bytes:
    """Via de captura local: lee los BYTES de una captura hecha a mano (navegador), para
    anclar una roca que vive tras un muro anti-bot que urllib no cruza (ver NOTA_DEV
    origen_local). Resuelve `origen` relativo a base_dir (la carpeta del grano); una ruta
    absoluta se usa tal cual (eleccion explicita del actor local). Una ruta RELATIVA no
    puede escapar de base_dir (guard anti-`..`). NO sanciona el reloj ni calcula el hash:
    eso lo hace materializar_orden en la puerta, igual que con una descarga."""
    if os.path.isabs(origen):
        ruta = os.path.abspath(origen)
    else:
        base = os.path.abspath(base_dir or ".")
        ruta = os.path.abspath(os.path.join(base, origen))
        if os.path.commonpath([base, ruta]) != base:
            raise ValueError(f"origen_local '{origen}' escapa de la carpeta del grano (base_dir)")
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"origen_local no existe o no es un archivo: {ruta}")
    with open(ruta, "rb") as f:
        return f.read()


def _pendiente(r) -> bool:
    return r.get("content_hash") in (None, PLACEHOLDER, "")


def materializar_orden(doc, store, fetch=_fetch_urllib, consolidado_por=None, clock=None,
                       base_dir=None) -> dict:
    """Baja la roca de cada referencia pendiente a WORM y rellena content_hash + capture_ts.
    Muta doc in-place. Devuelve resumen. NO toca graph_aec.

    Resiliente por-referencia: una URL muerta (DNS caido, host colgado, 404) NO aborta el
    grano ni pierde el progreso de las demas. La ref fallida queda en MATERIALIZAR (pendiente)
    y se reporta en 'fallidas' (con su load_bearing). El WORM idempotente hace inocuo el
    progreso parcial: re-correr solo re-intenta las pendientes. La ingesta (gate C3) sigue
    rechazando el grano mientras quede cualquier ref sin roca -> nada nace sin ancla."""
    clock = clock or (lambda: datetime.datetime.now().strftime(ISO))
    aec = doc.get(ROOT_KEY) or {}
    if consolidado_por:
        aec.setdefault("meta", {})["consolidado_por"] = consolidado_por

    lb = {a.get("survived_from") for a in (aec.get("afirmaciones") or [])
          if a.get("survived_from")}
    bajadas, ya, fallidas = [], [], []
    for q in (aec.get("consultas") or []):
        for r in (q.get("referencias") or []):
            lid = r.get("local_id")
            if not _pendiente(r):
                ya.append(lid)
                continue
            origen = r.get("origen_local")         # via de captura local (host anti-bot)
            try:
                data = (_leer_archivo_local(origen, base_dir) if origen
                        else fetch(r["url"]))      # archivo local, o descarga (red)
            except Exception as e:                 # una fuente caida no tumba el grano entero
                fallidas.append({"local_id": lid, "url": r.get("url"),
                                 "error": f"{type(e).__name__}: {e}",
                                 "load_bearing": lid in lb})
                continue                           # la ref queda en MATERIALIZAR (pendiente)
            h = store.put_snapshot(data)           # WORM idempotente (mismo hash = no-op)
            r["content_hash"] = h
            r["capture_ts"] = clock()              # reloj sancionado en la puerta (NUNCA mtime)
            if origen:                             # procedencia: el actor local capturo a mano;
                r["captura"] = "manual"            # conserva r["url"] como localizador canonico
                r.setdefault("captura_tool", "desconocido")
            bajadas.append({"local_id": lid, "url": r["url"], "content_hash": h,
                            "bytes": len(data), "captura": r.get("captura", "automatica")})
    return {"materializadas": bajadas, "ya_materializadas": ya, "fallidas": fallidas,
            "consolidado_por": (aec.get("meta") or {}).get("consolidado_por")}


def materializar_archivo(in_path, store, out_path=None, fetch=_fetch_urllib,
                         consolidado_por=None) -> dict:
    """Materializa una orden desde archivo, IN-PLACE por defecto: el grano evoluciona de orden
    (placeholders) a materializado (ingestible) en el MISMO archivo. Un grano = un archivo.
    Usa --out solo si quieres escribir a otra ruta."""
    with open(in_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    # base_dir = la carpeta del grano: ancla las rutas RELATIVAS de origen_local (captura local).
    res = materializar_orden(doc, store, fetch=fetch, consolidado_por=consolidado_por,
                             base_dir=os.path.dirname(os.path.abspath(in_path)))
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
    ap.add_argument("--timeout", type=int, default=30,
                    help="timeout de descarga por URL en segundos (default: 30)")
    ap.add_argument("--init", action="store_true",
                    help="bootstrap: crea el durable WORM si no existe (uso raro; por defecto falla ruidoso)")
    args = ap.parse_args(argv)

    from aec_store import AecStore
    store = AecStore(args.aec, create=args.init)
    fetch = lambda u: _fetch_urllib(u, timeout=args.timeout)
    res = materializar_archivo(args.orden, store, out_path=args.out, fetch=fetch,
                               consolidado_por=args.consolidado_por)
    print(f"MATERIALIZADAS: {len(res['materializadas'])} | ya: {len(res['ya_materializadas'])} | "
          f"fallidas: {len(res['fallidas'])} | consolidado_por: {res['consolidado_por']}")
    for b in res["materializadas"]:
        print(f"  {b['local_id']}: {b['content_hash'][:16]}... ({b['bytes']} bytes) <- {b['url']}")
    for f in res["fallidas"]:
        sev = "BLOQUEANTE (load-bearing)" if f["load_bearing"] else "AVISO (no load-bearing)"
        print(f"  FALLIDA {f['local_id']} [{sev}] <- {f['url']}")
        print(f"          {f['error']}")
    print(f"ingestible: {res['out']}")
    if res["fallidas"]:
        print("PARCIAL: quedan refs en MATERIALIZAR. Corre 'python prevuelo.py "
              f"{res['out']}' para el diagnostico; reemplaza/quita las fuentes muertas y re-materializa.")
        return 1
    print("siguiente: python ingesta.py", res["out"], "--aec", args.aec,
          "--db ek_chuah.db --nube   (B realineado: visible en el lector al instante)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
