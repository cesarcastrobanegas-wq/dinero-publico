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
- **Murcia**: solo 5 de los 45 municipios tienen una fuente propia scrapeada
  (**Lorca, Lorquí, Mula, Molina de Segura, Fuente Álamo**) — los otros 40 no
  tienen ninguna fuente conectada, no es que "salga 0", es que nunca se
  consulta nada para ellos. No existe un dataset regional único como el RPC
  catalán para Murcia.
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
