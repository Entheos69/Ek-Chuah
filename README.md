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
| `materializa.py` | Paso 2 (materializacion): aterriza una solicitud sancionada (snapshot a WORM + via). |
| `ingesta.py` | Paso 3 (ingesta): YAML-AEC -> lint C1-C7 -> verifica hash en WORM (C3) -> puebla `graph_aec`. Idempotente, CERO red. |

## Dependencias

Substrato (pasos 1-2): **solo stdlib**. `ingesta.py` (paso 3) usa **PyYAML** para parsear el
artefacto YAML-AEC (consistente con el gemelo `concept-sediment`; colapso Guardian 2026-06-27).

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

## Ingerir un grano (paso 3)

    python ingesta.py <grano.yaml> --aec ../AEC --db ek_chuah.db   # puebla el durable real (sancion Guardian)
    python ingesta.py <grano.yaml> --aec ../AEC --lint-only        # solo lintea, no escribe

## Diseno

`concept-sediment/docs/ek_chuah/DISENO_EK_CHUAH_C0_AEC_2026-06-26.md`

## Frontera

- Pasos 1-3 (substrato + materializacion + ingesta) en verde. Falta: MCP-AEC lector C3
  (nivel 2, jurisdiccion CodeMCP, paso 4 -- se desbloquea cuando `graph_aec` tiene >=1 grano
  real ingerido), descarga de red real en el paso 2, inferidor real, replicacion 3-2-1 del log.
- Bifurcaciones abiertas: D-ver-2 (deteccion proactiva vs perezosa), D-ver-3 (vista por
  defecto), async-aporte (como una IA emite necesidad al Estratega).
