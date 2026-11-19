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

- **Nucleo local: stdlib + PyYAML + truststore** (ya instalados). El camino B (`ingesta --nube`,
  LOCAL; canon realineado 14-sep) agrega `psycopg2-binary` + `google-genai`, ya en `requirements.txt`.
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

## Playbook: resolver un BLOQUEANTE (fuente muerta vs host vivo anti-bot)

**Primero clasifica el modo de fallo** -- no toda ref inalcanzable es una fuente muerta. Sondeo
directo: `python -c "import socket; socket.getaddrinfo('<host>',443)"` (DNS) y un `urlopen` con
timeout. `devolucion.py` ya hace esta clasificacion por ti (reusa el sondeo de prevuelo):

    python -c "import truststore; truststore.inject_into_ssl(); import devolucion, sys; sys.exit(devolucion._main(['granos/<grano>.yaml']))"

Clasifica cada ref load-bearing inalcanzable y anota el grano in-place con un bloque out-of-band
`reevaluacion:` (read-only vs WORM; materializa/ingesta lo ignoran):

- **`fabricacion`** (load-bearing + **DNS muerto**: el host no resuelve) -> la URL probablemente
  **nunca existio**. Señal de alucinacion del Estratega. NO la reemplaces tu: **devuelve el grano**
  al Estratega (ya trae el bloque `reevaluacion:`) para que retire o sustituya la afirmacion.
- **`degradacion`** (load-bearing + **TIMEOUT / HTTP 403 / ERROR**: el DNS SI resuelve) -> la fuente
  **existe y esta viva**, solo esta inalcanzable para el substrato. Dos sub-casos:
  - **Fuente realmente muerta/movida** (404, dominio caducado): re-anclar o quitar (ver abajo).
  - **Host vivo que rechaza al fetcher (anti-bot)**: NO esta muerta; tu lector/navegador la cruza
    pero `urllib` no. **No la reemplaces unilateralmente**: es el trazo epistemico del Estratega.
    **Devuelve el grano** (flujo B realineado: bloqueante -> `devolucion.py`, no parchear la roca).

**Experiencia acumulada -- hosts anti-bot medidos** (ver memoria `fetch-antibot-hosts.md`):
- **st.com** = tarpit Akamai; NO cruza `urllib` en ningun formato (HTML ni el PDF `/resource/...`),
  ni con UA de navegador a 40 s. Dato que solo vive ahi (p. ej. compromiso de longevidad): sacar
  del AEC, o **via de captura local** (ver abajo).
- **Farnell** = HTTP 403 determinista. Re-anclar a Digi-Key/Mouser del mismo MPN.
- **Mouser** = a veces HTML "Access denied" (PerimeterX) con HTTP 200 en vez del PDF (`%PDF-`).
- **Digi-Key** = baja con UA de navegador (403 ocasional = rate-limit; el resiliente reintenta).
- El rechazo es **host-especifico, no una ley general**: Renesas/TI publican datasheet PDF que baja;
  Digi-Key es distribuidor-ancla fiable. Anclar bien evita el bloqueante de raiz.

**Politica de ancla** (avalada Guardian 2026-11-18, `HANDOFF_Estratega_politica_ancla_descargable`):
el `survived_from` debe apuntar a una **roca que el substrato baje** (datasheet PDF del fabricante
que baje, o ficha de distribuidor que baje). El HTML de un fabricante anti-bot es **lectura, no
ancla**. Un precio es una lectura fechada -> anclar a distribuidor que baje, nunca consagrar por
captura manual una pagina de precio volatil.

**Si decides re-anclar** (fuente muerta real, o el Estratega te devuelve el grano re-emitido):
reemplaza por una **roca viva equivalente** que diga lo mismo que la `conclusion`/`txt`, descargable
y canonica (mirrors de datasheet verificados: `cdn.eicom.ru`, `store.comet.bg`, `piekarz.pl`; verifica
contenido con `pdftotext`+grep antes). Si la ref NO es load-bearing: **quitala** (mas honesto que
sustituir con una URL que no fue la evidencia). Luego vuelve a Etapa 1 y confirma OK.

Regla de decision: **DNS muerto load-bearing -> devolver (sospecha fabricacion); anti-bot/degradada
load-bearing -> devolver o re-anclar a roca descargable; no load-bearing -> quitar. Nunca inventes
la roca ni fabriques procedencia para pasar el gate.**

## Via de captura local (roca canonica tras un muro anti-bot)

Cuando un dato canonico SOLO vive en un host que `urllib` no cruza (st.com) y no quieres sacarlo
del AEC, el actor LOCAL (CodeEC via Claude-in-Chrome, o el Guardian a mano) guarda la pagina/PDF
como archivo y materializa DESDE el archivo, conservando la URL original como localizador:

1. Guarda el byte canonico en una carpeta que lea el grano (p. ej. `granos/capturas/<ref>.pdf`).
   Prefiere un documento canonico y byte-estable (datasheet PDF), no HTML de precio volatil.
2. En la ref del grano, ademas de `url` (se conserva como localizador), agrega:

       origen_local: "capturas/<ref>.pdf"   # ruta relativa a la carpeta del grano (no puede escapar)
       captura: "manual"
       captura_tool: "claude-in-chrome"       # o "guardian-manual"

3. Materializa normal: lee el byte del archivo (no de la red), calcula el hash y sella el
   `capture_ts` en la puerta (reloj sancionado, NUNCA el mtime). La URL queda intacta.
4. Ingiere normal: la procedencia (`captura: manual` + herramienta) **sedimenta en el log**
   (gate C9), para que WORM nunca presente una captura a mano como descarga `urllib`.

Membrana: el default sigue siendo `urllib`; la captura es la **excepcion marcada**. La conduce el
actor local (del mismo lado que el WORM), NO el Estratega (nube). La procedencia va al evento, nunca
al id determinista -> no mueve identidades (E1 intacta). Detalle de diseno: `NOTA_DEV_origen_local_captura`.

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
