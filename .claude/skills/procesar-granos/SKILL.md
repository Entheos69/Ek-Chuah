---
name: procesar-granos
description: Modo consumo / procesamiento de granos (Ek-Chuah). Usa esta skill para consolidar/procesar/ingerir/CONSUMIR un grano YAML-AEC (granos/*.yaml) al durable WORM y a graph_aec -- llevar un grano de ORDEN (content_hash MATERIALIZAR) a ingerido, y para VERIFICAR si ya fue consumido. Cubre el pre-flight preventivo de URLs, el fix de SSL (Norton), la materializacion resiliente, la ingesta con gate C3, la verificacion de consumo (consumido.py), y como resolver fuentes muertas sin romper la integridad epistemica. Dispara con "procesa el grano", "consolida el grano", "consume el grano", "ingiere el YAML-AEC", "materializa la orden", "verifica si el grano fue consumido", "modo consumo", "modo procesamiento de granos". Para trabajar sobre el codigo/maquinaria del pipeline (no sobre un grano), usa la skill "desarrollar-ek-chuah".
---

# Modo procesamiento de granos (Ek-Chuah)

Un **grano** = `granos/<session_id>.yaml` = una `necesidad` con su arbol (inscripciones,
consultas->referencias, afirmaciones). Nace como **ORDEN** del Estratega con
`content_hash`/`capture_ts` = `MATERIALIZAR`. Tu trabajo: llevarlo **in-place** por el
pipeline hasta quedar ingerido en `graph_aec`, sin que ninguna afirmacion nazca sin roca.

Principio rector: **una afirmacion se ancla a una ROCA real en WORM** (I2/I4, gate C3
"nace confirmada"). Si la roca no existe/no baja, el grano NO se ingiere hasta resolverlo.
**Nunca fabriques procedencia** (no sustituyas una URL muerta por otra descargable solo
para pasar el gate): eso corrompe justo lo que el sistema protege.

## Entorno (lee esto primero)

- **Windows + Norton rompe el SSL en el sandbox.** Norton intercepta TLS (MITM) con su CA
  raiz, que esta en el almacen de Windows pero no en el bundle de Python -> `urllib` revienta
  con `CERTIFICATE_VERIFY_FAILED`. Fix: **`truststore.inject_into_ssl()`** hace que Python
  valide contra el almacen del SO. Antepon esto a cualquier paso que toque la red:

      python -c "import truststore; truststore.inject_into_ssl(); import prevuelo, sys; sys.exit(prevuelo._main(['granos/<grano>.yaml']))"

- **Solo stdlib + PyYAML + truststore** (ya instalados). `psycopg` solo para el export (camino B).
- Corre siempre desde la raiz del repo. El durable WORM vive FUERA del repo en `../AEC`.

## Pipeline (3 etapas, in-place)

### Etapa 1 -- Pre-flight (preventivo, NO escribe nada)

Sondea las URLs pendientes ANTES de bajar nada y localiza los huecos por severidad:

    python -c "import truststore; truststore.inject_into_ssl(); import prevuelo, sys; sys.exit(prevuelo._main(['granos/<grano>.yaml']))"

Lectura del reporte (`[LB]` = load-bearing: la ref sostiene una afirmacion via `survived_from`):

- **BLOQUEANTE** (ref inalcanzable + load-bearing): la afirmacion nace sin ancla.
  **Resuelvela ANTES de materializar** (ver playbook abajo).
- **AVISO** (ref inalcanzable + NO load-bearing): puedes **quitar la referencia** del grano.
- **OK**: la roca baja; lista para materializar.

Exit 0 = sin bloqueantes. Exit 1 = hay bloqueantes; no avances hasta resolver.

### Etapa 2 -- Materializar (baja la roca a WORM; RED)

    python -c "import truststore; truststore.inject_into_ssl(); import materializa_orden as m; m._main(['granos/<grano>.yaml','--consolidado-por','Guardian'])"

- Es **resiliente**: una URL muerta ya no aborta el grano; baja las demas, persiste el
  progreso, y deja la fallida en `MATERIALIZAR` reportando su severidad (exit 1 si hubo fallidas).
- **Idempotente**: re-correr solo re-intenta las pendientes (WORM dedup por content-hash).
- `--timeout N` si algun host es lento.

### Etapa 3 -- Ingerir (lint C1-C7 + gate C3 + append log + rebuild SQLite; CERO red)

    python ingesta.py granos/<grano>.yaml --aec ../AEC --db ek_chuah.db

- **`--aec` DEBE ser el MISMO root que uso el paso 2** (default `../AEC` en ambos). Si difieren,
  el gate C3 no encuentra el snapshot y rechaza ("content_hash no resuelve en WORM").
- Para validar sin escribir: `python ingesta.py granos/<grano>.yaml --aec ../AEC --lint-only`.
- **Exito** = `INGESTA OK: ... huerfanos=0`. Idempotente (E1): re-ingerir = no-op.

## Playbook: resolver una fuente muerta

1. **Confirma el modo de fallo** con un sondeo directo (DNS vs timeout vs HTTP):
   `python -c "import socket; socket.getaddrinfo('<host>',443)"` (DNS), o un `urlopen` con timeout.
2. **Es load-bearing** (sostiene una afirmacion): **reemplaza la fuente** por una **roca viva
   equivalente** que diga lo mismo que la `conclusion`/`txt` ya registrada. Busca en la web una
   fuente durable y canonica (evita DDNS gratuitos / hosts efimeros). Edita solo `<ref>.url` y
   re-materializa. Justificacion: el claim es real; re-anclas la MISMA afirmacion a una roca
   verdadera.
3. **NO es load-bearing** (ninguna afirmacion tiene `survived_from: <ese ref>`): **quita la
   referencia** del grano. Quitar es mas honesto que sustituir con una URL que no fue la evidencia.
4. Vuelve a la Etapa 1 y confirma OK antes de materializar/ingerir.

Regla de decision: **load-bearing muerta -> reemplaza; no load-bearing muerta -> quita.**
Nunca inventes la roca.

## Verificar el consumo (¿ya fue ingerido?)

Para saber si un grano YA fue consumido (ingerido al durable) **sin tocar la red ni escribir**,
y sin depender de la palabra de nadie:

    python consumido.py                         # escanea granos/ y da el resumen
    python consumido.py granos/<grano>.yaml     # un grano en concreto
    python consumido.py --json                  # salida maquinable (gates/scripts)

- Cruza los ids **deterministas** del grano contra el log durable (misma `derivar_eventos` que
  usa la ingesta) -> **CONSUMIDO** == "la ingesta seria un no-op". A diferencia del gate C3,
  **NO exige que las rocas esten en WORM**: solo compara ids. CERO red, CERO escritura.
- Estados: **CONSUMIDO** (todos los eventos en el log), **NO-CONSUMIDO** (ninguno),
  **PARCIAL** (grano editado tras ingerir: las afirmaciones/refs cambiadas ya no matchean),
  **VACIO** (no es un YAML-AEC).
- **Exit 1** si algo no esta consumido -> sirve de gate en scripts.
- Úsalo tras ingerir para confirmar, o al retomar para saber que falta.

## Export a la nube (camino B, opcional, tras ingerir)

    python exporta_log.py --aec ../AEC --dry-run                 # valida local (sin red)
    python exporta_log.py --aec ../AEC --db-url "$DATABASE_URL"  # cruce real (Guardian provee la URL)

Membrana: SOLO el log (`log/inscripciones.jsonl`), nunca `snapshots/`. Idempotente por `line_sha`.

## Verificacion

Antes de dar por hecho el grano: `python -m unittest discover -s tests -p "test_*.py"` en verde,
e ingesta reportando `huerfanos=0`.
