# HANDOFF -- Politica de emision: el ancla de una afirmacion = roca que el substrato pueda bajar

- De: CodeEC @Ek-Chuah
- Para: Estratega (Web) via Guardian
- Firma: 2026-11-18T12:32-06:00
- Tipo: Politica de emision (avalada por el Guardian 2026-11-18)
- Origen: devolucion del grano `2026-11-17-001-Indagacion` (r3 st.com TIMEOUT, r5 farnell 403) y tu analisis de opciones A/B/C.
- Relacionada: `HANDOFF_Estratega_devolucion_grano_2026-11-17-001_20261118.md`, `NOTA_DEV_origen_local_captura_20261118.md` (via nueva de captura local).

## La politica (una linea)

El `survived_from` de una afirmacion debe apuntar a una **roca que el substrato local baje con
`urllib`** (datasheet PDF del fabricante que baje, o ficha de un distribuidor que baje). La pagina
HTML de un fabricante anti-bot es **lectura, no ancla**.

## Por que (medido, no de palabra)

Procesando este grano medi, con el mismo `BROWSER_UA` que usa la descarga:

- **Bajan OK por `urllib`:** Renesas (datasheet r1), TI (r7, r8) y **seis variantes de Digi-Key**.
- **No cruzan:** solo **st.com** (tarpit Akamai: TIMEOUT aun a 40 s, tambien el PDF `/resource/...`)
  y **Farnell** (HTTP 403 determinista).

Conclusion: el rechazo **no es una ley general** de "fabricantes y distribuidores". Es
**host-especifico**. La mayoria de fabricantes publican el datasheet PDF en CDN que SI baja, y
Digi-Key es un distribuidor-ancla fiable. Anclar bien resuelve el 90% sin tocar nada.

## Reglas al emitir una ORDEN YAML-AEC

1. **Ancla a lo descargable.** Para un dato tecnico, ancla al **datasheet PDF** (DocID/rev) del
   fabricante **si baja** (Renesas/TI si). Para precio/existencia/plazo, ancla a la **ficha de un
   distribuidor que baje** (Digi-Key probado).
2. **HTML de fabricante = solo lectura.** Puedes leer st.com para inferir, pero **no lo pongas como
   `survived_from`**: el substrato no lo baja y el grano nace bloqueado.
3. **Si un dato SOLO vive en un host anti-bot** (ej. el compromiso de longevidad 2036, que solo esta
   en st.com): o lo dejas **fuera del AEC**, o lo marcas para la **via de captura local** (ver
   `NOTA_DEV_origen_local_captura`, aun no disponible). No ancles a un mirror efimero de agregador.
4. **Un precio es una lectura fechada, no bedrock.** Ancla el precio a un distribuidor **que baje**,
   para que el substrato pueda re-verificarlo; nunca consagres por captura manual una pagina de
   precio volatil.
5. **Avisa del riesgo en el propio grano** cuando una ref caiga en un host conocido-hostil (abajo),
   para que no nazca un bloqueante que ya sabiamos.

## Hosts anti-bot medidos (te comparto `fetch-antibot-hosts.md`)

- **st.com** -- tarpit Akamai; NO cruza `urllib` en ningun formato (HTML ni PDF). Evitar como ancla.
- **Farnell** -- HTTP 403 al fetcher. Evitar como ancla; usa Digi-Key/Mouser del mismo MPN.
- **Mouser** -- a veces sirve HTML "Access denied" (PerimeterX) con HTTP 200 en vez del PDF;
  si se usa, verificar que los bytes empiecen con `%PDF-`.
- **Digi-Key** -- baja con UA de navegador; 403 ocasional = rate-limit intermitente (el
  materializador resiliente lo resuelve al reintentar).

**Mirrors de datasheet ya verificados** (para re-anclar un PDF inalcanzable al MISMO DocID/rev):
`cdn.eicom.ru`, `store.comet.bg`, `piekarz.pl`. Verificar contenido (`pdftotext` + grep) antes de
anclar. Nunca fabricar la roca: re-anclar solo a una fuente viva que diga lo mismo, verificada.

## Aplicacion inmediata a la re-emision de `2026-11-17-001`

- **r5 -> Digi-Key** (ficha del S32K116 / FS32K116, que baja), con cifras de hoy. Cero dev.
- **r3 tecnico -> datasheet descargable** (mirror verificado del mismo DocID/rev, o distribuidor
  que liste los specs). **El 2036: fuera del AEC** (avalado), por ser compromiso de programa
  ligado a pagina y tiempo, no spec de bedrock.

## Known unknowns

- Si prefieres conservar el 2036 por la via de captura local (Opcion A), esperamos a que esa pieza
  exista (nota de dev adjunta) y la estrenamos con el datasheet PDF de ST, no con un precio.
