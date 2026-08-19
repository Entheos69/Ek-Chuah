#!/usr/bin/env python3
"""
aec_verify.py -- Gate PRE-EMISION del Estratega para granos YAML-AEC (Ek-Chuah).

Corre del lado nube (Cowork + Claude in Chrome), ANTES de entregar el grano al actor
local. NO sustituye a ingesta.py: la autoridad del lint estructural es ingesta.lint, que
esta herramienta REUSA (no reimplementa) para no divergir. Lo que aporta es lo que el
lint NO puede hacer nunca -- comparar el YAML contra los BYTES que el navegador leyo:

  V1  VERBATIM: cada resultados_crudos[].texto es substring LITERAL de la captura del DOM.
      Si no aparece, es SINTESIS (anti-patron #1 del skill): el check que convierte una
      cuestion de disciplina del Estratega(t+1) en una comparacion de cadenas ejecutable.
  V2  extracto corto: <15 palabras (restriccion de copyright del skill).
  V3  cada referencia tiene su captura asociada (si no, el verbatim no se pudo comprobar).

Lo ESTRUCTURAL (C0 identidad-doble, C1 schema, C2 tripleta+inferidor, C3/C5 membrana
MATERIALIZAR en emision, C4 anclaje, C6 necesidad, C8 revisiones) se DELEGA a ingesta:
una sola fuente de verdad, sin la copia que ya habia divergido (inferidor). Si el repo no
es importable en el sandbox de la nube, se degrada: corre V* y avisa que lo estructural va
por `python ingesta.py --emision`. Recomendacion: checa el repo en la nube (el Estratega
tiene acceso) para que la delegacion opere y el gate sea completo.

AVISOS (no bloquean; son politica del grafo, decide el Guardian):
  - coherencia consulta<->busqueda (una formulacion sin busqueda literal gemela).
  - coherencia de reloj (fecha del session_id vs fecha de inferidor.ts).
  - campos derivados declarados (referente_id/huella): ingesta los TOLERA, pero el grano
    nube deberia llevar solo locators (membrana D2). Aviso, no fallo, para no contradecir
    a la ingesta.
  - offset de zona en inferidor.ts (specs en conflicto: ek-chuah-yaml-aec omite offset,
    episteme-minimo dir.13 lo exige). Aviso: quien resuelve es el Guardian.

Solo stdlib + PyYAML. Sin emojis (encoding Windows).
"""
from __future__ import annotations
import hashlib, os, re, sys, unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("falta pyyaml: pip install pyyaml --break-system-packages")

# Autoridad estructural: se reusa ingesta.lint / basename_ok si el repo es importable.
# Sin drift: los mismos C0-C8 que corren en la ingesta local corren aqui.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ingesta import lint as _lint_local, basename_ok as _basename_ok
    _HAS_REPO = True
except Exception:
    _HAS_REPO = False

# --------------------------------------------------------------------------
# Normalizacion para el cotejo VERBATIM: el DOM y el YAML no coinciden byte a byte
# aunque digan lo mismo (comillas tipograficas, NBSP, guiones largos, saltos de linea
# son ruido de transporte). Se normalizan AMBOS lados igual antes de comparar.
#
# CUIDADO (frontera con la propuesta del testigo, dictamen 2026-08-19 seccion 2): hoy
# esta funcion es solo un normalizador de DISPLAY para substring -- su salida no entra
# a ningun id del grafo. El dia que un `testigo_lectura.sha256` derive de ella y viaje
# al log, se vuelve LOAD-BEARING (como nucleo._canon): habria que congelarla y compartirla
# entre nube y local. Cambiarla entonces re-mapearia esos testigos. No lo es aun.
# --------------------------------------------------------------------------
_COMILLAS = {0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
             0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2032: "'", 0x2033: '"',
             0x2013: "-", 0x2014: "-", 0x2212: "-", 0x00A0: " ", 0x200B: ""}


def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_COMILLAS)
    return re.sub(r"\s+", " ", s).strip()


def sha256_txt(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _split_code(msg: str):
    """Un mensaje de ingesta.lint ('C2: foo') -> ('C2', 'foo')."""
    code, sep, rest = msg.partition(":")
    return (code.strip(), rest.strip()) if sep else ("C?", msg.strip())


@dataclass
class Reporte:
    fallos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    testigos: dict = field(default_factory=dict)

    def fallo(self, check, msg): self.fallos.append((check, msg))
    def aviso(self, check, msg): self.avisos.append((check, msg))
    @property
    def ok(self): return not self.fallos


def verificar(ruta, capturas: dict | None = None) -> Reporte:
    """Gate pre-emision. `capturas`: {url_cruda: texto_visible_capturado_del_navegador}."""
    ruta = Path(ruta)
    r = Reporte()
    doc = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    capturas = {k: normalizar(v) for k, v in (capturas or {}).items()}

    if not isinstance(doc, dict) or "ek_chuah_aec" not in doc:
        r.fallo("C1", "falta root key 'ek_chuah_aec'")
        return r
    g = doc["ek_chuah_aec"] or {}

    # ---- estructural: DELEGADO a ingesta (autoridad unica), o degradado ----
    if _HAS_REPO:
        for m in _basename_ok(ruta.stem, doc):      # C0 identidad-doble
            r.fallo(*_split_code(m))
        for m in _lint_local(doc, store=None):      # C1/C2/C3-C5-emision/C4/C6/C8
            r.fallo(*_split_code(m))
    else:
        r.aviso("REPO", "ingesta.py no importable aqui: estructural (C0-C8) NO verificado. "
                        "Corre 'python ingesta.py --emision <grano>' en el repo. V* si corre.")

    # ---- V1/V2/V3: verbatim, lo unico que exige tener la fuente enfrente ----
    inscripciones = g.get("inscripciones") or []
    for i, ins in enumerate(inscripciones):
        lid = ins.get("local_id") or f"<inscripcion #{i}>"
        for j, res in enumerate(ins.get("resultados_crudos") or []):
            texto = res.get("texto") or ""
            fuente = res.get("fuente") or "<sin fuente>"
            n_pal = len(texto.split())
            if n_pal >= 15:
                r.fallo("V2", f"{lid}[{j}] {fuente}: extracto de {n_pal} palabras (limite <15, copyright)")
            if not capturas:
                r.aviso("V1", f"{lid}[{j}] {fuente}: sin captura, verbatim NO verificado")
                continue
            aguja = normalizar(texto)
            donde = [u for u, pajar in capturas.items() if aguja and aguja in pajar]
            if donde:
                r.testigos.setdefault(donde[0], sha256_txt(capturas[donde[0]]))
            else:
                r.fallo("V1", f"{lid}[{j}] {fuente}: extracto NO literal en ninguna captura "
                              f"-> probable sintesis (anti-patron #1): {texto[:60]!r}")

    # ---- avisos de politica (no bloquean) + V3 captura-asociada ----
    literales = {normalizar(b) for ins in inscripciones for b in (ins.get("busqueda") or [])}
    for c in (g.get("consultas") or []):
        formul = normalizar(c.get("formulacion") or "")
        if formul and formul not in literales:
            r.aviso("coherencia", f"formulacion sin busqueda literal gemela: {formul[:60]!r} "
                                  f"(consulta y busqueda pueden diferir; solo se avisa)")
        for ref in (c.get("referencias") or []):
            rid = ref.get("local_id")
            for derivado in ("referente_id", "huella"):
                if derivado in ref:
                    r.aviso("D2", f"{rid}: declara '{derivado}' (derivado); el grano nube deberia "
                                  f"llevar solo el locator. ingesta lo tolera -> aviso.")
            url = ref.get("url") or ""
            if re.search(r"^data:|;base64,", url):
                r.aviso("D2", f"{rid}: la url parece llevar bytes embebidos, no un locator: {url[:40]!r}")
            if capturas and url and url not in capturas:
                r.aviso("V3", f"{rid}: referencia sin captura asociada ({url[:60]})")

    # ---- aviso de reloj: fecha del session_id vs fecha de inferidor.ts ----
    sid = ((g.get("meta") or {}).get("session_id")) or ""
    fecha_sid = sid[:10] if len(sid) >= 10 else ""
    for i, ins in enumerate(inscripciones):
        lid = ins.get("local_id") or f"<inscripcion #{i}>"
        ts = str((ins.get("inferidor") or {}).get("ts") or "")
        if not ts:
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", ts):
            r.aviso("D2", f"{lid}: inferidor.ts {ts!r} sin offset numerico. episteme-minimo dir.13 "
                          f"lo exige; ek-chuah-yaml-aec lo omite. Specs en conflicto -> Guardian.")
        if fecha_sid and ts[:10] and ts[:10] != fecha_sid:
            r.aviso("reloj", f"{lid}: session_id fecha {fecha_sid} != inferidor.ts fecha {ts[:10]} "
                             f"(si una es UTC y la otra local, el grano nace con dos relojes)")
    return r


def main(argv):
    if len(argv) < 2:
        sys.exit("uso: aec_verify.py <grano.yaml> [captura_<local_id>.txt ...]")
    caps = {}
    doc = yaml.safe_load(Path(argv[1]).read_text(encoding="utf-8")) or {}
    refs = [ref for c in ((doc.get("ek_chuah_aec") or {}).get("consultas") or [])
                for ref in (c.get("referencias") or [])]
    por_id = {ref.get("local_id"): ref.get("url") for ref in refs}
    for p in argv[2:]:
        lid = Path(p).stem.replace("captura_", "")
        if lid in por_id:
            caps[por_id[lid]] = Path(p).read_text(encoding="utf-8")
        else:
            print(f"  aviso: {p} no matchea ningun local_id {list(por_id)}")
    rep = verificar(argv[1], caps)
    for ch, m in rep.fallos: print(f"FALLO {ch}: {m}")
    for ch, m in rep.avisos: print(f"aviso {ch}: {m}")
    for u, h in rep.testigos.items(): print(f"testigo {h[:16]}... <- {u}")
    print("\nAPTO para entregar al Guardian" if rep.ok else "\nRETENIDO: corrige antes de entregar")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
