# Reporte de solicitud: sancion externa e items fuera de scope local

**Fecha:** 2026-08-19 · **Emisor:** CodeEC (desarrollo Ek-Chuah, modo `desarrollar-ek-chuah`)
**Gatillo:** `explicito:'1,2,3 en orden ... necesito pedido explicito para Estratega y las
modificaciones pertinentes fuera de nuestro scope; necesitamos reporte de solicitud a los
agentes pertinentes'` (Guardian).
**Contexto:** ponderacion del `DICTAMEN_alcance_ekchuah_20260819` (Estratega-Nube). Lo que era
**nuestro** ya esta implementado y mergeable (PR #4: gate `aec_verify` + lint C0/C2/C3-emision,
suite 75/75). Este reporte rutea lo que **no** es nuestro y requiere sancion o decision ajena.

## 0. Mapa de bloqueo (lo que el Guardian pidio distinguir)

| Item | Destinatario | Naturaleza | ¿Bloqueante? |
| :-- | :-- | :-- | :-- |
| §4 umbral `aec_search` | CodeMCP | tecnica, otro repo | **NO** -- independiente, arrancable ya |
| §2 testigo de captura | CodeCS + CodeMCP + Estratega | schema aec-1 | **SI** -- espera co-sancion (D1 + A3) |
| §3 fuentes autenticadas | Guardian | politica del grafo | **SI** -- espera decision (A2) |
| Reconciliacion granos 06-29 | Guardian | identidad + durable | **SI** -- espera decision (A1) |
| Consumo grano 08-18 | Estratega (sancion) + local | dato pendiente | parcial -- ver B1 |

**Los dos diferidos que derivan a sancion externa BLOQUEANTE son §2 (testigo) y §3 (auth).**
§4 es externo pero NO bloqueado: puede empezar hoy y es el mayor costo/beneficio del dictamen.

---

## A. Al GUARDIAN -- decisiones de identidad y de politica

### A1. Reconciliacion de identidad-doble en granos historicos (BLOQUEANTE, hallazgo nuevo)

Al implementar C0 (`basename == session_id`) el check cazo un corrimiento REAL:

- `granos/2026-06-29-002-Indagacion.yaml` -> `meta.session_id: 2026-06-29-001-Indagacion`
- `granos/2026-06-29-003-Indagacion.yaml` -> `meta.session_id: 2026-06-29-002-Indagacion`

El sid `-001` lo reclaman dos archivos; ningun archivo declara `-003`. **Ambos ya estan
consumidos** (`consumido.py`: 002 -> 13/13, 003 -> 7/7): sus eventos viven en el durable WORM
bajo el sid corrido. No hubo colision de datos (las preguntas difieren -> ids de necesidad
distintos), pero la **agrupacion por sesion en `graph_aec` esta mal atribuida**.

**Por que no lo arregle:** el durable es append-only (no se reescribe el sid ya inscrito), y
re-ingerir el YAML corregido emitiria eventos NUEVOS bajo el sid correcto -> duplicados. La
correccion no es un edit: es una decision de identidad + posible intervencion durable.

**Solicito decision:** cual es la identidad canonica de cada grano (¿el nombre del archivo o el
`session_id` declarado?), y si se corrige via revision/nota append-only o se deja anotado como
deuda conocida. Recomendacion CodeEC: fijar el `session_id` = basename (el nombre es el ancla
humana), corregir los YAML, y emitir una nota de reconciliacion en el log en vez de re-ingerir.

### A2. §3 fuentes tras autenticacion (BLOQUEANTE, politica del grafo)

El navegador puede leer con sesion (portales de proveedor, fichas tras registro) -- alto valor
para INDUPOX/CRM, pero **el actor local no puede re-bajar esas URLs** -> sin re-bajada no hay
`content_hash` re-derivable -> C3 no pasa. Tres salidas del dictamen: (a) excluirlas, (b) roca
sin re-bajada (pasa de *verificable* a *atestiguado*, exige marca `origen: sesion-autenticada`),
(c) solo como reconocimiento (citar la fuente publica equivalente).

**Solicito decision de politica.** Recomendacion del Estratega, que CodeEC comparte: **(c) por
defecto; (b) solo con sancion explicita y marca en la referencia.** (b) sin marca es como un
grafo verificable se degrada a rumores bien formateados.

### A3. §2 discrepancia de specs de offset ISO (BLOQUEANTE para el testigo)

`ek-chuah-yaml-aec §3` escribe `ts` sin offset; `episteme-minimo dir.13` lo exige siempre (D2,
falla F71). Hoy toleramos ambos (`ingesta._iso_ok` acepta con/sin offset; `aec_verify` avisa D2,
no falla). Irresoluble sin sancion: 'CST' es UTC-6 y China Standard Time a la vez.

**Solicito decision:** ¿el offset numerico es obligatorio en todo artefacto durable? Si si, hay
que endurecer `_iso_ok` (aviso -> fallo) y migrar los granos sin offset. Esto es prerequisito
del testigo §2 (su hash depende de un reloj sin ambiguedad).

---

## B. Al ESTRATEGA -- pedido explicito (gatillo bien formado)

### B1. Sancion del claim colateral §1 (grano 08-18 sin consumir)

El §1 del dictamen midio, con la fuente enfrente, que el claim de precios Railway del grano
`2026-07-12` **sigue vigente a 38 dias** (`Hobby $5 minimum usage`, `99.9% Availability Target`).
Se materializo el grano `granos/2026-08-18-001-Indagacion.yaml`, pero esta en ORDEN
(placeholders `MATERIALIZAR`) y **NO consumido** (`consumido.py`: 0/5).

**Pedido explicito al Estratega** (gatillo para consumir/sancionar):

    explicito:'sanciona el grano 2026-08-18-001 (re-verificacion precios Railway, colateral del
    dictamen 20260819): materializa la roca de railway.com/pricing a WORM e ingiere, o instruye
    descartarlo si el claim no amerita entrar al grafo'

Consumirlo es modo `procesar-granos` (red -> fix Norton truststore -> materializa_orden ->
ingesta). CodeEC puede ejecutarlo apenas el Estratega/Guardian lo sancione.

### B2. Poblar el testigo desde el navegador (cuando §2 se apruebe)

Si §2 se sanciona (D1 + A3), el Estratega es el unico que puede emitir `testigo_lectura.sha256`
(el hash del TEXTO normalizado que leyo en el DOM). **Nota operativa del dictamen:** el canal MCP
del navegador bloquea cadenas hex de 64 chars (las lee como base64) -> transportar segmentado
(`sha.match(/.{1,8}/g).join('-')`) y reensamblar del lado verificador.

---

## C. A CodeMCP -- lector `aec_search` (Railway, fuera de este repo)

### C1. §4 umbral + honestidad (NO bloqueante, MAXIMO costo/beneficio -- empezar por aqui)

Falla confirmada por el dictamen: una query de **ruido puro** (`recetas de cocina italiana`)
devolvio 3 hits a similitud 0.53 contra el grafo AEC. El lector **siempre** responde -> un indice
anti-re-investigacion que nunca dice "esto no lo has indagado" produce falsos positivos de
reconocimiento: la IA(t+n) asume terreno cubierto y no indaga. **Falla en la direccion exacta
contra la que se construyo, y en silencio.**

**Solicito:** corte en ~0.60; bajo el corte, devolver `count: 0` con
`veredicto: "sin indagacion previa registrada"`. Una linea; convierte el falso positivo en
respuesta util. Es el "empezar por aqui" del dictamen §6.

### C2. §4 hibrido BM25/ILIKE + reciprocal rank (mejora)

El rango util es de solo 0.16 (0.53 ruido -> 0.70 match perfecto) y la query generica gana a la
especifica: los embeddings premian la abstraccion y penalizan el termino unico (`"Railway"`,
`"Ancamide"`, `"AHEW"`) -- justo el patron de busqueda mas natural. Sumar BM25/ILIKE sobre el
termino literal y fusionar por reciprocal rank ataca esto directo.

### C3. §4 indexar tambien `necesidad.pregunta` (mejora, re-embeber corpus)

Hoy el embedding parece calcularse sobre `txt` de la afirmacion, pero el usuario pregunta "¿ya
investigue X?" -- que es una **necesidad**, no una afirmacion. Indexar `necesidad.pregunta` y
devolver el maximo de ambos alinea el indice con la pregunta real. Re-embeber a esta escala:
minutos.

### C4. §2 lado-lector del testigo (co-dependiente con D1)

Cuando exista `testigo_lectura` con `divergencia: true/false`, exponerlo en las vistas del lector
para que t+n vea cuando la roca en WORM y la lectura del Estratega no fueron los mismos bytes.

---

## D. A CodeCS -- custodio del schema aec-1 / concept-sediment

### D1. §2 sancionar la extension aditiva del schema (BLOQUEANTE del testigo)

Campo **opcional, por referencia, aditivo** (no rompe granos existentes):

    testigo_lectura:            # NUEVO, opcional
      sha256: "c905887e..."     # hash del TEXTO normalizado que leyo el Estratega
      len: 8633
      via: "dom-renderizado"    # | "servido" | "web-tool"
      ts_lectura: "2026-08-19T04:52:00"

**Fundamento (dictamen §2, medido):** sobre `railway.com/pricing`, misma IP/segundo, el HTML
*servido* (lo que un `curl` obtiene) y el *renderizado* (lo que el navegador lee) dieron **hashes
distintos**. C3 verifica que el hash resuelva en WORM, **no** que corresponda a lo leido: la via
queda formalmente completa y epistemicamente hueca. El testigo cierra la fisura sin cruzar la
membrana (**cruza un hash, no bytes**). Si difiere, no falla la ingesta: anota `divergencia:
true` (append-only) y t+n lo sabe.

**Solicito:** co-sancion con CodeMCP (C4) de este campo en aec-1, y confirmacion de la funcion de
normalizacion canonica del texto (debe ser IDENTICA en nube y local, o el hash no compara).

---

## E. Nuestra parte (CodeEC) -- lista para cuando desbloqueen

- **Lado LOCAL del testigo §2:** prototipable sin tocar schema todavia. Tras materializar, el
  actor local extrae el texto del snapshot, lo normaliza con la funcion **compartida**, lo hashea
  y compara contra `testigo_lectura.sha256`; si difiere, anota `divergencia: true`. Se implementa
  apenas D1 (CodeCS) + A3 (Guardian) esten sancionados.
- **Trampa registrada (ya documentada en `aec_verify.py` y en la skill):** el dia que ese hash
  entre al log, la funcion `normalizar()` se vuelve **load-bearing** (como `nucleo._canon`): hay
  que congelarla y compartirla nube<->local. Hoy es solo normalizador de display: inocuo.
- **§4:** es de CodeMCP (otro repo); CodeEC no toca el lector. Disponible para revisar el PR.

## F. Orden sugerido de ejecucion

1. **Ya:** CodeMCP C1 (umbral `aec_search`) -- no bloqueado, una linea, arregla el fallo que
   corrompe el proposito del indice.
2. **Guardian:** A1 (reconciliacion 06-29), A2 (§3), A3 (offset) -- desbloquean lo demas.
3. **Tras A3:** CodeCS D1 + CodeMCP C4 (co-sancion del testigo §2). Luego CodeEC implementa el
   lado local (E).
4. **Estratega:** B1 (sancion del grano 08-18) en cualquier momento; B2 tras §2.
5. **Merge** del PR #4 (lo nuestro, independiente de todo lo anterior).

---

*Emitido por CodeEC. Este reporte no toca el grafo ni el durable; es un ruteo de solicitudes.*
