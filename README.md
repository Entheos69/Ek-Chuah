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

## Invariantes probadas (`tests/test_substrato.py`)

- **I1** -- borrar la `.db` y reconstruir del log = identico (el falsador que define C0).
- **I2** -- afirmacion load-bearing insegura si su version no tiene snapshot.
- **I4** -- afirmacion anclada a una VERSION (content-hash), nunca al referente; version
  actual = vista derivada.
- **WORM** -- snapshot idempotente; no hay `update` ni `delete`.
- Invariante de la tripleta; deteccion de huerfanos; normalizacion conservadora de URL.

## Correr

    python tests/test_substrato.py -v

## Diseno

`concept-sediment/docs/ek_chuah/DISENO_EK_CHUAH_C0_AEC_2026-06-26.md`

## Frontera

- Esto es el **substrato** (C0). Falta: materializacion nace-en-la-nube, MCP-AEC (nivel 2,
  jurisdiccion CodeMCP), inferidor real, replicacion 3-2-1 del log.
- Bifurcaciones abiertas: D-ver-2 (deteccion proactiva vs perezosa), D-ver-3 (vista por
  defecto), async-aporte (como una IA emite necesidad al Estratega).
