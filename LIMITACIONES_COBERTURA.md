# Limitaciones de cobertura conocidas — Dinero Público

Documento de referencia, no exhaustivo pero sí verificado contra el código y los
datos reales (`backend/cache.db`) a fecha 2026-08-18. Cada punto indica si es un
límite real de la fuente de datos (no arreglable sin una fuente nueva), una
decisión deliberada de alcance, o algo pendiente de hacer.

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
  sueldo.
- **Presidentes de Diputación/CCAA**: 5 personas hardcodeadas a mano, sin
  scraper — si hay elecciones o dimisión hay que actualizarlo manualmente.
- **Alcaldes con 0€**: el motivo (renuncia al sueldo por cobrar ya de la
  Diputación) solo se verificó caso a caso para 3 municipios concretos
  (Sabadell, Sant Boi, Granollers); la nota que se muestra es genérica/
  condicional, no garantiza que sea siempre ese el motivo en otros casos.

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
  - **Pendientes de la tanda** (aún sin verificar):
    Ourense y Ames (verificar en la fuente oficial), Santiago (¿ya entra el órgano "Xunta de Goberno
    ... (CONTRATOS MENORES)" por PLACE?), Lugo (¿sigue publicando en 2024-25?), Vilagarcía, Narón,
    Arteixo (rendiciondecuentas.es como posible fuente nacional).

