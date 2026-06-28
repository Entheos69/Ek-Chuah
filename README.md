# ek-chuah -- herramientas del tercer grafo (substrato C0, forma Q)

Greenfield. Solo stdlib. El **durable** vive FUERA de este repo, en `../AEC/`
(no committeable/pusheable por topologia). Este repo es **codigo** (tracked).

## Forma Q (event-sourcing)

- **Durable = log JSONL append-only** en `../AEC/log/inscripciones.jsonl` + **snapshots
  content-addressed** en `../AEC/snapshots/`. WORM por construccion (solo append; el
  snapshot es idempotente por content-hash).
- **Proyeccion = SQLite regenerable**, reconstruida SIEMPRE del log (`proyeccion.py`).
  Es desechable (gitignored). Borrar la `.db` y reconstruir del log = identico (falsador I1).

## Modulos

| Archivo | Rol |
|---|---|
| `nucleo.py` | `Inscripcion` (tripleta + conclusion firmada), huellas, divergencia. |
| `normaliza_url.py` | `canonical(URL)` = referente derivado (D-ver-1, norm conservadora). |
| `aec_store.py` | El materializador: UNICO escritor append-only del durable (WORM). |
| `via_epistemica.py` | Emision de eventos: necesidad -> consulta -> referencia(version) -> afirmacion. |
| `proyeccion.py` | Reconstruye la `.db` del log + consultas (traza, huerfanos, I2, version_actual). |
| `materializa.py` | Materializador programatico (snapshot a WORM + via en un paso; PoC/demo). |
| `materializa_orden.py` | Paso 2 (materializacion del flujo orden): baja cada URL de una orden YAML-AEC a WORM y rellena `content_hash`+`capture_ts`. Aqui vive la red. |
| `ingesta.py` | Paso 3 (ingesta): YAML-AEC -> lint C1-C7 -> verifica hash en WORM (C3) -> puebla `graph_aec`. Idempotente, CERO red. |
| `exporta_log.py` | Borde local -> nube (camino B): empuja `log/inscripciones.jsonl` a la tabla `aec_log` del Postgres MCP-AEC. Idempotente por `line_sha` (ON CONFLICT DO NOTHING). Membrana: SOLO el log, nunca snapshots. |

## Dependencias

Substrato (pasos 1-2): **solo stdlib**. `ingesta.py` (paso 3) usa **PyYAML** para parsear el
artefacto YAML-AEC (consistente con el gemelo `concept-sediment`; colapso Guardian 2026-06-27).
`exporta_log.py` (cruce real) usa **psycopg** (o `psycopg2`) para escribir a `aec_log` --
importado PEREZOSO: los tests y `--dry-run` corren sin red ni driver.

## Invariantes probadas (`tests/test_substrato.py` + `tests/test_ingesta.py`)

- **I1** -- borrar la `.db` y reconstruir del log = identico (el falsador que define C0).
- **I2** -- afirmacion load-bearing insegura si su version no tiene snapshot; la ingesta no
  puebla si el `content_hash` no resuelve en WORM (gate C3 "nace confirmada").
- **I3** -- cero huerfanos: toda afirmacion trae su via (referencia + inscripcion).
- **I4** -- afirmacion anclada a una VERSION (content-hash), nunca al referente; version
  actual = vista derivada.
- **E1** -- ingesta idempotente: re-ingerir el mismo YAML-AEC = no-op completo (el log no crece).
- **WORM** -- snapshot idempotente; no hay `update` ni `delete`.
- Invariante de la tripleta; deteccion de huerfanos; normalizacion conservadora de URL;
  rechazos de lint C1/C2/C4/C5/C6.

## Correr

    python -m unittest discover -s tests -p "test_*.py"

## Granos (los YAML-AEC)

Un grano = un YAML-AEC = una `necesidad` con su arbol (D-schema-2). Viven en
**`granos/<session_id>.yaml`** (tracked; el analogo a `sessions/` de concept-sediment, sin
reusar el nombre). El durable WORM (`../AEC`) y la proyeccion (`*.db`) NO son granos.

## Consolidar un grano (orden del Estratega -> graph_aec)

El grano llega como ORDEN con `content_hash`/`capture_ts` = `MATERIALIZAR`. Dos pasos,
**in-place** (el mismo archivo evoluciona orden -> materializado -> ingerido):

    # paso 2: baja la roca de cada URL a WORM y rellena los placeholders (RED; sancion del actor local)
    python materializa_orden.py granos/2026-06-27-001-Indagacion.yaml --aec ../AEC --consolidado-por "Guardian"

    # paso 3: lint C1-C7 + verifica hash en WORM -> puebla graph_aec (CERO red, idempotente)
    python ingesta.py granos/2026-06-27-001-Indagacion.yaml --aec ../AEC --db ek_chuah.db

    # solo validar sin escribir nada (falla en C3/C5 hasta materializar):
    python ingesta.py granos/2026-06-27-001-Indagacion.yaml --aec ../AEC --lint-only

## Exportar a la nube (camino B)

El MCP-AEC en la nube reconstruye `graph_aec` del **log replicado** (tabla `aec_log`),
no de la proyeccion empujada. `exporta_log.py` es el unico cruce nube <- local: empuja
las lineas de `log/inscripciones.jsonl` con `line_sha` identico al de `aec_store`
(idempotente; re-exportar = no-op). Membrana: SOLO el log, nunca `snapshots/`.

    # validar local sin la nube (lee y hashea, no escribe; sin red ni driver):
    python exporta_log.py --aec ../AEC --dry-run

    # cruce real (el Guardian provee el DATABASE_URL del store MCP-AEC):
    python exporta_log.py --aec ../AEC --db-url "$DATABASE_URL"

## Diseno

`concept-sediment/docs/ek_chuah/DISENO_EK_CHUAH_C0_AEC_2026-06-26.md`

## Frontera

- Pasos 1-4 en verde (substrato + materializacion + ingesta + lector C3 MCP-AEC desplegado).
  `exporta_log.py` (borde camino B) construido y probado offline (paridad `line_sha`,
  idempotencia, incremental, membrana). Falta el **cruce real**: el Guardian aprovisiona el
  `DATABASE_URL` del store MCP-AEC (rol con escritura a `aec_log`) y corre el exportador tras
  cada ingesta. Tambien: descarga de red real en el paso 2, inferidor real, replicacion 3-2-1.
- Bifurcaciones abiertas: D-ver-2 (deteccion proactiva vs perezosa), D-ver-3 (vista por
  defecto), async-aporte (como una IA emite necesidad al Estratega).
