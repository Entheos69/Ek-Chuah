---
name: desarrollar-ek-chuah
description: Modo desarrollo (Ek-Chuah). Usa esta skill para trabajar sobre el CODIGO / la maquinaria del pipeline de granos -- crear o modificar herramientas (prevuelo.py, materializa_orden.py, ingesta.py, consumido.py, exporta_log.py, proyeccion.py, aec_store.py, nucleo.py), refactorizar, agregar tests, y llevar el cambio a commit/PR/merge -- respetando los invariantes epistemicos del sistema (forma Q, WORM append-only, determinismo). NO es para consumir un grano concreto (eso es la skill "procesar-granos"). Dispara con "agrega una herramienta", "modifica el pipeline", "refactoriza ingesta", "escribe un test", "modo desarrollo", "desarrolla en Ek-Chuah".
---

# Modo desarrollo (Ek-Chuah)

Trabajas sobre la **maquinaria** del sistema, no sobre un grano. El objetivo es cambiar el
codigo sin romper los invariantes que el sistema existe para proteger: **una afirmacion se
ancla a una roca real** y **el log durable es la unica verdad**. Contraparte: para *consumir*
un grano (materializar/ingerir uno de `granos/*.yaml`), usa la skill **`procesar-granos`**.

## Arquitectura en una pagina (leela antes de tocar nada)

- **Forma Q (event-sourcing).** El durable es un **log JSONL append-only** (`../AEC/log/inscripciones.jsonl`)
  mas **snapshots content-addressed** (`../AEC/snapshots/<sha256>`, las "rocas"). El durable vive
  **FUERA del repo** (hermano: `../AEC`) por topologia, no por `.gitignore`.
- **`aec_store.py`** es el UNICO escritor: solo verbos de **APPEND** (`append_event`, `put_snapshot`).
  No hay update ni delete -> WORM por construccion. El snapshot no se re-escribe (idempotente por hash).
- **`proyeccion.py` (graph_aec / SQLite) es DESECHABLE**: se reconstruye del log (`reconstruir`).
  Nunca la trates como fuente de verdad; `*.db` esta gitignored.
- **`nucleo.py`**: identidades. `huella_insumos(premisa,busqueda,resultados)` = identidad de la
  roca-inscripcion; `content_hash(bytes)` = identidad de la version (I4). ISO fijo, reloj sancionado.
- **Ids deterministas.** Los ids de evento se derivan del CONTENIDO (`ingesta._det_id`, `huella_insumos`),
  no uuid -> re-ingerir el mismo YAML es un no-op (E1, idempotencia). Esto es sagrado: no lo rompas.

### Pipeline (quien hace que)
1. **`prevuelo.py`** -- pre-flight: sondea URLs por severidad. Read-only, no escribe.
2. **`materializa_orden.py`** -- baja rocas a WORM (RED, no idempotente por naturaleza, resiliente por-ref).
3. **`ingesta.py`** -- lint C1-C7 + gate C3 (verifica roca en WORM, CERO red) + append log + rebuild.
4. **`consumido.py`** -- ¿ya fue ingerido? Cruza ids deterministas contra el log. CERO red/escritura.
5. **`exporta_log.py`** -- export del log a la nube (camino B). Membrana: SOLO el log, nunca snapshots.

## Inventario de herramientas (abstracto de referencia)

Caracterizacion de cada modulo para NO re-investigar. Formato: **rol** | API clave | invariante/trampa.

### Substrato (identidad y durable)
- **`nucleo.py`** -- *el algebra de identidades y las estructuras de inscripcion.*
  `huella_insumos(premisa,busqueda,resultados)` = id de la roca-inscripcion (sha256 sobre los TRES
  insumos, canonicalizados); `content_hash(bytes)` = id de la VERSION (I4); `ISO` = formato de reloj;
  dataclasses `Inferidor`/`Inscripcion` con `invariante_ok`/`integridad_ok`. **Trampa:** la huella se
  computa sobre `_canon` (json sort_keys, separators fijos); cualquier cambio ahi re-mapea TODAS las
  identidades -> jamas lo toques a la ligera. La conclusion NO entra en la huella (es re-derivable).
- **`aec_store.py`** -- *el UNICO escritor del durable (WORM append-only).* `AecStore(root)` con
  `append_event` (log JSONL, modo 'a', sella `ts` si falta, json canonico), `put_snapshot(bytes)->hash`
  (content-addressed, `os.replace` atomico, no re-escribe), `has_snapshot`, `read_snapshot`, `iter_events`.
  **Invariante:** solo verbos de APPEND; no hay update/delete. Todo lo demas que escriba durable pasa por aqui.

### Lado emision (escribe eventos al log)
- **`via_epistemica.py`** -- *la cadena causal del saber (necesidad -> consulta -> version -> afirmacion),
  con ids uuid propios.* Cada metodo EMITE un evento via `aec_store`. Separa REFERENTE (canonical URL) de
  VERSION (content-hash); la afirmacion se ancla a la VERSION, nunca al referente mutable. **Nota:** la
  ingesta NO reusa esta clase (usa ids DETERMINISTAS via `derivar_eventos`) para no depender de uuids; ver
  el docstring de `ingesta`. Es la via "manual" / de referencia del modelo, no el camino de consumo de granos.
- **`materializa.py`** -- *materializador del flujo "nace-en-la-nube"* (el Estratega sanciona en la nube; este
  brazo local aterriza lo sancionado: snapshot + via + inscripcion + afirmacion). **Distinto de
  `materializa_orden.py`** (que es el paso 2 sobre una ORDEN YAML con placeholders `MATERIALIZAR`). No lo
  confundas: el pipeline de granos usa `materializa_orden`, no este.

### Lado lectura (CQRS, sobre la .db desechable)
- **`proyeccion.py`** -- *reconstruye graph_aec (SQLite) del log y lo consulta.* `reconstruir(store,db)` borra
  y regenera SIEMPRE del log (falsador I1: N rebuilds = mismo contenido logico; nada se inventa aqui, todo
  viene del log). Vistas: `version_actual` (I4: ultimo capture_ts, NO flag persistido), `huerfanos`
  (afirmacion sin ref/insc), `load_bearing_inseguras` (I2: afirmado cuya version no tiene snapshot),
  `traza_ascendente` (afirmacion -> necesidad), `dump_logico` (volcado canonico para comparar rebuilds).
  **Invariante:** la .db es DESECHABLE (`*.db` gitignored); nunca la trates como verdad ni le agregues estado
  que no derive del log. `INSERT OR IGNORE` en todo -> orden-independiente e idempotente.

### Utilidades
- **`normaliza_url.py`** -- *canonical(URL) = referente_id* (D-ver-1). Normalizacion CONSERVADORA: colapsa
  http/https, fragmento, params de tracking (utm_*, fbclid, gclid...), slash final y orden de query; NO
  fusiona paginas distintas (no borra otros params). **Regla:** bajo-normalizar antes que fusionar. Tres
  identidades que NUNCA se conflan: locator (URL cruda) / referente (canonical) / contenido (content-hash).
- **`demo_aec.py`** -- *demo end-to-end sobre AEC TEMPORAL* (nunca el durable real). Inscribe, reconstruye,
  muestra traza + version_actual + huerfanos=0 + falsador I1. Util como ejemplo ejecutable de la forma Q.

### Pipeline de granos (los 4 pasos, detalle en la seccion Pipeline arriba)
- **`prevuelo.py`** | `prevuelo(doc, probe=_probe_urllib)`, severidades BLOQUEANTE/AVISO/OK; `probe` inyectable.
  Baja el cuerpo COMPLETO al sondear (para cazar el host que sirve 200 y se cuelga). Read-only.
- **`materializa_orden.py`** | `materializar_orden(doc,store,fetch=...)`, muta el doc in-place, resiliente
  por-ref (una URL muerta no tumba el grano; queda en `MATERIALIZAR`), `fetch` inyectable. Escribe snapshots.
- **`ingesta.py`** | `derivar_eventos(doc)` (PURA, fuente unica de ids) -> `ingest_doc` (lint C1-C7 + gate C3 +
  append). `lint(doc,store)` devuelve errores bloqueantes; `session_id_de`. CERO red. Idempotente (E1).
- **`consumido.py`** | `estado_doc/estado_grano/escanear_granos`, estados CONSUMIDO/NO-CONSUMIDO/PARCIAL/VACIO.
  Reusa `derivar_eventos` -> CONSUMIDO == ingesta seria no-op. CERO red/escritura; no exige rocas en WORM.
- **`exporta_log.py`** | `export_log(log_path, sink)` con `MemorySink` (tests/--dry-run) o `PostgresSink`
  (driver perezoso). Idempotente por `line_sha` (sha de la linea canonica, espejo de `append_event`).
  Membrana: SOLO el log, jamas snapshots. Direccion unica local -> nube.

## Reglas de diseno (el porque, no solo el que)

- **Separacion load-bearing.** La RED (descarga, no idempotente) vive SOLO en el paso 2. La ingesta
  es local, determinista, idempotente. No metas red en la ingesta ni escritura durable en el prevuelo.
  Captura-primero-luego-ingesta: lo peor que puede quedar es un blob WORM huerfano (inocuo), nunca
  una afirmacion sin roca.
- **Una sola fuente de verdad de los ids.** Si dos sitios necesitan los mismos ids deterministas,
  extrae una **funcion pura compartida** en vez de duplicar la logica. Ejemplo canonico:
  `ingesta.derivar_eventos` la usan `ingest_doc` (filtra los ya presentes y appendea) y `consumido.py`
  (cruza contra el log) -> "consumido" == "la ingesta seria no-op", sin drift. Duplicar = bug futuro.
- **Nunca fabriques procedencia.** Ninguna herramienta debe permitir que una afirmacion pase el gate
  sin su roca real. Si un cambio facilita saltarse C3, es un cambio malo aunque los tests pasen.
- **Solo stdlib + PyYAML + truststore.** `psycopg` solo en el export. No agregues dependencias sin
  una razon fuerte; el sistema se precia de correr con casi nada.
- **Sin emojis / solo ASCII en el codigo y la salida.** El encoding de Windows revienta con emojis.
  Todos los modulos existentes lo respetan; siguelo.
- **Inyecta las dependencias de red.** `fetch`/`probe` son inyectables (default urllib) para que los
  tests NO toquen la red. Cualquier herramienta nueva con red debe hacer lo mismo.

## Flujo de trabajo

1. **Entiende antes de escribir.** Lee los modulos afectados y sus tests (`tests/test_*.py`). Los tests
   son **falsadores** del axioma, no cobertura: cada uno paga un invariante (idempotencia, gate C3,
   huerfanos=0, rebuild identico). Imitalos.
2. **Implementa** respetando las reglas de arriba. Reutiliza (funcion pura compartida) antes de duplicar.
3. **Tests primero-o-junto.** Agrega `tests/test_<modulo>.py` que falsee el nuevo axioma. Usa tempdirs
   (`tempfile.mkdtemp` + `AecStore(tmp)`), nunca el durable real. Patron: probe/fetch inyectado.
4. **Corre TODA la suite** (no solo lo tuyo):

       python -m unittest discover -s tests -p "test_*.py"

   Debe quedar en verde. Si tu cambio toca la ingesta, confirma tambien que un grano real sigue
   dando `INGESTA OK ... huerfanos=0` y `consumido.py` reporta CONSUMIDO.
5. **Documenta.** Actualiza `README.md` y la skill relevante (`procesar-granos` si cambiaste el flujo de
   consumo; esta skill si cambiaste la arquitectura). Actualiza la memoria si el estado del proyecto cambia.
6. **Commit / PR / merge** (ver abajo).

## Entorno y git (trampas reales de este repo)

- **Red en el sandbox: Norton rompe el SSL.** Antepon `truststore.inject_into_ssl()` a cualquier
  paso que toque la red (ver skill `procesar-granos`). No aplica a pasos sin red (ingesta, consumido, tests).
- **Corre siempre desde la raiz del repo.** El `--aec` default es `../AEC` en todos los modulos; manten
  ese contrato (paso 2 y paso 3 DEBEN usar el mismo root o el gate C3 no encuentra el snapshot).
- **La herramienta Bash es Git Bash (POSIX sh), NO PowerShell.** Para mensajes de commit multilinea usa
  un archivo (`git commit -F msg.txt`) o un heredoc POSIX (`<<'EOF'`). **NUNCA** `@'...'@` (here-string de
  PowerShell) en Bash: se cuela literal en el mensaje. (Pasa de verdad; ya mordio una vez.)
- **Convencion de commits:** `tipo(ek-chuah): resumen` (feat/fix/chore/refactor). Cierra el cuerpo con
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Separa cambios de codigo de cambios de datos
  (granos) en commits distintos.
- **Branch + PR.** Trabaja en una rama `feat/...`; no commitees directo en `main` sin permiso. PR con `gh`:
  `gh pr create --base main --head <rama> --title ... --body-file pr.md`. Cierra el body con la linea
  `Generated with Claude Code`. Merge con `gh pr merge <n> --merge --delete-branch` cuando el usuario lo pida.
- **Confirma acciones hacia afuera** (push, PR, merge) con el usuario antes de ejecutarlas.

## Checklist de "hecho"

- [ ] Suite completa en verde (`unittest discover`).
- [ ] Ningun camino nuevo permite afirmacion-sin-roca ni salta el gate C3.
- [ ] Sin duplicar logica de ids (funcion pura compartida donde aplique).
- [ ] Solo stdlib/PyYAML/truststore; sin emojis; red inyectable.
- [ ] README + skill(s) + memoria actualizados si cambio el contrato o el estado.
- [ ] Commits limpios (codigo vs datos separados), rama + PR, merge solo con OK del usuario.
