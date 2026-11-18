# NOTA DEV -- Via de captura local: materializar desde archivo conservando la URL original

- De: CodeEC @Ek-Chuah
- Firma: 2026-11-18T12:32-06:00
- Modo: `desarrollar-ek-chuah` (toca la maquinaria: `materializa_orden`, esquema de ref, ingesta, tests)
- Estado: **spec avalado por el Guardian 2026-11-18, NO implementado.** No bloquea ningun grano.
- Origen: Opcion A del Estratega (captura local con navegador, conservando la URL) para hosts anti-bot
  (st.com tarpit). Ver `HANDOFF_Estratega_politica_ancla_descargable_20261118.md`.

## Problema que resuelve

Un dato canonico que **solo** vive tras un muro anti-bot (p. ej. el datasheet de ST, que `urllib`
no cruza en ningun formato). Hoy no hay forma de llevar esa roca a WORM sin que el fetcher baje
los bytes el mismo.

## Lo que YA existe (no re-implementar)

`materializa_orden._fetch_urllib` (linea 42) abre `file://` nativamente -- su docstring lo dice:
*"file:// tambien sirve"*. Si una ref tuviera `url: file:///C:/.../x.pdf`, materializa ya calcularia
el hash, sellaria `capture_ts` y snapshotaria a WORM. **El fetch local ya funciona.**

## Lo que FALTA (el dev real, chico y especifico)

El hueco no es leer el archivo: es que hoy `url` es **a la vez localizador y fuente de bytes**
(`materializar_orden` baja de `r["url"]` y lo guarda como procedencia). Usar `file://` como `url`
**perderia la URL original** y mentiria sobre la procedencia. Falta:

### 1. Separar localizador de fuente de bytes (campo `origen_local`)

En la ref, un campo opcional:

```yaml
- local_id: r3
  url: "https://www.st.com/.../stm8af6266.html"   # localizador canonico, SE CONSERVA
  origen_local: "capturas/r3_stm8af6266.pdf"       # de aqui salen los BYTES (ruta local)
  captura: "manual"                                 # procedencia: navegador, no urllib
  captura_tool: "claude-in-chrome"                  # o "guardian-manual"
  content_hash: "MATERIALIZAR"
  capture_ts: "MATERIALIZAR"
```

`materializar_orden`: si `origen_local` esta presente y la ref sigue en MATERIALIZAR, **lee los bytes
de ese archivo** (no de `url`), calcula hash, sella `capture_ts`, snapshota a WORM, **y deja `url`
intacto** como localizador. Si falta `origen_local`, comportamiento actual (baja de `url`).

### 2. La procedencia manual debe SEDIMENTAR en el log, no solo en el YAML

Critico para el invariante (forma Q / determinismo): WORM nunca debe afirmar una descarga `urllib`
que no ocurrio. `captura: manual` + `captura_tool` tienen que viajar al **evento de referencia** del
log (`ingesta.derivar_eventos`, donde hoy va `referente_id`/`content_hash`/`capture_ts`), para que
el durable registre **como** se obtuvieron los bytes. Un lector del log debe poder distinguir una
roca bajada automatica de una capturada a mano.

### 3. Lint de la ingesta debe tolerar/validar los campos nuevos

Verificar que C1-C7 no rechacen `origen_local`/`captura`/`captura_tool` (campos desconocidos). Mejor:
una regla **C-nueva** suave -> si `captura: manual`, el evento DEBE llevar la marca de procedencia
(no se puede capturar a mano y presentarlo como descarga limpia).

## Membrana / politica de uso

- **Default inamovible: `urllib`.** La captura local es la **excepcion marcada**, solo para hosts
  anti-bot canonicos (datasheet PDF). **Nunca** para una pagina de precio volatil.
- **Quien guarda el archivo:** el actor local de esta maquina -- CodeEC (via Claude-in-Chrome) o el
  Guardian a mano. NO el Estratega (nube): cruzaria al plano fisico que su protocolo le veda. El hash
  y el reloj los pone siempre CodeEC en la puerta.
- **Reproducibilidad:** una captura manual es menos reproducible que una descarga; por eso la marca
  `captura: manual` es **obligatoria** y auditable en el log. Preferir capturar documentos **canonicos
  y byte-estables** (PDF con DocID/rev), no HTML renderizado.

## Esbozo de implementacion

- `materializa_orden.py`: en el loop de `materializar_orden`, si `r.get("origen_local")`, fetch =
  leer ese archivo (ruta relativa a la raiz del grano o absoluta validada); conservar `url`; propagar
  `captura`/`captura_tool` al resultado.
- `ingesta.py` (`derivar_eventos`): incluir `captura`/`captura_tool` en el payload del evento
  `referencia`; agregar la regla de lint de procedencia.
- Esquema de ref: documentar `origen_local`, `captura`, `captura_tool` como opcionales.
- Tests (sin red): materializar una ref con `origen_local` apuntando a un archivo de prueba; afirmar
  que `url` se conserva, que el hash es el del archivo, y que el evento del log lleva la marca manual.
- Actualizar skill `procesar-granos` y `desarrollar-ek-chuah` con la via y su politica de uso.

## Known unknowns

- Ruta de `origen_local`: relativa a la raiz del repo vs absoluta. Propuesta: relativa a la carpeta
  del grano, validada para no escapar (no `..`). A decidir en implementacion.
- Si conviene que CodeEC conduzca Claude-in-Chrome para la captura (probado que esta disponible) o
  dejarlo como guardado manual del Guardian. El Guardian decide tras ver salir el grano por la via C.
