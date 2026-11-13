# Licitaciones para empresas: fuentes, TED e informe mensual (12-11-2026)

Para decidir antes del lanzamiento B2B. Nada de esto está programado: es la base para que César decida. Las cifras
son medidas del 12-11-2026, salvo que se diga otra cosa.

## 1. Qué fuentes de licitaciones abiertas entran hoy

**Solo el feed 643 de PLACE** (`sindicacion_643`, «perfiles de contratante alojados en la Plataforma»). Es el mismo
del que salen los contratos formales del Índice. El hilo `licitaciones` de `app.py` lee sus ZIP mensuales y su Atom
en vivo. **No entra la agregación de plataformas autonómicas** (`sindicacion_1044`, «PlataformasAgregadasSinMenores»),
que es donde publican los órganos que tienen plataforma propia (Generalitat de Catalunya y sus entes, Comunidad de
Madrid, Euskadi, Junta de Andalucía, Xunta de Galicia, Navarra, La Rioja…). Tampoco entra TED.

### Licitaciones abiertas en la web por comunidad (feed 643, /convocatorias, 12-11-2026 hacia las 18:30)

| Comunidad | Abiertas | | Comunidad | Abiertas |
|---|---:|---|---|---:|
| Andalucía | 1.079 | | Canarias | 365 |
| Comunidad de Madrid | 868 | | Aragón | 270 |
| Comunitat Valenciana | 665 | | Castilla-La Mancha | 285 |
| Castilla y León | 434 | | Extremadura | 254 |
| Galicia | 241 | | Illes Balears | 227 |
| Región de Murcia | 222 | | Principado de Asturias | 170 |
| Cantabria | 139 | | **Cataluña** | **115** |
| La Rioja | 65 | | Ceuta / Melilla | 42 / 37 |
| **País Vasco** | **32** | | **Navarra** | **11** |

Cataluña (8 millones de habitantes) tiene la mitad que Murcia (1,6 millones); País Vasco y Navarra, casi nada. Es
el hueco de las plataformas propias.

### Lo que nos falta: medido en el feed 1044

Medido el 12-11-2026, con el Atom en vivo del feed 1044 recorrido 45 días hacia atrás (81 páginas, 398 MB, 23.576
entradas distintas), quedándome con la última versión de cada una:
- **2.281 licitaciones abiertas** (en estado PUB y con plazo sin vencer a las 19:10) que hoy no salen en la web;
- en la web había **5.810** abiertas a la misma hora.

**Nos falta en torno al 28 %** de las licitaciones abiertas de España que publican PLACSP y las plataformas
agregadas (2.281 de 8.091). Es una cota por arriba: si algún órgano publica en las dos, contaría dos veces. Falta
cruzar por expediente.

| Comunidad (feed 1044) | Abiertas | En la web hoy (643) |
|---|---:|---:|
| Cataluña | 1.243 | 115 |
| País Vasco | 469 | 32 |
| Comunidad de Madrid | 185 | 868 |
| Andalucía | 168 | 1.079 |
| Navarra | 98 | 11 |
| Galicia | 83 | 241 |
| La Rioja | 27 | 65 |
| Sin lugar en el anuncio | 8 | — |

- **Procedimiento**: 1.369 abiertos, 565 abiertos simplificados, 301 «otros» y el resto, sueltos.
- **SARA**: 682 armonizados y 1.599 no.
- **Quién más publica**: Osakidetza, Infraestructures de la Generalitat, el Departament d'Educació, el Servicio
  Andaluz de Salud, FGC, el Hospital La Paz, TMB, la CCMA, el SERGAS y el Ajuntament de Barcelona.

Con el 1044, Cataluña pasaría de 115 a unas 1.350 y País Vasco de 32 a unas 500.

### Qué costaría añadir el feed 1044

- **Lectura**: el formato es el mismo (CODICE). `licitaciones_place.analizar_entrada` lo lee sin cambios: es lo que
  ha usado esta medición.
- **Descarga**: el ZIP de octubre de 2026 pesa unos 15 MB (según su ETag; PLACE no deja pedir solo las cabeceras),
  frente a los ~290 MB de un mes del 643. El Atom en vivo va a unas 190 entradas y 2,2 MB por página, unas 2
  páginas al día. En ancho de banda y memoria de Render es poco.
- **Trabajo**: 1-2 días. Una segunda fuente en el hilo `licitaciones` (ZIP mensual + Atom en vivo, como el 643),
  una columna `fuente` en la tabla y el texto «según PLACSP» de /convocatorias, del correo y del PDF, que pasaría a
  «según PLACSP y las plataformas autonómicas agregadas en ella».
- **Riesgos**:
  1. Los enlaces de cada anuncio llevan a la plataforma autonómica, no a PLACSP. Los pliegos, la herramienta de
     presentación y el alta son los de esa plataforma. La guía ya lo dice («el alta y la herramienta son las de esa
     plataforma»).
  2. **Duplicados**: algunos órganos publican en las dos. Habría que quitarlos por expediente + NIF del órgano antes
     de contar.
  3. **Calidad**: falta medir cuántos traen NUTS, plazo con hora, requisitos y pliegos. En el 643, 30 de 31 traen
     PCAP y PPT.
  4. **Tipo de órgano**: en la medición, el lector clasificó las 2.281 como ámbito «otros». No reconoce cómo
     codifican estas plataformas el tipo de administración, y el filtro «Cualquier organismo» de /convocatorias
     las dejaría todas juntas. Hay que mapear sus códigos.
  5. **Asignación a municipio**: el filtro por ayuntamiento de /convocatorias usa el nombre del órgano. Con
     Ajuntament/Udala/Concello ya funciona, pero hay que comprobarlo.
- **Lo que no cubre ni el 1044**: lo que ninguna plataforma agrega a PLACSP. Por ejemplo, los contratos menores (el
  feed se llama «SinMenores»), que no son licitaciones abiertas.

## 2. Licitaciones europeas (TED): propuesta

**Qué es**: TED (Tenders Electronic Daily) es el suplemento del Diario Oficial de la UE con los anuncios de
contratos por encima de los umbrales europeos de toda la UE y el EEE.

**API**: búsqueda `POST https://api.ted.europa.eu/v3/notices/search`.
- No pide clave ni registro para buscar: la documentación oficial dice «The Search API does not require a key», y
  lo he comprobado con consultas de prueba.
- Consulta en el lenguaje «expert search» de TED.
- Como mucho 250 avisos por página (comprobado: con 251 responde «exceeds maximum allowed value (250)»). Para más,
  se itera con `iterationNextToken`.

**Filtros que sirven** (nombres de campo de la documentación de TED, probados):
- **CPV**: `classification-cpv` (admite comodín: `classification-cpv=90*`).
- **País**: `buyer-country` (código ISO de 3 letras: `ESP`) o `place-of-performance`.
- **Tipo de anuncio**: `notice-type` (`cn-standard`, `cn-social`… = anuncios de licitación; `can-*` = adjudicaciones).
- **Fechas**: `publication-date` y `deadline-receipt-tender-date-lot` (plazo de cada lote).

**Qué da cada aviso**:
- título en todas las lenguas de la UE (también en castellano), comprador, país, valor estimado, CPV, plazo por
  lote y enlace a los documentos de cada lote (`document-url-lot`, que lleva a la plataforma del comprador);
- enlace al aviso en HTML o PDF: `https://ted.europa.eu/es/notice/<número>/pdf`.

**Volumen** (anuncios de licitación, 12-10 a 11-11-2026, medido con la API):
- **2.538** de compradores españoles. Casi todos son los mismos contratos SARA que ya publica PLACSP: para España, TED
  añade poco.
- **40.520** del resto de países de la UE y el EEE: eso es lo nuevo.

**Propuesta**: un apartado «Licitaciones en Europa» solo para socios, no en /convocatorias. Funcionaría así:
- cada socio elige CPV y países;
- se consulta TED una vez al día con su filtro (con los 250 por página bastan pocas peticiones);
- el aviso sale en el correo semanal con su enlace a TED y al documento, sin lista de comprobación, porque cada país
  tiene sus reglas.

**Coste**:
- la API es gratuita (no pone precio en ninguna parte) y sin registro;
- programar: 2-3 días;
- mantener: poco (API versionada; la v2 sigue «hasta que exista la v4»).

**Riesgos**:
1. **Interés real**: una pyme española rara vez se presenta en otro país. Antes de programar, preguntaría a 5-10
   socios si lo usarían.
2. **Idioma**: los pliegos van en la lengua del comprador.
3. **Límites de uso**: la web de TED publica límites de «uso justo» (700 peticiones por minuto, 3 descargas
   simultáneas de paquetes). Con una consulta diaria por socio no hay problema.
4. **Datos personales**: algunos avisos llevan nombres de personas de contacto. No los mostraríamos.
5. **Licencia**: los avisos «can be freely reused, for commercial or non-commercial purposes» (aviso legal de TED,
   Decisión 2011/833/UE). No piden atribución expresa para los datos; la daría igualmente.

**Recomendación**: esperar al feed 1044 (más valor para las empresas españolas y menos trabajo) y probar TED con
unos pocos socios. Para las licitaciones **españolas**, TED no compensa como fuente directa: ver el apartado 4.

## 3. Informe mensual: propuesta

**A quién**:
- **socios de pago** (empresas del filtro): su sector y sus provincias;
- **Cámara de Comercio / asociaciones**: su región, como herramienta para sus asociados;
- más adelante, si César quiere, una versión pública resumida (sin nombres de empresas) para prensa.

**Qué llevaría** (todo con datos que ya tenemos):

1. **Resumen del mes**: licitaciones publicadas y su importe, por sector (división CPV) y provincia, comparado con
   el mes anterior y con el mismo mes del año anterior (tabla `licitaciones` y ZIP de PLACE).
2. **Las que siguen abiertas** y encajan con el perfil (el motor del filtro), con su lista de comprobación.
3. **Quién gana**: adjudicatarios más frecuentes de su sector y provincia en los últimos 12 meses, con número de
   contratos e importe (contratos formales del Índice). Solo empresas; las personas físicas, sin nombre, como en el
   resto de la web.
4. **Plazos**: días medios entre publicación y cierre por tipo de procedimiento. Ojo: la tabla no guarda la fecha
   de publicación; habría que usar `visto` (la primera vez que la leímos), que se queda a pocas horas en el Atom en
   vivo pero no vale para lo leído de ZIP antiguos. Se puede añadir la fecha de publicación (`IssueDate`) al lector
   antes de lanzarlo.
5. **Competencia**: número medio de ofertas por contrato adjudicado en su sector (`ReceivedTenderQuantity` de
   CODICE). Hoy no se guarda: habría que añadirlo al lector.
6. **Bajas medias**: diferencia media entre presupuesto e importe adjudicado. Solo con los contratos que traen las
   dos cifras, y dejándolo dicho.

**Formato**: el mismo PDF en blanco y negro del filtro (`filtro_licitaciones_informe.py`), de 4 a 6 páginas, y un
enlace a la web.

**Coste**: 3-4 días con los puntos 1-3. Los puntos 4 y 5 necesitan ampliar el lector antes (1 día más) y unos meses
de datos acumulados.

**Riesgos**:
- comparar meses con datos que aún se están completando (los ZIP del mes en curso cambian a diario): el informe
  saldría del mes cerrado, a partir del día 3;
- y el aviso de siempre: los datos son los de la fuente y pueden tener errores.

## 4. Cobertura real, medida con TED (12-11-2026, noche)

**Cómo se ha medido**
- **TED**: con su API, los anuncios de licitación (`cn-standard`, `cn-social`, `cn-desg`) de compradores españoles
  (`buyer-country=ESP`) publicados del 13-10 al 12-11-2026. Son **2.542**; **2.104** seguían abiertos desde el
  13-11. Solo se comparan los abiertos, porque de lo nuestro solo vemos lo abierto.
- **Lo nuestro**:
  - **643**: las 5.808 abiertas que enseñaba /convocatorias el 12-11 a las 20:00;
  - **1044**: 2.279 abiertas, medidas en su Atom en vivo esa misma noche.
- **Cruce**, por este orden:
  1. mismo anuncio de PLACE: TED trae el enlace `detalle_licitacion&idEvl=…`, el mismo que guardamos;
  2. mismo expediente (el 643 no lo enseña en la web, el 1044 sí);
  3. título parecido (≥ 60 % de palabras en común) y mismo día de cierre;
  4. mismo órgano y mismo día de cierre. Hace falta porque TED da a menudo el título traducido al castellano y sin
     expediente, mientras que la plataforma catalana lo da en catalán.

**Resultado (2.104 abiertas en TED)**

| | Anuncios | % |
|---|---:|---:|
| Los tenemos por el 643 (PLACE) | 1.281 | 60,9 % |
| Los tenemos por el 1044 (plataformas autonómicas) | 657 | 31,2 % |
| **Los tenemos con 643 + 1044** | **1.938** | **92,1 %** |
| No los tendríamos | 166 | 7,9 % |

**De los 166 que faltan**
- **60 están en PLACE según TED, pero no salían en /convocatorias.** Investigado el 13-11 (apartado 4 bis): **no
  es un fallo de lectura**.
  - 47 se publicaron en la tanda diaria de PLACE de la tarde del 12-11 y nuestro ciclo de 3 h aún no la había leído
    cuando se bajó la web. El 13-11 ya salen.
  - Las otras 13 están cerradas en PLACE, aunque TED las siga dando por abiertas.
  - La del ejemplo de la Confederación Hidrográfica del Duero (452-A.210.00.03/2026) está **anulada** en PLACE
    desde el 10-11: no era «abierta hasta el 24-11», como decía la primera versión de este informe.
- **12 son de instituciones de la UE con sede en España** (EUIPO en Alicante, Centro de Satélites en Torrejón,
  F4E en Barcelona, Comisión…). No son sector público español y publican en su propia plataforma
  (webgate.ec.europa.eu); solo están en TED.
- **Unos 7 son de entidades que publican fuera de PLACE y de su agregación**, comprobado en su perfil:

  | Entidad | Tipo | Anuncios | Dónde publica |
  |---|---|---:|---|
  | Aigües de Barcelona | empresa mixta con derechos especiales | 2 | portal propio |
  | Cámara de Comercio de España | corporación de derecho público | 2 | camara.es |
  | Marfina Bus / Moventis | privada con derechos especiales | 1 | moventis.es |
  | TMESA (autobuses municipales de Terrassa) | empresa municipal | 1 | tmesa.com |
  | Ente de Servicios Tributarios de Asturias | organismo público | 1 | presenta por licita.asturias.es |

  **Ninguno tiene RSS, API ni datos abiertos de contratación**: son páginas HTML (TMESA solo tiene el RSS
  genérico de su web). Añadirlos uno a uno sería un raspado de HTML por portal, para 1 o 2 anuncios al mes cada
  uno. No compensa.
- **Los otros ~87 son, casi seguro, de plataformas que ya están en el 1044**: catalana 36, Navarra 13, Andalucía 15,
  Galicia 8, Euskadi 3… En la mayoría el órgano sí aparece en el 1044 con otras licitaciones, y en varios el
  expediente del 1044 va dentro del título de TED (p. ej. Mercados de Abastecimientos de Barcelona,
  «(2026OB0001)»). Lo más probable es la misma licitación con otra fecha de cierre (prórroga) u otro título. TERSA,
  el Ajuntament de Barcelona y la Diputació tienen su perfil en contractaciopublica.cat, que está en el 1044. Es
  una cota por arriba de lo que falta, no una fuente nueva.

**Cobertura del sector público español con 643 + 1044**
Se quitan las 12 de instituciones de la UE y las 13 que PLACE ya da por cerradas: quedan **2.079 anuncios**.

| | Cobertura |
|---|---:|
| Medida la noche del 12-11 (cruce estricto) | 93,2 % (1.938) |
| **Corregida el 13-11** (las 47 de la tanda del 12-11 ya salen) | **95,5 %** (1.985) |
| Si los ~87 de plataformas del 1044 son las mismas con otra fecha o título | **hasta 99,7 %** (2.072) |
| Fuera de PLACE y de su agregación, comprobado | **~0,3 %** (unos 7 al mes) |

**Con TED como fuente añadida**
- Cubriría también esos ~7 al mes y las 12 de instituciones de la UE: el 100 % de lo que publica TED.
- Pero **TED solo tiene lo que supera los umbrales europeos**. De lo que queda por debajo y fuera de PLACE y del
  1044 no hay forma de medir cuánto falta con esta fuente, aunque por lo visto arriba son entidades pequeñas y
  pocas.

**Propuesta**
1. **El «hueco de PLACE» no era tal** (apartado 4 bis): era el retraso entre la tanda diaria de PLACE y nuestro
   ciclo. Arreglado en una rama encima del #49: un ciclo más a las 21:00.
2. **No añadir TED como fuente directa para las españolas.** Ganaría unas 7 licitaciones españolas al mes (el
   0,3 %), a cambio de cruzar cada anuncio con PLACE y el 1044. Ese cruce, como se ve arriba, solo es exacto con
   PLACE (por `idEvl`); con el 1044 depende de órgano y fecha, y se equivocaría a veces en los dos sentidos.
3. **Las 12 de instituciones de la UE con sede en España**, si se quieren, en el apartado «Licitaciones en Europa»
   del punto 2 (que ya sería TED), no mezcladas con las españolas.
4. **Si se añadiera TED igualmente** para las españolas, solo las que no lleven enlace a contrataciondelestado.es
   ni a las plataformas del 1044, y quitando repetidos por órgano + día de cierre. Coste: 1-2 días sobre lo del
   punto 2.

Los requisitos (solvencia, clasificación) del 1044 tampoco se pueden sacar de TED de forma fiable. TED los trae a
veces en los armonizados (`selection-criterion-lot`), pero casi siempre como «ver el pliego» o solo el tipo
(«volumen de negocios anual»).

## 4 bis. El «hueco de lectura de PLACE», investigado (13-11-2026)

**Cómo**
- Se han seguido las 60 en el feed 643 por su `idEvl` (el enlace que trae TED): ZIP de octubre y de noviembre y
  Atom en vivo.
- Después, a partir de las 12:30 UTC, se ha buscado cada una por su expediente en /convocatorias. Solo páginas
  públicas, sin tocar la base.

**Qué eran las 60**

| | Anuncios TED | Qué pasa en PLACE | ¿Sale hoy en /convocatorias? |
|---|---:|---|---|
| Publicadas el 12-11 (09:21-13:19) | 46 | en la tanda diaria del 12-11 (20:18) | **sí, las 46** |
| Ayuntamiento de Siero, póliza RC | 1 | abierta; TED sin `idEvl` y con otra fecha: el cruce no la casó | **sí** |
| Resueltas (RES) | 6 | p. ej. transporte sanitario 19/20/21-26 AA, SU13017/2026 | no (bien) |
| Anuladas (ANUL o borrada «ANULADA») | 6 | CH del Duero (3 anuncios TED), Hospital de Medina del Campo (2), un ayuntamiento (76/2026) | no (bien) |
| En evaluación (EV) | 1 | Diputación, 2026/D22200/006-302/00007 (PLACE cerró el 03-11) | no (bien) |

En total, 47 abiertas que ya salen y 13 cerradas. **Ninguna se perdía en la lectura.**

**La causa: el horario de PLACE**
- PLACE no va publicando el Atom del 643 a lo largo del día. Lo publica **una vez al día, hacia las 20:05-20:45
  hora peninsular**, con todo lo del día:
  - el `Last-Modified` del Atom era 12-11 19:18 GMT;
  - los .atom de los ZIP se llaman `_AAAAMMDD_2003` a `_2046`;
  - no hay tandas en fin de semana.
- Nuestro hilo lee cada 3 h desde el arranque. La tanda podía tardar hasta 3 h en verse, y la web se bajó para el
  cruce antes de ese ciclo.
- TED, en cambio, publicó esos anuncios el mismo 12-11 durante el día.

**Descartado**
- **Corte del Atom**: el lector para en la primera página con algo ya visto, aunque las tandas traen al final
  versiones con fecha de días anteriores. Simulado sobre todas las tandas de octubre y noviembre (86.808
  entradas): **no se pierde ninguna**, porque la página donde para se guarda entera.
- **Tope de páginas** (`LIC_MAX_PAGINAS_ATOM` = 40): las tandas tienen 3-7 páginas.
- **Plazos, lotes y versiones posteriores**: el plazo, los lotes y las versiones posteriores se leen bien (el
  analizador da PUB y la fecha correcta en las 47).

**Arreglo** (rama `wip/licitaciones-hora-place`, encima del #49)
- El hilo se despierta también a las 21:00 hora peninsular, justo después de la tanda, además de cada 3 h.
- Lo del día sale en /convocatorias hacia las 21:00, no hasta 3 h después.
- Fuera del refresco nocturno y sin descargas nuevas: es una lectura más del Atom (~6 páginas).
- Pruebas: la espera hasta el siguiente ciclo, el caso del 12-11, y que una tanda con versiones antiguas al final
  se lee entera sin pedir la página siguiente.

**TED como medida**
- Para medir cobertura hay que comparar con TED **a la mañana siguiente**, no la misma noche.
- Además, hay que quitar lo que PLACE ya da por cerrado: TED no publica las anulaciones ni las resoluciones hasta
  mucho después.
