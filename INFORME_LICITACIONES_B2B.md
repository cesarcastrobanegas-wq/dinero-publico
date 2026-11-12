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
unos pocos socios.

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
