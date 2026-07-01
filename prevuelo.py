"""
prevuelo.py -- Pre-flight del Paso 2: localiza los huecos ANTES de materializar.

El paso 2 (materializa_orden) baja la roca de cada referencia a WORM. Cuando una URL
esta muerta (DNS caido, host que se cuelga, 404) el materializador no puede bajar la roca:
el grano queda inconsistente (afirmacion sin roca) y la ingesta (gate C3) lo rechaza.

Este modulo hace ese diagnostico ANTES, de manera preventiva y SIN escribir nada:
sondea cada referencia pendiente (content_hash == MATERIALIZAR) y la clasifica por
alcanzabilidad. Cruza con las afirmaciones para asignar SEVERIDAD:

  - BLOQUEANTE : referencia inalcanzable que SOSTIENE una afirmacion (survived_from).
                 Sin su roca, la afirmacion nace sin ancla -> hay que reemplazar la
                 fuente (roca viva equivalente) antes de materializar.
  - AVISO      : referencia inalcanzable que NO sostiene ninguna afirmacion. Puede
                 quitarse del grano (quitar > fabricar procedencia con otra URL).
  - OK         : la roca baja; lista para el paso 2.

Read-only: NO escribe en WORM ni muta el grano. Toca la red solo para SONDEAR (lee un
trozo pequeno del cuerpo, lo justo para detectar el host que se cuelga a mitad de la
respuesta). probe inyectable -> los tests no tocan la red. Sin emojis (Windows).

Uso:
    python prevuelo.py granos/2026-06-30-002-Indagacion.yaml
    # exit 0 si no hay BLOQUEANTES; exit 1 si alguna ref load-bearing es inalcanzable.
"""
from __future__ import annotations
import socket
import urllib.error
import urllib.request

from ingesta import ROOT_KEY
from materializa_orden import PLACEHOLDER, _pendiente

# estados de un sondeo
OK = "OK"
DNS = "DNS"          # getaddrinfo failed: el host no resuelve (URL muerta/fabricada)
TIMEOUT = "TIMEOUT"  # conecta pero se cuelga leyendo (anti-bot / endpoint colgado)
HTTP = "HTTP"        # respondio con codigo de error (404, 403, 5xx)
ERROR = "ERROR"      # otro fallo de red (conexion rechazada, TLS, etc.)

# severidades
BLOQUEANTE = "BLOQUEANTE"
AVISO = "AVISO"


def _probe_urllib(url: str, timeout: int = 12) -> tuple:
    """Sondeo real read-only AUTORITATIVO: baja el cuerpo completo (acotado por timeout)
    para detectar tanto el host que no resuelve como el que sirve un 200 y se CUELGA a
    mitad de la respuesta (challenge anti-bot). Leer solo un trozo daria falsos OK a esos
    hosts. NO escribe en WORM (esa es la diferencia con el paso 2): mismo trabajo de red,
    cero durable. Devuelve (estado, detalle)."""
    req = urllib.request.Request(url, headers={"User-Agent": "ek-chuah-prevuelo/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()                           # cuerpo completo: revienta si el host se cuelga
            return OK, str(getattr(r, "status", 200))
    except urllib.error.HTTPError as e:
        return HTTP, str(e.code)
    except (socket.gaierror,) as e:
        return DNS, str(e)
    except (socket.timeout, TimeoutError):
        return TIMEOUT, "read/connect timeout"
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, socket.gaierror):
            return DNS, str(reason)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return TIMEOUT, "read/connect timeout"
        return ERROR, str(reason)
    except Exception as e:                     # ultimo recurso: nunca revienta el prevuelo
        return ERROR, f"{type(e).__name__}: {e}"


def refs_load_bearing(aec: dict) -> set:
    """local_ids de referencia que aparecen como survived_from en alguna afirmacion."""
    return {a.get("survived_from") for a in (aec.get("afirmaciones") or [])
            if a.get("survived_from")}


def prevuelo(doc: dict, probe=_probe_urllib, timeout: int = 12) -> dict:
    """Sondea las referencias PENDIENTES y las clasifica por severidad. No escribe nada.
    Devuelve {items:[...], bloqueantes:int, avisos:int, ok:int, ya:int}."""
    aec = doc.get(ROOT_KEY) or {}
    lb = refs_load_bearing(aec)
    items, bloq, avi, ok, ya = [], 0, 0, 0, 0
    for q in (aec.get("consultas") or []):
        for r in (q.get("referencias") or []):
            lid = r.get("local_id")
            url = r.get("url")
            es_lb = lid in lb
            if not _pendiente(r):
                ya += 1
                items.append({"local_id": lid, "url": url, "estado": "YA",
                              "detalle": "ya materializada", "load_bearing": es_lb,
                              "severidad": None})
                continue
            estado, detalle = probe(url, timeout) if _acepta_timeout(probe) else probe(url)
            if estado == OK:
                ok += 1
                sev = None
            elif es_lb:
                bloq += 1
                sev = BLOQUEANTE
            else:
                avi += 1
                sev = AVISO
            items.append({"local_id": lid, "url": url, "estado": estado,
                          "detalle": detalle, "load_bearing": es_lb, "severidad": sev})
    return {"items": items, "bloqueantes": bloq, "avisos": avi, "ok": ok, "ya": ya}


def _acepta_timeout(probe) -> bool:
    """El probe real toma (url, timeout); un probe de test puede tomar solo (url)."""
    try:
        import inspect
        return len(inspect.signature(probe).parameters) >= 2
    except (TypeError, ValueError):
        return False


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Pre-flight del paso 2: sondea las referencias de un grano y localiza "
                    "los huecos (URLs muertas) por severidad. Read-only, no escribe nada.")
    ap.add_argument("grano", help="ruta del grano YAML-AEC (orden con placeholders)")
    ap.add_argument("--timeout", type=int, default=12, help="timeout de sondeo por URL (s)")
    args = ap.parse_args(argv)

    import yaml
    with open(args.grano, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    rep = prevuelo(doc, timeout=args.timeout)
    print(f"PREVUELO {args.grano}")
    for it in rep["items"]:
        sev = it["severidad"] or ("" if it["estado"] in (OK, "YA") else "")
        marca = "[LB]" if it["load_bearing"] else "    "
        etiqueta = it["severidad"] or it["estado"]
        print(f"  {it['local_id']:4} {marca} {etiqueta:11} {it['url']}")
        if it["estado"] not in (OK, "YA"):
            print(f"            -> {it['estado']}: {it['detalle']}")
    print(f"resumen: ok={rep['ok']} ya={rep['ya']} avisos={rep['avisos']} "
          f"bloqueantes={rep['bloqueantes']}")
    if rep["bloqueantes"]:
        print("RESULTADO: BLOQUEANTE -- hay refs load-bearing inalcanzables; "
              "reemplaza la fuente (roca viva equivalente) antes de materializar.")
        return 1
    if rep["avisos"]:
        print("RESULTADO: OK con AVISOS -- refs no load-bearing inalcanzables; "
              "considera quitarlas del grano antes de materializar.")
        return 0
    print("RESULTADO: OK -- todas las refs pendientes bajan; listo para el paso 2.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
