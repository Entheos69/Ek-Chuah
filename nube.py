"""
nube.py -- B realineado: consolidacion directa a la nube (patron concept-sediment).

Decision Guardian 2026-07-02: AEC se realinea al patron concept-sediment (el escritor
escribe DIRECTO al Postgres Railway que lee el lector; visibilidad instantanea, sin
gesto manual replicate+rebuild). PERO conservando forma Q: la verdad servida sigue
siendo el LOG (aec_log append-only) y graph_aec sigue siendo proyeccion regenerable
(I1 intacto: un rebuild completo desde aec_log = el estado que esta funcion dejo).

Un solo comando hace el cruce completo, ATOMICO (una transaccion):
  1. PUSH        cada evento del log local -> aec_log (ON CONFLICT line_sha DO NOTHING)
  2. PROYECTA    solo los eventos NUEVOS (rowcount==1) -> graph_aec incremental,
                 mismo SQL evento-por-evento que projection_build.rebuild_projection
  3. EMBEDDINGS  para las afirmaciones nuevas (Gemini @1536, task RETRIEVAL_DOCUMENT);
                 sin API key -> quedan NULL y lo reporta (corre un rebuild con
                 embeddings despues, o la busqueda cae a ILIKE)

Idempotencia: el gate es el INSERT a aec_log. Re-correr = 0 nuevos = 0 proyectados
(esto ademas evita duplicar referente_assert, que no tiene PK). Push y proyeccion
comparten transaccion: si la proyeccion falla, el push se revierte -> nunca queda
un aec_log adelantado a graph_aec.

El log JSONL local queda como WRITE-AHEAD/espejo: la ingesta local sigue escribiendo
ahi primero (offline sigue funcionando); este cruce empuja el delta y se auto-repara
(idempotente). Colapsa el SOL exportador: exporta_log.py y projection_build --replicate
quedan obsoletos para la operacion normal.

Membrana: cruza SOLO el log (content_hash, nunca bytes de snapshots/). psycopg2 directo
(sin sqlalchemy: consistente con el estilo stdlib del substrato). Sin emojis (Windows).

Uso:
    python nube.py --aec ../AEC                      # DATABASE_URL del entorno
    python nube.py --aec ../AEC --db-url postgres://...
(la ingesta lo invoca con --nube; ver ingesta.py)
"""
from __future__ import annotations
import os
import sys
import time
import logging

from exporta_log import iter_log_events, log_path_for

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))
# Reintentos ante flake transitorio de Gemini: un embedding NO debe quedar NULL
# por un fallo pasajero de red/API (HANDOFF CodeAEC 2026-11-12). Env-overridable.
EMBED_RETRIES = int(os.environ.get("EMBED_RETRIES", "3"))
EMBED_BACKOFF = float(os.environ.get("EMBED_BACKOFF", "0.5"))   # segundos, base; crece 2^i


def _ensure_tls() -> None:
    """Norton (u otro MITM corporativo) intercepta TLS con su CA raiz, que vive en el
    almacen de Windows pero NO en el bundle de Python -> urllib/google-genai revientan con
    CERTIFICATE_VERIFY_FAILED. truststore hace que Python valide contra el almacen del SO.
    Se antepone a CUALQUIER paso de red de este modulo (consolidar/embed_missing via CLI).
    Idempotente y no-fatal: si truststore no esta, avisa y sigue (puede no haber MITM)."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception as e:                         # pragma: no cover - entorno-dependiente
        logger.warning("truststore no disponible (%s); TLS sin fix de Norton", e)


# ---- embeddings del escritor (mismo proveedor que el lector; degradacion elegante) ----

def _embed_once(text: str) -> list:
    """UN intento real contra Gemini. Lanza en cualquier fallo (lo maneja el reintento).
    Factorizado para que `embed_gemini` pueda reintentar y los tests inyecten el intento."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    resp = client.models.embed_content(
        model=EMBEDDING_MODEL, contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT",
                                        output_dimensionality=EMBEDDING_DIM))
    return list(resp.embeddings[0].values)


def embed_gemini(text: str, attempt=_embed_once,
                 retries: int | None = None, backoff: float | None = None) -> list | None:
    """Embedding RETRIEVAL_DOCUMENT via google-genai, con reintento + backoff.
    None si no hay key/texto (fallo PERMANENTE: no se reintenta) o si agota reintentos
    (fallo transitorio persistente: se avisa ruidoso, el caller lo contabiliza por id).
    Espejo de Ek-Chuah-mcp/embeddings.py (mismo modelo/dim env-overridable).
    `attempt`/`retries`/`backoff` inyectables para falsar el reintento sin red."""
    key = os.environ.get("GEMINI_API_KEY", "")
    text = (text or "").strip()
    if not key or not text:
        return None                                # permanente: no hay nada que reintentar
    retries = EMBED_RETRIES if retries is None else retries
    backoff = EMBED_BACKOFF if backoff is None else backoff
    last = None
    for i in range(max(retries, 1)):
        try:
            return attempt(text)
        except Exception as e:
            last = e
            if i < retries - 1:
                logger.warning("Gemini embedding fallo (intento %d/%d): %s; reintento",
                               i + 1, retries, e)
                if backoff:
                    time.sleep(backoff * (2 ** i))
    logger.warning("Gemini embedding agoto %d reintentos: %s", retries, last)
    return None


# ---- proyeccion incremental de UN evento (espejo de projection_build, dialecto %s) ----

def _proyectar_evento(cur, ev: dict) -> str | None:
    """Aplica un evento a graph_aec. Devuelve el af_id si inserto una afirmacion
    (para embeddear despues). El SQL espeja projection_build.rebuild_projection
    evento-por-evento; la ATOMICIDAD y la no-duplicacion las garantiza el caller
    (solo llega aqui un evento cuyo INSERT a aec_log fue nuevo)."""
    kind = ev.get("ev")
    ts = ev.get("ts")
    if kind == "inscripcion":
        cur.execute(
            "INSERT INTO inscripcion VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (ev["id"], ev["premisa"], _j(ev["busqueda"]), _j(ev["resultados_crudos"]),
             ev["conclusion"], ev["inferidor_model"], ev["inferidor_ts"], ev["huella"], ts))
    elif kind == "necesidad":
        cur.execute(
            "INSERT INTO necesidad VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (ev["id"], ev["pregunta"], ev["gatillo"], ev.get("origen_nodo"), ts))
    elif kind == "consulta":
        cur.execute(
            "INSERT INTO consulta VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (ev["id"], ev["nec_id"], ev["formulacion"], ts))
    elif kind == "referencia":
        ref = ev["referente_id"]
        cur.execute("INSERT INTO referente VALUES (%s,%s) "
                    "ON CONFLICT (referente_id) DO NOTHING", (ref, ev["capture_ts"]))
        cur.execute("UPDATE referente SET primera_captura=%s "
                    "WHERE referente_id=%s AND primera_captura > %s",
                    (ev["capture_ts"], ref, ev["capture_ts"]))
        cur.execute(
            "INSERT INTO version VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (ev["id"], ref, ev["content_hash"], ev["url_cruda"], ev["capture_ts"],
             ev["fecha_fuente"], ev["q_id"], ev.get("estatus", "viva"), ts))
    elif kind == "afirmacion":
        cur.execute(
            "INSERT INTO afirmacion (id,txt,insc_id,ref_id,tipo,estatus,ts) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (ev["id"], ev["txt"], ev["insc_id"], ev.get("ref_id"),
             ev["tipo"], ev["estatus"], ts))
        return ev["id"]
    elif kind == "referente_assert":
        cur.execute("INSERT INTO referente_assert VALUES (%s,%s,%s,%s,%s,%s)",
                    (ev["id"], ev["referente_a"], ev["referente_b"],
                     ev["relacion"], ev["gatillo"], ts))
    elif kind == "revision":
        cur.execute(
            "INSERT INTO revision VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (ev["id"], ev["target_af"], ev["nuevo_estatus"],
             ev.get("reemplazada_por"), ev.get("motivo"), ev.get("gatillo"), ts))
        cur.execute("UPDATE afirmacion SET estatus=%s WHERE id=%s",
                    (ev["nuevo_estatus"], ev["target_af"]))
    return None


def _j(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ---- el cruce completo (push + proyeccion en UNA transaccion) ----

def consolidar(aec_root: str, connect, embed_fn=embed_gemini) -> dict:
    """Empuja el delta del log local a aec_log Y lo proyecta a graph_aec, atomico.

    connect: callable que devuelve una conexion DB-API (inyectable; el real es
    psycopg2.connect(db_url)). embed_fn inyectable (tests sin red).
    Devuelve evidencia citable: leidos/nuevos/proyectados/embebidos.
    """
    log_path = log_path_for(aec_root)
    cx = connect()
    leidos = nuevos = 0
    af_nuevas = []
    try:
        with cx:                                   # transaccion: commit/rollback atomico
            with cx.cursor() as cur:
                for sha, canon, ev in iter_log_events(log_path):
                    leidos += 1
                    cur.execute(
                        "INSERT INTO aec_log (line_sha, event) "
                        "VALUES (%s, CAST(%s AS jsonb)) "
                        "ON CONFLICT (line_sha) DO NOTHING", (sha, canon))
                    if cur.rowcount == 1:          # SOLO lo nuevo se proyecta (gate)
                        nuevos += 1
                        af_id = _proyectar_evento(cur, ev)
                        if af_id:
                            af_nuevas.append((af_id, ev.get("txt", "")))

        embebidas = 0
        fallidas_ids: list[str] = []               # ids que quedaron sin vector (dir. 8/12)
        if af_nuevas:
            with cx:
                with cx.cursor() as cur:
                    for af_id, txt in af_nuevas:
                        emb = embed_fn(txt) if embed_fn else None
                        if not emb:
                            fallidas_ids.append(af_id)   # NO silencioso: se reporta por id
                            continue
                        vec = "[" + ",".join(str(f) for f in emb) + "]"
                        cur.execute("UPDATE afirmacion SET embedding = CAST(%s AS vector) "
                                    "WHERE id=%s", (vec, af_id))
                        embebidas += 1
    finally:
        cx.close()

    return {"leidos": leidos, "nuevos": nuevos, "afirmaciones_nuevas": len(af_nuevas),
            "embebidas": embebidas, "sin_embedding": len(fallidas_ids),
            "ids_sin_embedding": fallidas_ids}


# ---- backfill idempotente de embeddings NULL (espejo de projection_build --embed-missing) ----

def embed_missing(connect, embed_fn=embed_gemini) -> dict:
    """Rellena SOLO las afirmaciones con `embedding IS NULL`, SIN TRUNCATE (no tumba al
    lector). Rompe la trampa del acoplamiento de `consolidar`: aqui la oportunidad de
    embeddear depende de la AUSENCIA del vector, no de la novedad del evento en el log
    -> re-correr SI repara un NULL que quedo de un cruce con Gemini caido (idempotente:
    `AND embedding IS NULL` en el UPDATE lo hace seguro ante carreras y re-corridas).

    Mantenimiento de indice: el embedding es regenerable (I1), excluido de dump_logico;
    no aporta contenido al grafo ni cruza la membrana del log. connect/embed_fn inyectables.
    Devuelve evidencia citable: candidatas/embebidas/fallidas (+ ids de las fallidas)."""
    cx = connect()
    candidatas: list = []
    embebidas = 0
    fallidas_ids: list[str] = []
    try:
        with cx:
            with cx.cursor() as cur:
                cur.execute("SELECT id, txt FROM afirmacion WHERE embedding IS NULL")
                candidatas = list(cur.fetchall())
        for af_id, txt in candidatas:
            emb = embed_fn(txt) if embed_fn else None
            if not emb:
                fallidas_ids.append(af_id)
                continue
            vec = "[" + ",".join(str(f) for f in emb) + "]"
            with cx:                               # una tx por fila: un fallo no pierde lo ya hecho
                with cx.cursor() as cur:
                    cur.execute("UPDATE afirmacion SET embedding = CAST(%s AS vector) "
                                "WHERE id=%s AND embedding IS NULL", (vec, af_id))
            embebidas += 1
    finally:
        cx.close()
    return {"candidatas": len(candidatas), "embebidas": embebidas,
            "fallidas": len(fallidas_ids), "ids_fallidas": fallidas_ids}


def _connect_real(db_url: str):
    import psycopg2
    return lambda: psycopg2.connect(db_url)


def _main(argv=None):
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(
        description="B realineado: empuja el delta del log local a aec_log y lo proyecta "
                    "a graph_aec en la nube, atomico e idempotente. Un comando, visible al instante.")
    ap.add_argument("--aec", default="../AEC", help="raiz del durable WORM (default: ../AEC)")
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                    help="DATABASE_URL del Postgres AEC (default: env DATABASE_URL)")
    ap.add_argument("--embed-missing", action="store_true",
                    help="backfill: rellena SOLO los embeddings NULL (sin TRUNCATE, idempotente); "
                         "no cruza el log. Para reparar NULL que quedaron de un Gemini caido.")
    args = ap.parse_args(argv)

    if not args.db_url:
        print("[nube] ERROR: falta DATABASE_URL (o --db-url).", file=sys.stderr)
        return 2

    _ensure_tls()                                  # Norton: fix TLS antes de tocar Gemini

    if args.embed_missing:
        res = embed_missing(_connect_real(args.db_url))
        print(f"[nube] embed-missing: candidatas={res['candidatas']} "
              f"embebidas={res['embebidas']} fallidas={res['fallidas']}")
        if res["fallidas"]:
            print(f"[nube] AVISO: {res['fallidas']} sin embedding tras reintentos. "
                  f"FALLARON: {', '.join(res['ids_fallidas'])}. Re-corre --embed-missing "
                  "(idempotente) cuando Gemini responda; ILIKE las ve mientras tanto.")
            return 1
        return 0

    res = consolidar(args.aec, _connect_real(args.db_url))
    print(f"[nube] leidos={res['leidos']} nuevos={res['nuevos']} "
          f"afirmaciones_nuevas={res['afirmaciones_nuevas']} "
          f"embebidas={res['embebidas']} de {res['afirmaciones_nuevas']}")
    if res["sin_embedding"]:
        print(f"[nube] AVISO: {res['sin_embedding']} afirmacion(es) sin embedding tras "
              f"reintentos. FALLARON: {', '.join(res['ids_sin_embedding'])}. "
              "Corre 'python nube.py --embed-missing' para rellenarlas (idempotente, "
              "solo-NULL); la busqueda ILIKE si las ve mientras tanto.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
