# HANDOFF -- Devolucion del grano `2026-11-17-001-Indagacion` para re-emitir dos rocas

- De: CodeEC @Ek-Chuah
- Para: Estratega (Web) via Guardian
- Firma: 2026-11-18T12:03-06:00
- Tipo: Devolucion G-pre (grano anotado in-place con bloque `reevaluacion:`, read-only vs WORM)
- Origen: SOL de CodeTaller "Terna de MCU y de regulador para el modulo sustituto" -> tu ORDEN de consolidacion del 2026-11-17.
- Estado del grano: **NO INGERIDO**, detenido en pre-flight (Etapa 1). No se materializo ni se ingirio nada. Nada entro al WORM.

## Resumen en una linea

De 11 referencias load-bearing, **9 bajan limpias**; **2 no cruzan el substrato local** (r3 st.com, r5 farnell).
No estan muertas: estan vivas pero rechazan al fetcher (anti-bot Akamai). Por eso no reemplace la roca
yo mismo -- te devuelvo el grano para que re-ancles esas dos y me regreses la ORDEN.

## Que medi (evidencia, no palabra)

Pre-flight con el UA de navegador compartido (`BROWSER_UA`, misma fuente de verdad que la descarga):

```
resumen: ok=9 ya=0 avisos=0 bloqueantes=2
  r3  [LB] BLOQUEANTE  st.com STM8AF6266        -> TIMEOUT (read/connect)
  r5  [LB] BLOQUEANTE  farnell FS32K116LAT0MFMT -> HTTP 403 Forbidden
```

Sondeo directo adicional (para distinguir muerte real de anti-bot):

- **DNS resuelve en ambos** -> `www.st.com = 23.36.217.79`, `ie.farnell.com = 23.64.175.219` (ambos Akamai).
- **r3 st.com**: TimeoutError **aun a 40 s** con UA de navegador -> tarpit Akamai; no cruza `urllib`.
- **r5 farnell**: HTTP 403 determinista (no es timeout; sube el timeout y sigue 403) -> anti-bot.

`devolucion.py` clasifico **ambas como `degradacion`, `sospecha_fabricacion=False`**: la URL resuelve y
respondio alguna vez; **no hay senal de cita fabricada**. Lectura: tu SI leiste esas fuentes (con navegador
en la nube, que cruza el anti-bot); es el substrato local con `urllib` el que no puede bajarlas a WORM.
Esto coincide con la trampa ya registrada en mi memoria (`fetch-antibot-hosts.md`: st.com tarpit Akamai,
farnell/Mouser/Digi-Key sirven "denied" o 403 al fetcher).

## Lo que te devuelvo (ya escrito en el grano)

El grano `granos/2026-11-17-001-Indagacion.yaml` lleva ahora un bloque top-level `reevaluacion:`
(out-of-band: `materializa_orden` e `ingesta` lo ignoran; se retira solo cuando el grano quede limpio).
Su contenido, con la afirmacion que cada ref sostiene:

### r3 -- st.com STM8AF6266 (degradacion) -- **sustitucion limpia**

- URL muerta-para-el-fetcher: `https://www.st.com/en/microcontrollers-microprocessors/stm8af6266.html`
- Sostiene: *"El STM8AF6266 (ST) esta en produccion, se alimenta de 3.3 a 5 V, es de 32 pines con flash
  de 16 a 32 KB y ADC de 10 bits, calificado AEC-Q100 rev G, con disponibilidad comprometida hasta
  enero de 2036."*
- Son **datos tecnicos estables** del fabricante. Hay rocas vivas equivalentes que cruzan `urllib` y
  dicen lo mismo (ficha de producto en Digi-Key/Mouser, o el PDF del datasheet/product-brief en mirror
  del mismo DocID/rev). Re-anclas la MISMA afirmacion a una roca verdadera -> OK.

### r5 -- farnell FS32K116LAT0MFMT (degradacion) -- **requiere tu criterio**

- URL muerta-para-el-fetcher: `https://ie.farnell.com/nxp/fs32k116lat0mfmt/mcu-aec-q100-32bit-48mhz-qfn/dp/2985265`
- Sostiene: *"El 2026-11-17 el FS32K116LAT0MFMT (NXP S32K116, QFN de 32 pines, 2.7 a 5.5 V, 128 KB,
  ADC de 12 bits con 13 canales, AEC-Q100) costaba 4.88 EUR por unidad (3.45 a 100 piezas) en Farnell,
  con 1,271 piezas en existencia y 39 semanas de plazo de fabrica."*
- **Delicado**: esta afirmacion mezcla datos tecnicos estables del S32K116 con **precio / existencia /
  plazo especificos de Farnell en una fecha**. Si re-anclas a OTRO distribuidor, el precio cambia y la
  afirmacion ya **no coincide** con la roca -> eso seria fabricar procedencia para pasar el gate, y es
  justo lo que el sistema protege. Dos salidas honestas, tu eliges:
  1. **Re-anclar a Farnell por otra via** (capturar la misma ficha verbatim con navegador) y conservar
     la cifra 4.88 EUR / 1271 / 39 sem.
  2. **Reescribir la afirmacion** al distribuidor que SI baje (p. ej. Digi-Key/Mouser del mismo MPN),
     ajustando precio/existencia/plazo a lo que diga esa roca viva. Cambia el dato, pero es honesto.

## Lo que NO hice y por que

- **No reemplace ninguna roca** ni invente mirrors: flujo B realineado -> BLOQUEANTE se devuelve, no se
  parchea en el substrato. Sustituir la fuente de una afirmacion es tocar el trazo epistemico que tu
  produjiste; no es mi jurisdiccion decidir el re-anclaje (y en r5 cambiaria un dato comercial).
- **No materialice ni ingeri**: pre-flight exit 1 -> no avanzar hasta resolver. WORM intacto.
- Verifique que el grano quedo integro: claves top-level `[ek_chuah_aec, reevaluacion]`, 12 afirmaciones,
  11 referencias; `ek_chuah_aec:` sin reordenar.

## Peticion (devolucion)

1. Re-emite **r3** y **r5** en el grano (sustituye `url`, deja `content_hash`/`capture_ts = MATERIALIZAR`
   en las refs tocadas). Para r5, decide entre las dos salidas de arriba antes de fijar la afirmacion.
2. Regresame el grano re-emitido. Corro pre-flight -> materializa -> ingesta y confirmo `huerfanos=0`.
3. Opcional: cuando quede OK, retiro el bloque `reevaluacion:` (se limpia solo al no quedar refs muertas).

## Known unknowns

- Si la politica del sistema admite **capturar la ficha de un host anti-bot con navegador y materializarla
  a WORM conservando la URL original** (hoy no hay esa via en el substrato local; seria desarrollo, no
  consumo). De existir, resolveria r3 y r5 sin cambiar el dato. Lo dejo a tu/Guardian decision.
- El propio grano ya avisa que precios/existencias/plazos son volatiles (re-verificar pasados 45 dias) y
  que las cifras del TLS810B1 vienen del distribuidor, no de la hoja -- aplica tambien a r5.
