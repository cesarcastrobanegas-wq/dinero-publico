# Limitaciones de cobertura conocidas — Dinero Público

Documento de referencia, no exhaustivo pero sí verificado contra el código y los
datos reales (`backend/cache.db`) a fecha 2026-08-18. Cada punto indica si es un
límite real de la fuente de datos (no arreglable sin una fuente nueva), una
decisión deliberada de alcance, o algo pendiente de hacer.

## Alcance temporal: solo los últimos 5 años (decisión de César, 2026-09-25)

- **Regla**: solo interesan contratos (menores y formales) de los últimos cinco años; a 2026-09-25 eso es
  desde el **2021-09-01**. Para menores vive en `MENORES_DESDE_FECHA` (`backend/app.py`) y en `DESDE_FECHA` del
  script manual; el generador del backfill gallego de PLACE tiene su suelo en `MES_MINIMO = "202109"`.
  Con el paso del tiempo hay que subir esas constantes a mano.
- **Menores — aplicado (2026-09-26)**: `_guardar_contratos_menors_locales` (punto único de escritura) descarta lo
  anterior al corte, y el arranque **archiva, no borra** (`_archivar_menores_fuera_de_ventana`) las filas ya
  cargadas en la tabla `contratos_menors_archivo`. Snapshot de las 9.650 filas del 2026-09-26 (Galicia 3.784,
  Cataluña RPC 5.828, Lorquí 37, Torre Pacheco 1; 27,2 M€) en
  `backend/historico/contratos_menores_anteriores_2021-09.json.gz`. Las filas sin fecha (Fuente Álamo, 801) se conservan.
- **Formales — decidido y aplicado (2026-09-27)**: la auditoría del 2026-09-26 (PSCP 6.570/74.731 filas fuera de
  ventana, 8,8 %; Euskadi 7.226/20.093, 36 %; Navarra sin medir) llevó a la misma decisión que menores: recortar
  a 5 años, archivando (nunca borrando) lo que queda fuera. Ver el detalle completo, qué cambió en el código y
  cómo se limpió lo que ya estaba guardado en la sección **"Alcance de 5 años en contratos formales de PSCP/
  Euskadi/Navarra"**, más abajo en este mismo documento (nota: en un resumen anterior esta misma noche este punto
  se dejó escrito como "pendiente de decisión" a la vez que ya se describía como aplicado más abajo —
  contradicción señalada por César el 2026-09-27 y corregida aquí).

## Contratos menores

- **Cataluña (Girona/Lleida/Barcelona/Tarragona)**: se consulta el dataset RPC
  de la Generalitat (`hb6v-jcbf`) para los 987 municipios reales, pero:
  - **Sin NIF y sin URL por expediente** — la fuente no publica ninguno de
    los dos campos.
  - **53/221 Girona, 79/231 Lleida, 45/309 Barcelona, 21/181 Tarragona**
    (238/987 en total, ~24%) devuelven 0 filas. No se puede distinguir si es
    porque de verdad no hubo contratos menores o porque ese ayuntamiento no
    los reporta al registro de la Generalitat — los contratos menores no
    tienen obligación legal de publicación centralizada.
- **Murcia** (actualizado 2026-09-24): 9 de los 45 municipios tienen una fuente propia
  (**Lorca, Lorquí, Mula, Molina de Segura, Fuente Álamo, Cartagena, Murcia capital,
  San Pedro del Pinatar, Torre Pacheco**) — los otros 36 no tienen ninguna fuente
  conectada, no es que "salga 0", es que nunca se consulta nada para ellos. No existe
  un dataset regional único como el RPC catalán para Murcia. Descartados tras verificar
  (2026-09-24): Caravaca de la Cruz (su sección de menores está vacía), San Javier (se
  detiene en 2021 y son decretos/facturas, no un listado), Los Alcázares (solo publica
  los financiados por Agenda Urbana y PRTR, no todos), Alhama de Murcia (portal de
  transparencia en mantenimiento, reintentar), Totana (archivo con una sola entrada de 2015 sin
  adjudicatario ni importe; fichas de 2019 en fase de licitación) y Yecla (su portal Governalia
  está archivado/suspendido, HTTP 410; las páginas antiguas de la JGL dan 404).
  - **Cartagena** (2026-09-24, sin desplegar al escribir esto): el portal propio solo devuelve
    2026; 2022-2025 se recuperan de su portal Governalia (`app.governalia.es`, idP=47226), un
    espejo de lo que Cartagena comunica a PLACE (13.560 filas, fuente `cartagena-governalia`).
    No es la misma lista que el portal propio (se solapan ~62 % en 2026), por eso solo se usa
    hasta 2025. Importes: portal propio CON IVA, Governalia SIN IVA. Arrastra errores de origen:
    992 filas con adjudicado 0 (se dejan a 0) y un "menor" de 6.000.000 € (id 39918, feria de
    Málaga 2025, mismo importe en PLACE; se muestra tal cual con una nota visible en su fila, `_NOTAS_CONTRATO_MENOR` en app.py, lista cerrada revisada a mano, no una regla por importe).
  - Mula y Molina de Segura se cargan **a mano** (`actualizar_contratos_menores_murcia_manual.py`,
    necesita odfpy/openpyxl) — no están en el cron diario. Si nadie relanza
    el script, esos datos se quedan congelados sin ningún aviso.
- **Estado (2026-08-18): DONE.** Se añadió un aviso visible (`.cm-aviso` en
  `app.py`, dentro de `render_html`) en la ficha de cualquier municipio real
  (no pseudo-municipio) sin ninguna fila en `contratos_menors_locales`,
  explicando que los contratos menores no siempre tienen obligación de
  publicación centralizada y que cualquier vecino o concejal puede
  solicitarlos formalmente al ayuntamiento por vía de acceso a la información
  pública (enlace a la Ley 19/2013 + búsqueda del portal de transparencia del
  ayuntamiento). Verificado con Playwright en desktop y móvil (390px), sin
  overflow, y confirmado que NO aparece en pseudo-municipios (Región de
  Murcia, AGE, UMU, Provincia de X) ni en municipios que sí tienen datos
  (Lorca).

## Contratos menores — País Vasco vía API de Euskadi (2026-09-27)

- **Descubrimiento**: la misma API REST de Euskadi que ya usábamos para contratos formales
  (`api.euskadi.eus/procurements/contracts`, `contracting-authority-id` numérico sin ambigüedad) acepta
  `minor-contract=true` en vez de `false` y devuelve los contratos MENORES de cada ayuntamiento, con la MISMA
  fecha real de adjudicación (`awardDate`) que los formales. Cubre los 251 municipios ya mapeados en
  `MUNICIPIOS_PAIS_VASCO_EUSKADI_ID` — el 100 % de los municipios vascos que el proyecto ya tiene conectados —
  de una sola vez, sin necesitar ayuntamiento a ayuntamiento.
- **Generador**: `backend/actualizar_contratos_menores_euskadi.py` (cadencia manual/periódica, mismo patrón que
  `actualizar_contratos_menores_murcia_manual.py`), fichero `backend/contratos_menores_euskadi.json.gz`, cargador
  `_cargar_contratos_menores_euskadi` en `app.py` (arranque, upsert idempotente sobre `contratos_menors_locales`).
  Alcance de 5 años aplicado en el propio generador (se descarta lo anterior a `MENORES_DESDE_FECHA`, igual que en
  el resto de fuentes de menores). Sanity check de importe (más de ~50.000 € = por encima del techo legal de un
  contrato menor de obras con margen de IVA) impreso al final del generador para revisión manual, sin excluir nada
  automáticamente (mismo criterio que el resto del proyecto: nunca se adivina, se anota).
- **Cobertura final (2026-09-27): 155.708 contratos menores en los 251 municipios** (113 sin ninguno). Volumen muy
  alto en los municipios grandes de Gipuzkoa/Bizkaia (Irun 31.969, Errenteria 21.085, Hernani 24.869, Tolosa
  15.926, Eibar 24.126) — puede ser real (compra muy fragmentada) o reflejar cómo la propia API cuenta/agrupa
  entradas; sin confirmar, anotado para revisar con calma.
- **Cobertura PARCIAL conocida en 7 municipios grandes** (el generador tenía un tope de seguridad de 200
  páginas/10.000 contratos que se quedó corto para estos, ya corregido en el script a 700 páginas/15 min por
  municipio para el futuro, pero no relanzado entero esta noche por el tiempo que costaría — varias horas):
  **Eibar** (8.851 de 24.126 reales, 37 %), **Elgoibar** (7.435 de 10.537, 71 %), **Errenteria** (10.000 de
  21.085, 47 %), **Getxo** (7.280 de 12.623, 58 %), **Hernani** (10.000 de 24.869, 40 %), **Irun** (10.000 de
  31.969, 31 %), **Tolosa** (10.000 de 15.926, 63 %). Para completarlos: relanzar
  `python actualizar_contratos_menores_euskadi.py Eibar Elgoibar Errenteria Getxo Hernani Irun Tolosa` (con el
  script ya corregido) — cada uno puede tardar hasta 15 minutos por el volumen.
- **Aviso automático de importes sospechosos**: 52 de las 155.708 filas superan los 100.000 € (hasta 8.447.000 €
  en Loiu por "retirada de columnas de antiguo alumbrado", 4.839.353 € en Deba por instalar césped artificial en
  una pista de tenis...) — mismo tipo de error de origen que el caso Prismaglobal/Vitoria-Gasteiz de noches
  anteriores, pero sin URL por contrato para verificarlo uno a uno y con demasiado volumen para curarlos a mano
  como esos casos. `app.py` muestra un aviso automático (`EUSKADI_MENOR_IMPORTE_SOSPECHOSO = 100.000`) en
  cualquier fila de esta fuente por encima de ese umbral, en vez de ocultarla o inventar una cifra corregida.
  Portugalete concentra más de una decena de los 52 casos — posible problema específico de esa fuente/municipio,
  sin confirmar. 4 filas (de 155.708) tienen fecha de adjudicación futura (hasta 2029) — mismo tipo de dato
  imposible ya documentado para los formales de Euskadi arriba; se dejan tal cual, sin excluir.

## Contratos menores — mapeo de agregadores regionales, resto de España (2026-09-27)

Comprobado esta noche (no solo buscado: consulta real a la API/CKAN de cada portal) si existe, para otras
comunidades, un agregador regional equivalente al RPC catalán (que si cubre ayuntamientos) o al CKAN de la Región
de Murcia:

- **Comunidad de Madrid** (`datos.comunidad.madrid`, CKAN): sin ningún dataset de contratos menores municipales;
  su búsqueda por "contratos menores ayuntamiento" no devuelve nada relevante (solo estadísticas de contratos
  laborales y parque de vehículos). El portal de datos abiertos del propio Ayuntamiento de Madrid (`datos.madrid.es`)
  sí tiene un dataset de contratos menores, pero es solo del Ayuntamiento de Madrid capital, no de otros municipios
  de la Comunidad.
- **Castilla y León** (`analisis.datosabiertos.jcyl.es/explore/dataset/contratos-menores/`, OpenDataSoft):
  128.119 filas, pero **verificado contra el propio dataset** (campo `organo`): son todas de la Junta de Castilla y
  León (Consejerías, Delegaciones Territoriales) — la administración AUTONÓMICA, no los ayuntamientos. No sirve
  para cobertura municipal.
- **Comunitat Valenciana** (`dadesobertes.gva.es`, CKAN + "Consulta Contractes de la Generalitat"): la búsqueda
  CKAN por "contractes menors ajuntament" no devuelve ningún dataset; la consulta de contractes es de la
  Generalitat, no de los ayuntamientos.
- **Aragón** (`opendata.aragon.es`): el dataset de contratos es "Contratos Gobierno de Aragón" — la administración
  autonómica, mismo patrón.
- **Illes Balears**: el Registre de Contractes (CAIB) es también de la administración autonómica balear y su
  sector público instrumental, no de los ayuntamientos.
- **Castilla-La Mancha**: el Portal de Contratación (`contratacion.castillalamancha.es`) publica los contratos
  menores del sector público REGIONAL en el perfil del contratante de la Plataforma de Contratación del Estado,
  no un registro agregado de los ayuntamientos.
- **Conclusión**: de las comunidades comprobadas, **solo Cataluña (RPC) y la Región de Murcia (CKAN de
  datosabiertos.regiondemurcia.es, ya conectado) tienen un agregador real que cubre ayuntamientos**. Para el resto
  (Madrid, Castilla y León, Comunitat Valenciana, Aragón, Illes Balears, Castilla-La Mancha, y las que faltan por
  comprobar: Andalucía, Galicia [ya con backfill PLACE propio], Extremadura, Cantabria, La Rioja, Canarias,
  Asturias, Navarra) la única vía es ayuntamiento a ayuntamiento, como ya se viene haciendo. **País Vasco es un
  caso especial resuelto de otra forma**: no por un agregador de contratos menores dedicado, sino porque su
  API de contratación (Euskadi, ver más arriba) sirve formales y menores con el mismo mecanismo.

### Investigación ayuntamiento a ayuntamiento por población (2026-09-27, en curso)

Para las seis comunidades sin agregador, se investiga empezando por el municipio más poblado de cada una (solo
fuentes oficiales; cualquier lead de agregador/prensa se marcaría "sin confirmar", pero no ha hecho falta esta
ronda porque todo lo encontrado es fuente primaria municipal):

- **Madrid capital (~3,3 M hab., con diferencia el mayor municipio de los seis) — CONECTADO esta noche**: dataset
  oficial "Contratos menores" de `datos.madrid.es` (id 300253, Dirección General de Contratación y Servicios),
  CSV mensual desde 2015, con NIF. Ver conector `actualizar_contratos_menores_madrid_capital.py` — 27.959
  registros desde 2021-09. El resto de municipios de la Comunidad de Madrid sigue sin agregador (ver arriba);
  cada uno necesitaría su propia investigación.
- **Zaragoza (~675.000 hab., Aragón) — lead confirmado, sin conectar**: el Ayuntamiento publica un dataset OCDS
  (Open Contracting Data Standard) completo en `zaragoza.es/sede/servicio/contratacion-publica/ocds` (catálogo
  147 de su portal de datos abiertos), con CSV/JSON/XML y un endpoint `/ocds/award` con parámetros `after`/
  `before`/`rows`. Incluye contratos menores junto con el resto (habría que filtrar por `procurementMethod` o
  similar). La consulta exacta con parámetros de fecha devolvió error 400 ("Could not find acceptable
  representation") en las pruebas de esta noche -- pendiente de resolver la sintaxis correcta antes de construir
  el conector; es el segundo mayor municipio de los seis y merece prioridad.
- **Valencia capital (~800.000 hab., Comunitat Valenciana) — portal en plena reorganización**: tiene contratos
  menores documentados en su portal de transparencia y un histórico de API CKAN (`gobiernoabierto.valencia.es`),
  pero el rediseño del portal (junio de 2026) ha retirado esa API antigua (redirige a la web nueva, sin CKAN
  operativo comprobado esta noche). Es el municipio más grande de los seis con NINGÚN dato conectado todavía --
  prioridad alta para la próxima ronda, revisando la estructura nueva del portal.
- **Valladolid (~298.000 hab., Castilla y León) — lead confirmado, formato incómodo**: publica "Contratos
  menores y volumen de contratación" en `valladolid.gob.es/es/perfil-contratante/...`, un XLSX por trimestre/año
  (no un dataset único), desde al menos 2018. Viable pero requiere descargar y unificar muchos ficheros con
  estructura que puede variar por año (mismo patrón de riesgo ya visto en Madrid capital esta noche: columnas y
  formato de fecha distintos según el año).
- **Palma (~416.000 hab., Illes Balears) — lead confirmado, formato incómodo**: `palma.es/es/contratos-menores`
  publica Excel + PDF por trimestre. Mismo patrón que Valladolid.
- **Alicante (~337.000 hab., Comunitat Valenciana)**: contratos menores publicados por departamento/servicio
  (no un dataset agregado), en el portal de transparencia reformado en 2024 -- no se ha encontrado un CSV único;
  requeriría más investigación para saber si es viable.
- **Albacete (~173.000 hab., Castilla-La Mancha)**: sin CSV/dataset localizado esta noche en su portal de
  transparencia; solo referencia genérica a la contratación. Pendiente de mirar con más detalle o contactar/
  solicitar acceso a la información (vía el trámite que el propio portal ofrece).
- **Pendiente de revisar** (siguiente ronda, mismo criterio): León, Burgos, Salamanca (Castilla y León);
  Castellón de la Plana, Elche (Comunitat Valenciana); Huesca, Teruel (Aragón); Toledo, Ciudad Real, Guadalajara
  (Castilla-La Mancha); resto de municipios de la Comunidad de Madrid por población.

## Fondos UE

- Solo cubre **Murcia y Girona** — Lleida, Barcelona y Tarragona no están
  conectadas a esta fuente.
- **Cohesion Data** (94% de las filas): el nombre del beneficiario está vacío
  en la fuente oficial para el 100% de los registros españoles (0/139.395,
  verificado). El enriquecimiento vía Kohesio/linkedopendata.eu que intenta
  rellenarlo solo acierta ~6,6% porque esa web bloquea por IP tras una ráfaga
  de peticiones.
- Cohesion Data solo da ubicación a nivel provincial, nunca por ciudad — esos
  registros nunca se asignan a un municipio concreto (quedan agregados en
  `/fondos-ue`). Existe una vía teórica (coordenadas lat/long) para
  geolocalizar al municipio exacto — documentada como ampliación futura, no
  implementada.
- El detector de cargos públicos no aplica a fondos UE: CORDIS (6% de las
  filas) sí trae beneficiario pero son organizaciones, no personas físicas.

## Directivos / Registro Mercantil

- Asociaciones (NIF letra G) y cooperativas (NIF letra F) no están en el
  Registro Mercantil — su junta directiva no es localizable por ninguna
  fuente pública automatizable (investigado y cerrado, incluyendo el
  Registre de Cooperatives de Catalunya).

## Sueldos y cargos públicos

- **Concejales**: ISPA solo publica el importe TOTAL agregado por
  ayuntamiento, sin nombre por fila — cuando hay varios concejales con
  dedicación en el mismo consistorio (el caso mayoritario) es imposible
  atribuir el importe a una persona. Se muestran resaltados pero nunca con
  sueldo. **Desde 2026-09-27 hay una segunda vía, aparte, para los
  municipios cuya web oficial publica una tabla nombre + importe: ver
  "Sueldos de concejales publicados por el propio ayuntamiento" más abajo.**
- **Presidentes de Diputación/CCAA**: 5 personas hardcodeadas a mano, sin
  scraper — si hay elecciones o dimisión hay que actualizarlo manualmente.
- **Alcaldes con 0€**: el motivo (renuncia al sueldo por cobrar ya de la
  Diputación) solo se verificó caso a caso para 3 municipios concretos
  (Sabadell, Sant Boi, Granollers); la nota que se muestra es genérica/
  condicional, no garantiza que sea siempre ese el motivo en otros casos.

## Sueldos de concejales publicados por el propio ayuntamiento (2026-09-26/27)

Regla: solo webs OFICIALES del ayuntamiento (transparencia, sede, boletín oficial, web municipal), nunca agregadores ni prensa.
Un registro exige nombre + cargo/concejalía + importe + URL de la fuente (+ la base del importe tal como la dice la fuente);
si falta algo o es ambiguo se salta y se anota. Nada se estima ni se convierte (mensual → anual). Código:
`backend/actualizar_sueldos_concejales.py`; datos: `backend/sueldos_concejales.json`; bitácora con todos los saltos y anomalías:
`SUELDOS_CONCEJALES_LOG.md`. **Cada ficha con datos muestra un desplegable con las filas enlazadas a su fuente y una nota con las
salvedades de esa fuente** (`_NOTAS_SUELDOS_CONCEJALES` en `app.py`); las fichas de los municipios aparcados muestran un aviso con
el motivo (`_SUELDOS_CONCEJALES_SIN_TABLA`).

- **Cobertura a 2026-09-27**: 697 registros en 36 municipios (Sevilla, Málaga, Cádiz, Huelva, Almería; L'Hospitalet, Terrassa, Sabadell,
  Lleida, Girona, Mataró; Madrid, Majadahonda, Móstoles, Las Rozas; Elche, Castellón de la Plana, Alcoy, Sagunto, Alcalá de Henares, Pozuelo de Alarcón, Torrevieja; Vigo; Logroño; Murcia, Molina de Segura,
  Cartagena; Huesca; Ciudad Real; Santa Cruz de Tenerife; Telde; Palencia, Salamanca; Eivissa, Calvià; Vitoria-Gasteiz). Es una fracción pequeña de España: la mayoría de ayuntamientos publica solo escalas por cargo o nóminas.
- **Salvedades concretas por fuente**:
  - **Sevilla**: cargo mostrado como "Concejal/a" genérico (el PDF fuente no especifica la concejalía); el importe es lo percibido en
    2024 e incluye cantidades pequeñas de concejales sin dedicación.
  - **Madrid**: importe = SUMA de las 12 mensualidades publicadas (una fila por persona y mes), no un importe anual publicado
    directamente; algunas personas tienen menos de 12 meses y la base lo indica.
  - **Eivissa**: algunos importes vienen escritos "63.407.63 €" (punto de millar y punto decimal). Solo se acepta ese patrón exacto
    (3 grupos, 2 cifras finales) tal como se publica; **si la fuente cambia de formato hay que revisar el parser** (`actualizar_eivissa`).
  - **Málaga**: importe = retribución anual del CARGO según la tabla del mismo libro Excel (no nómina individual); solo tenientes de
    alcalde y concejales delegados al 100 %.
  - **Huelva**: importes NETOS 2024. **Terrassa**: MENSUAL bruto (14 pagas), sin convertir. **Vigo** (julio 2023) y **Murcia**
    (febrero 2024): documentos fechados, los importes pueden haberse actualizado. **Palencia**: incluye algún año parcial.
  - **Vitoria-Gasteiz**: importe MENSUAL (sin anualizar) y la fuente rotula a todos los tenientes de alcalde como «teniente alcaldesa».
    **Castellón**: total anual bruto de 2024 (fila «Salario»); una persona con meses a cero se omite. **Móstoles**: la tabla no indica el
    periodo del importe. **Almería**: importes íntegros anuales de 2026; su servidor tiene la cadena de certificados incompleta y la
    descarga va sin verificar certificado (lectura de un documento público).
  - Cada conector excluye al alcalde (cubierto aparte), las asistencias a plenos y las filas con importe ilegible o incoherente.
- **Aparcados por falta de fuente utilizable** (no reintentar salvo fuente nueva; el motivo se muestra en su ficha):
  - **Córdoba**: escala por cargo (2025), sin importe por persona. **Granada**: BOP con nombres por categoría e importes en el
    acuerdo de Pleno aparte. **Jerez**: acuerdos por cargo y dedicación de delegados en documentos separados.
  - **Zaragoza**: tabla por concepto sin nombres. **València**: acuerdo plenario por cargos. **Valladolid**: retribuciones por cargo
    con nº de puestos (dic. 2023), sin nombres.
  - **Bilbao** (solo publica personal de libre designación) y **Alicante**: sin documento nominal localizado. **Palma**: el PDF
    enlazado es de 2023, anterior al mandato.
  - **Lote 5 (2026-09-27, aviso también en la ficha)**: **León** (solo iniciales), **Getafe** (por cargo, sin nombres), **Oviedo** (tabla nominal
    de 2019-2023), **Burgos** (sin cargo; la alcaldesa figura como un corporativo más), **Leganés** (PDF por persona sin nombre dentro y con
    enlaces cruzados), **A Coruña** y **Toledo** (por cargo, sin nombres), **Santander** (página sin contenido), **Las Palmas** (visor no
    legible), **Fuenlabrada**, **Alcobendas**, **Rivas-Vaciamadrid**. Detalle en `SUELDOS_CONCEJALES_LOG.md`.
  - **Lote 6 (2026-09-27, aviso también en la ficha)**: **Donostia** (cargo e importe en un documento, nombres en otro), **Lugo** (por dedicación y
    grupo), **Pontevedra** (mandato 2019-2023), **Ourense** (PDF escaneados sin texto), **Pozuelo** (BOCM sueltos), **Benidorm** (totales mensuales
    sin cargo), **Torrejón de Ardoz** (por cargo, sin nombres). **Las Rozas** sí entra, pero con importes del acuerdo de 2023 que la fuente dice
    que se actualizan con las Leyes de Presupuestos. Santiago de Compostela: portal inaccesible desde aquí, pendiente de reintento.
  - **Lote 7 (2026-09-27)**: **Huesca** y **Ciudad Real** entran (Ciudad Real: nombre con apellidos primero y sin coma, importes de 2024; Huesca: sin
    concejalía). Con aviso en la ficha: **Segovia**, **Guadalajara** y **Pinto** (por cargo, sin nombres). **Ávila** solo publica percepciones NETAS
    (pendiente de decidir si se admiten). Teruel y Mérida: pendientes de reintento (503 / 404).
  - **Lote 8 (2026-09-27)**: **Salamanca** entra con cargo genérico «Miembro de la Corporación» (el PDF no da concejalía ni separa al alcalde, que figura
    en la lista; nota pública). Con aviso: **Jaén** (PDF escaneado sin texto) y **Pamplona** (no localizado).
  - **Lote 9 (2026-09-27)**: **Telde** entra (retribución anual bruta ×14 de 2025). **Torrent** (Valencia) publica recibos de nómina individuales: no se procesan
    (datos personales innecesarios) y no lleva aviso porque su clave en la base pertenece a un municipio homónimo de Girona.
  - **Lote 10 (2026-09-27)**: **Calvià** entra (acuerdo plenario de 2023 en el BOIB, retribución por cargo; sin las indemnizaciones por asistencia). **Torrelavega**
    con aviso (solo nombre e importe, sin cargo ni periodo).
  - **Lote 11 (2026-09-27)**: **Sagunto** (cargo genérico «alcalde o concejal»: el PDF no separa al alcalde; URL con hash) y **Alcoy** (salario anual 2023 del mandato actual)
    entran. **Torremolinos** con aviso (solo recibos de nómina individuales, que no se procesan).
  - **Lote 14 (2026-09-27)**: **Torrevieja** entra (ficha individual por representante, igual que Pozuelo).
  - **Lote 13 (2026-09-27)**: **Pozuelo de Alarcón** entra (ficha individual por concejal con importe, no una tabla).
  - **Lote 12 (2026-09-27, reintentos)**: **Alcalá de Henares** entra (importe por tramo de cargo/dedicación, no por persona; nota
    pública). **Barcelona** (5.ª comprobación, su API sigue en timeout) y **Reus** (su página de retribuciones da 404 en las dos URL
    probadas) siguen aparcados.
  - Pendientes de reintento por otros motivos: **Barcelona** (su API de cargos devolvía "timeout" en dos comprobaciones),
    **Reus** (por cargo, sin nombres), **Alcalá de Henares** (por categoría, sin importe por persona).
- **Plataformas descartadas**: `*.sedelectronica.es/employees` exige Cl@ve (Marbella, Orihuela); seu-e.cat solo rellena el importe en
  la ficha de Girona (43 municipios catalanes sondeados).

## Alcance de 5 años en contratos formales de PSCP/Euskadi/Navarra (2026-09-27)

- **Qué era**: PSCP (Cataluña), Euskadi y Navarra consultan en vivo el histórico COMPLETO de cada municipio (no ZIPs
  mensuales como PLACE) y hasta ahora se guardaba tal cual, sin fecha ni corte de ningún tipo — la propia web lo
  admitía ("todavía no registramos la fecha de adjudicación"). Medido en la copia de producción del 25/09: **65.761
  contratos PSCP, 17.579 Euskadi y 7.643 Navarra ya guardados**, de fechas desconocidas (muchos, probablemente, de
  antes de 2021).
- **Qué cambia**: cada fuente SÍ trae una fecha real, no había que inventar nada:
  - **PSCP**: campo `data_adjudicacio_contracte` (verificado contra varios ajuntaments reales de Girona: fechas
    plausibles 2019-2023, no un valor relleno). Filtro aplicado en el propio `$where` de la consulta (menos filas
    que traer) y también en el código.
  - **Euskadi**: campo `awardDate` de la API (fecha real de adjudicación; 100 % de las filas de contrato menor
    muestreadas lo traían). Filtro en el código, tras traer cada página.
  - **Navarra**: el buscador legacy NO tiene un campo de fecha de adjudicación real en la ficha de detalle (comprobado
    en varias fichas reales) — solo la fecha de PUBLICACIÓN del anuncio en el listado, que se usa como filtro (muy
    cercana a la real, normalmente el mismo mes). El listado de Navarra llega hasta 2013 sin filtro (medido en
    Tudela, 600 filas): sin este cambio se habría seguido guardando todo.
  - Los tres conectores ahora aplican el mismo corte que los menores (`MENORES_DESDE_FECHA`, septiembre de 2021).
- **Cómo se limpia lo ya guardado**: no hay forma de saber la fecha de un contrato PSCP/Euskadi/Navarra ya guardado
  ANTES de este cambio (nunca se capturó) sin volver a consultar la fuente. Hay dos vías, ambas activas:
  1. **Progresiva y automática**: cada vez que un municipio de estas tres fuentes se refresca con normalidad
     (visita de un usuario a una ficha caducada, o un refresco por lotes), `_job_run` sustituye TODA la fuente de
     ese municipio por el resultado fresco (ya filtrado a 5 años) — nunca solo se fusiona, como sí hace PLACE — y
     **archiva** (no borra) las filas que quedan fuera de la ventana en `contratos_formales_archivo` (mismo patrón
     que `contratos_menors_archivo`).
  2. **Barrido forzado de una vez (2026-09-27, a petición de César)**: `depurar_formales_5anios.py` recorre en
     local los ~1.500 municipios conectados de las tres fuentes (942 PSCP, 251 Euskadi, 270 Navarra) reutilizando
     los mismos `buscar_en_pscp`/`buscar_en_euskadi`/`buscar_en_navarra` ya arreglados, y genera
     `correcciones_formales_5anios.json.gz` (por cada municipio+fuente, la lista fresca ya filtrada; solo si la
     búsqueda terminó sin errores y con al menos 1 contrato). Un nuevo loader de arranque,
     `_aplicar_correccion_formales_5anios()`, aplica esa corrección contra lo que haya REALMENTE en producción en
     ese momento — misma lógica de reemplazo+archivado de `_job_run`, calculada en el momento contra el dato real
     (no una lista de "a archivar" congelada de antemano) — una sola vez por versión del fichero (hash en
     `settings`, mismo patrón que `_aplicar_backfill_galicia_place`). Ver el resultado exacto (municipios
     corregidos, contratos archivados) en `INFORME_NOCHE_2026-09-27.md` una vez desplegado.
- **Salvaguarda de seguridad añadida** (probada en producción real, ver abajo): el reemplazo de una fuente SOLO
  ocurre si (a) la búsqueda terminó sin errores HTTP/de red y (b) la búsqueda fresca trajo al menos 1 contrato — así
  un mapeo roto o un fallo silencioso de la fuente nunca puede vaciar todo el histórico de un municipio por error
  (se detectó y corrigió este riesgo durante las pruebas de esta misma noche, con un caso real reproducido).
- **Verificado esta noche** contra una copia real de la cache.db de producción (25/09): Albons (PSCP) 12→9, Amurrio
  (Euskadi) 118→59, Tudela (Navarra) 447→289 contratos; en los tres casos, las filas restantes tienen fecha ≥
  2021-09-01, las descartadas quedaron archivadas, y el resto de fuentes/menores del municipio quedaron intactos.
  Render de ficha (Girona, Tudela) sin errores tras el refresco.

## Viabilidad: cruzar concejales/alcaldes con el Registro Mercantil (2026-09-27)

Informe de viabilidad (sin implementar nada) sobre detectar empresa propia de un cargo público y mostrar sus
cuentas anuales, a petición de César. Ver documento completo:
`INFORME_VIABILIDAD_REGISTRO_MERCANTIL.md`. Resumen: (i) el cruce por nombre sin DNI es viable como primer filtro
si se exige nombre completo + una señal de corroboración (provincia del domicilio social, fecha), y SIEMPRE con
revisión manual antes de publicar una atribución concreta — BORME nunca publica el DNI del administrador, es un
límite estructural, no de implementación; (ii) existencia de empresa + administrador es gratis y reutiliza la
infraestructura ya construida (`buscar_directivo`, BORME/BOE, empresia.es), pero las CIFRAS de cuentas anuales
(balance/PyG) de los últimos 5 años no tienen ninguna vía gratuita a esta escala — BORME solo confirma que hubo
depósito, sin cifras; el Registro Mercantil directo y einforma/axesor/infocif son de pago por informe. Recomendación:
construir solo la Fase 1 (existencia + cargo, gratis) por ahora; las cuentas anuales, caso a caso y bajo demanda.

## Contratos formales de Galicia en PLACE (backfill del patrón "Concello de X", 2026-09-25/27)

- **Qué era**: el patrón antiguo de `_regex_anclado` no reconocía órganos "Concello de X"/"Concello da/do X", así que los contratos
  formales de esos municipios no se atribuían. El fix (a1633d4) solo actúa sobre los ZIP mensuales que se procesen desde entonces;
  los meses anteriores se recuperan con un fichero generado en LOCAL (`backend/backfill_galicia_place.json.gz`, generador
  `backend/generar_backfill_galicia_place.py`) y aplicado al arrancar con una fusión aditiva (`_aplicar_backfill_galicia_place`).
  **Nunca se descargan ZIP en producción.**
- **Desplegado**: 1.738 contratos (tandas 1-7) en 45 municipios, meses **202109 → 202609**: el tope de septiembre de 2021 (alcance de 5 años) está
  cubierto. Cada tanda se probó antes contra una copia REAL de la cache.db de producción (sin pérdidas, sin cambios fuera del fichero, menores
  intactos; la 7.ª: 30 fichas, +266 contratos).
- **Límites**: (1) los meses posteriores a septiembre de 2021 están cubiertos, pero cada mes lo cubre solo lo que PLACE publicó ese mes; (2) solo cubre lo que PLACE publica (Galicia tiene
  contratos que no pasan por PLACE); (3) el fichero lo genera un script en local, no un cron: para ampliarlo hay que ejecutarlo
  (`python generar_backfill_galicia_place.py AAAAMM AAAAMM`). El generador se para solo ante desvíos de tiempo o memoria; las paradas
  observadas fueron carga de otros procesos y una suspensión del equipo, no problemas de datos.
- **Efecto visible**: las fichas gallegas ganan contratos formales (p. ej. Santiago de Compostela 12 → 116); el peso de un solo
  contrato puede ser grande (Santiago: transporte público de 128,6 M€).

## Población, deuda, cuentas anuales

- 5 municipios catalanes sin código INE en el dataset de origen (Santa Fe del
  Penedès, Sant Jaume de Frontanyà, Falset, Sant Jaume dels Domenys,
  Vila-rodona) → excluidos de alcaldes/ISPA/cuentas/población/deuda, por
  diseño.
- Saldo no financiero (superávit/déficit): ~96% de cobertura (949/987) — el
  resto son municipios que ese año aún no han remitido su liquidación a
  Hacienda.
- Enlace de cuentas anuales por año+idEntidad: 97% (957/987) — el 3% restante
  cae al buscador genérico de rendiciondecuentas.es en vez del enlace
  directo.

## Perfil de contratante

- Los municipios catalanes no tienen "Perfil PLACE" propio (su fuente es
  PSCP/RPC) — ese enlace queda vacío para ellos a propósito, no es un fallo.

## Clasificación de organismos estatales/autonómicos — Universidad de Murcia

- **Estado: RESUELTO (commit `5b01a51`, 2026-07-29).** La Universidad de
  Murcia se coló inicialmente en el pseudo-municipio "Administración General
  del Estado" (AGE) por el mismo bug de subcadena que agrupó ahí a Guardia
  Civil/AEAT/TGSS/INSS/etc. — pesaba el 64% de esa entrada pese a ser una
  universidad pública **autónoma**, no AGE en sentido estricto. Se separó a
  su propio pseudo-municipio ("Universidad de Murcia", `NOMBRE_PSEUDO_UMU` en
  `app.py`), con el mismo patrón de detección/acumulación que ya usaba la
  AGE (`_es_organo_umu`, `_guardar_pseudo_municipio_umu`).
  - Confirmado en producción (2026-08-18): `/?muni=Universidad+de+Murcia` y
    `/?muni=Administración+General+del+Estado` son dos fichas distintas.
  - **Corrección de esta misma memoria**: una nota anterior había marcado
    este punto como "pendiente de revisión" — quedó desactualizada, la
    separación ya estaba hecha 3 semanas antes de esa nota.

- **Comunitat Valenciana - contratos menores vía Governalia** (2026-09-24, sin desplegar al escribir esto):
  fuentes `ibi-governalia` (963, idP 72584), `sax-governalia` (2.710, idP 54165) y
  `vilamarxant-governalia` (784, idP 63100), todas en `app.governalia.es`, 2022-2026. Espejo de PLACE:
  importe = adjudicado SIN IVA (6 cifras significativas), verificado contra PLACE en 18 contratos
  (16 exactos, 2 con diferencia de redondeo en obras de cientos de miles de euros) y contra el
  resumen anual del propio portal. Vilamarxant: 5 filas "Contrato menor" por encima de 40.000 €
  (obras de emergencia, hasta 3.679.090 €) con nota visible (`_NOTAS_CONTRATO_MENOR`); se descartan
  2 filas de procedimiento "Abierto simplificado".
  - **Descartados tras verificar en vivo:** Elda, Silla, Picassent y Morella (su página de contratos
    no incrusta ningún módulo y no tienen ninguna página de menores), Villar del Arzobispo y Calvià
    ("Sección no habilitada"), Mutxamel y Orihuela (sin módulo de contratos en Governalia; Orihuela
    usa `orihuela.sedelectronica.es`), Castelló de la Plana y La Pobla de Vallbona (el subdominio
    no existe). **Tolosa**: `tolosa.governalia.es` incrusta por error el módulo de Vilamarxant y
    devuelve datos de otro municipio; no hay fuente de Tolosa.
  - **Mini-lote 2026-09-24 (también descartado):** Alboraya y San Miguel de Salinas tienen sitio Governalia
    pero ninguna página de contratos (Alboraya solo enlaza su perfil del contratante en `alboraya.es`);
    La Oliva tiene página `/transparencia/contratos/` pero vacía (sin módulo incrustado ni llamadas a la API,
    igual que Elda/Silla/Picassent). Por eso `_governalia_menores()`
    valida el municipio real de cada fila (`site`) y aborta si no coincide.

- **Galicia - contratos menores** (2026-09-24, sin desplegar al escribir esto):
  - **A Coruña** (`a-coruna`, 12.960 contratos 2021-2026-T1, ~47,1 M EUR): 24 ficheros ODS
    (trimestrales + 3 "Anexo" anuales) en coruna.gal, descargables con `requests` solo si se envía un
    Referer (sin él, 403). 2014-2019 quedan fuera (facturas sin NIF y otro esquema, anteriores a 2021).
    Importe CON IVA (máximo exacto 48.400 EUR = 40.000 + 21 %). NIF de personas físicas enmascarado
    (22 % de las filas) -> se guarda vacío. 2 filas con importe ilegible descartadas.
  - **Vigo** (`vigo`, 6.643 contratos 2022-2026, ~38,1 M EUR): PDFs anuales sin tabla generados desde su
    aplicación de expedientes; el índice solo enlaza hasta 2022 pero 2023-2026 existen con el mismo
    patrón de nombre. El nombre del adjudicatario PRECEDE a sus contratos (validado: 92-100 % de
    coherencia en proveedores inequívocos vs 13 % con la hipótesis contraria). Sin NIF. Importe CON IVA.
    2021 y anteriores excluidos: sus descripciones van en mayúsculas y se confunden con nombres.
  - **Ferrol** (`ferrol`, 1.550 contratos 2021-2026, ~19,2 M EUR): tabla HTML estática con TODOS los registros
    (2.762 de 2015-2026); un GET con `requests` basta. Importe CON IVA (verificado en el detalle: licitación x 1,21).
    Sin NIF en la lista (el detalle sí lo trae; rastrear 1.575 detalles queda como mejora opcional). "Tipo de
    expediente" es "Contrato menor" + ÁREA municipal, no el tipo de contrato: solo "obras" rellena el tipo. 25
    duplicados exactos colapsados. Máximo desde 2021: 48.387,90 EUR (<= 48.400).
  - **Oleiros: descartado** tras verificar su web, su nota de prensa y su sede electrónica (`sede.oleiros.org`): todo
    remite a PLACE, sin ningún listado de contratos menores.
  - **Pontevedra** (`pontevedra`, 9.401 contratos 2023-2026, ~40,8 M EUR): la sede
    (`sede.pontevedra.gal/public/contratos/contratos-index.xhtml`) tiene una "Consulta de contratos" JSF que pagina
    por AJAX; el conector la reproduce SIN navegador (GET -> POST de búsqueda con tipo 6 "Contrato menor" -> POST de
    paginación con `rows=20000`, ~5 s para todo). Verificado: idéntico al recorrido con navegador (9.411 filas) y las
    estadísticas oficiales del portal coinciden AL CÉNTIMO con las sumas por trimestre (2024-T4, 2025-T1, 2025-T2,
    2026-T2, 2026-T3). Importe CON IVA (max 48.398,79), NIF español incluido en el adjudicatario ("NOMBRE NIF Pyme"),
    datos desde el 2T-2023. 10 filas (67.631,55 EUR) sin adjudicatario se descartan.
  - **Ames** (`ames`, 3.387 contratos 2021-2025, ~13 M EUR): un ZIP anual en concellodeames.gal/es/transparencia/contratos
    con 2 PDF semestrales (tabla de 7 columnas, ~700-770 contratos/año). extract_tables() da filas con 7, 8 o 9 columnas y
    líneas sueltas: se interpreta por ANCLAS de contenido, no por posición. Importe CON IVA (max 48.350,23), escrito de
    formas muy distintas ("449.09 EUR", "4.480 euros", "4.829.99"). SIN fecha por contrato (se usa el inicio del semestre,
    avisado en la ficha) y sin NIF. Los saltos de numeración de la fuente NO son filas perdidas. Descartados: 3 con importe
    ilegible y 9 sin adjudicatario (21.854,30 EUR). Un decreto sin la barra ("21612024") se leía como 21,6 M EUR (corregido).
  - **Salvaguarda del script manual** (2026-09-24): `_fusionar_fuente()` conserva las filas anteriores de una fuente si su
    ejecución falla o devuelve menos del 90 % de lo que ya había (avisa con `!!`; `--forzar` acepta el resultado nuevo).
    Motivo: una ejecución de Ames devolvió 1.896 de 3.387 filas sin ningún error y `main()` habría sustituido la fuente por
    el resultado parcial en silencio. Ames además aborta si falla cualquier ZIP o PDF (un semestre perdido pesa ~9 % y no
    llegaría al umbral).
  - **Ourense: descartado** tras verificar su página oficial de transparencia y su sede electrónica: solo enlaza "Contratos
    (no incluidos los contratos menores)" y el perfil del contratante en PLACE; no hay ninguna sección de menores. El indicio
    de prensa de que dejó de publicar en 2022 queda confirmado por la propia fuente oficial.
  - **Santiago de Compostela** (`santiago`, 8.521 contratos 2021-2T 2026, ~42,3 M EUR): en PLACE sus órganos ("Xunta de
    Goberno do Concello de Santiago de Compostela", 24-42 entradas/mes) publican procedimientos 1/3/8/9, NINGUNO menor, y
    no existe ningún órgano "(CONTRATOS MENORES)" en todo PLACE (jun-2025 ni jul-sep 2026): ese dato de Cowork venía de un
    agregador. La fuente real es `santiagodecompostela.gal/gl/transparencia/relacion-de-contratos-menores` (una página por
    año, XLS trimestrales, actualización mensual; el dominio `transparencia.santiagodecompostela.gal` ya no existe).
    Dos formatos: 2021-1T 2026 "detalle por adjudicatarios" del sistema contable (con NIF, filas de subtotal, fecha = FECHA
    DE ENTRADA del documento) y desde el 2T-2026 tabla plana del Registro Central de Contratos (sin NIF). Importe CON IVA.
    Se EXCLUYEN 30 filas > 48.400 EUR (convenios con el Consorcio de hasta 3,5 M EUR, "entregas a cuenta" a la UTE de
    autobuses, liquidaciones): no son contratos. El 1T-2026 solo cubre del 1 al 8 de enero: del 9 de enero al 31 de marzo de
    2026 no hay datos. Ficheros solapados deduplicados. La web a veces sirve la página del año sin enlaces (reintentos);
    un selector solo por nombre dejaba fuera `RCR2E5.xls` (= 1T-2022).
  - **Lugo** (`lugo`, 5.485 contratos 2021-3T 2025, ~25,1 M EUR): PDF trimestrales en la página de transparencia "Contratos
    menores" de `datosabertos.lugo.gal` (el `node/969` es una plantilla con texto de relleno). DEJÓ DE PUBLICAR tras el
    3T-2025 (4T-2025 y 2026 dan 404). Tabla de 6 columnas (importe con IVA, sin NIF); fechas `dd/mm/aaaa` y `dd-mm-aa`. El
    PDF del 1T-2022 tiene ~31 % de filas ilegibles en origen (117 descartadas). 2 filas de 68.476,32 EUR (aglomerado) superan
    el máximo legal y llevan nota visible.
  - **BUG DE COBERTURA en el pipeline de PLACE para Galicia (arreglado en local, sin desplegar):** `_regex_anclado()` exigía
    "ayuntamiento de X" en el órgano, pero muchos concellos figuran como "Concello de X" ("Xunta de Goberno do Concello de
    Santiago de Compostela"), y los nombres con artículo llevan la contracción gallega ("Concello da Estrada" = "A Estrada"). Con
    el ZIP real de septiembre de 2026: 168 -> 196 contratos asignados a municipios gallegos (+17 %), 59 -> 73 municipios con
    contratos, Santiago 1 -> 6, ningún municipio pierde contratos, ningún órgano se asigna a dos municipios. Producción tenía
    UN contrato de Santiago. Solo afecta a los 313 municipios gallegos de la app. El histórico anterior a los ZIP conservados
    (3 meses) NO se recupera solo: habría que volver a descargar los ZIP mensuales antiguos.
  - **Pendientes de la tanda** (aún sin verificar):
    Santiago (¿ya entra el órgano "Xunta de Goberno
    ... (CONTRATOS MENORES)" por PLACE?), Lugo (¿sigue publicando en 2024-25?), Vilagarcía, Narón,
    Arteixo (rendiciondecuentas.es como posible fuente nacional).

