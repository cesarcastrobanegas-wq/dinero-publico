# Informe de trabajo autónomo nocturno — 2026-09-27

Encargo de César: 3 frentes en paralelo, con commit y push directos según se iba verificando cada
pieza (excepción de esta noche, no cambia el criterio del resto del proyecto). Todo lo de este informe
YA está en `main` salvo que se diga explícitamente lo contrario. Resumen por frente abajo; el detalle
fila a fila de cada pieza vive en `SUELDOS_CONCEJALES_LOG.md` y `LIMITACIONES_COBERTURA.md`.

---

## 1. Sueldos de concejales — 8 lotes más esta noche (lotes 6 a 13)

Partiendo de 386 registros/20 municipios (estado de la noche anterior), esta noche:

- **Reintentos**: Barcelona sigue devolviendo "API timeout error or wrong group ID" (5.ª comprobación,
  su servidor sigue caído, no es cosa nuestra). Reus da 404 en las dos URL de retribuciones probadas
  (reorganizó su web). **Alcalá de Henares y Pozuelo de Alarcón, que estaban aparcados, SÍ se han
  recuperado** al encontrar una forma distinta de leerlos (ver abajo) — ninguno de los dos publica una
  tabla clásica.
- **Municipios nuevos añadidos** (28 en total esta noche): Las Rozas de Madrid, Huesca, Ciudad Real,
  Telde, Calvià, Sagunto, Alcoy, Alcalá de Henares, Pozuelo de Alarcón — sumados a Castellón,
  Vitoria-Gasteiz, Móstoles, Almería, Salamanca de anoche.
- **Estado final: 673 registros en 35 municipios** (commit `bf522c7`, lote 13). Bitácora completa,
  con salvedades de cada fuente y motivo de cada aparcado, en `SUELDOS_CONCEJALES_LOG.md` (lotes 6-13).
- **Casos técnicos interesantes**:
  - *Alcalá de Henares*: no es una tabla — un párrafo por tramo de cargo/dedicación con varias personas
    y un importe compartido por todo el tramo. Algunas llevan una nota `{hasta DD/MM/AAAA}` (ya no está
    ahí) o `{desde DD/MM/AAAA}` (entró después). Parseado con cuidado de no confundir una nota con un
    nombre nuevo (hubo dos intentos fallidos antes de acertar el regex, documentados en el propio
    código).
  - *Pozuelo de Alarcón*: tampoco es una tabla — una ficha web por concejal/a con su importe embebido
    ("Retribuciones y régimen de dedicación (84.044,94 €)"). Se recorre el DOM en vez de la fuente
    plana.
  - *Ciudad Real*: la fuente escribe el nombre con los apellidos primero y sin coma — se deja tal cual
    (separar sería adivinar).
  - *Vitoria-Gasteiz*: el importe de la fuente es MENSUAL, no anual — se muestra tal cual, con nota.
- **Pendiente para cuando retomes**: más ciudades por población (quedan grandes sin comprobar a fondo:
  Gijón, Cáceres, Badajoz, Mérida — todas dieron 404 o sin nombres en los intentos de esta noche).

---

## 2. Contratos menores — mapeo completo de fuentes + un descubrimiento grande (Euskadi)

### 2.1 Mapeo de agregadores regionales (Madrid, Castilla y León, C. Valenciana, Aragón, Baleares, Castilla-La Mancha)

Comprobado en vivo (consulta real a la API/CKAN de cada portal, no solo búsqueda) si existe un
agregador regional que cubra ayuntamientos, como el RPC catalán o el CKAN de Murcia:

**Ninguno de los seis cubre ayuntamientos** — todos publican solo los contratos de la propia
administración autonómica (Consejerías, Generalitat, Gobierno de Aragón...), verificado mirando el
campo `organo`/`organismo` de cada dataset. Detalle completo en `LIMITACIONES_COBERTURA.md`
("Contratos menores — mapeo de agregadores regionales"). Conclusión: de lo comprobado hasta ahora,
solo Cataluña (RPC) y Murcia (CKAN regional) tienen un agregador real; el resto exige ir ayuntamiento
a ayuntamiento, como ya se hacía.

### 2.2 Descubrimiento: la API de Euskadi también sirve contratos MENORES

Mientras comprobaba la fecha real de los contratos formales de Euskadi (ver frente 3), until que la
misma API (`api.euskadi.eus/procurements/contracts`) acepta `minor-contract=true` en vez de `false` —
y devuelve los contratos menores de un ayuntamiento con la MISMA fecha real de adjudicación
(`awardDate`). Cubre los 251 municipios vascos que el proyecto ya tiene mapeados
(`MUNICIPIOS_PAIS_VASCO_EUSKADI_ID`), de una sola vez — el equivalente vasco del RPC catalán, aunque
por un mecanismo distinto (misma API que los formales, no un registro dedicado).

**Construido esta noche**:
- `backend/actualizar_contratos_menores_euskadi.py`: recorre los 251 municipios, filtra por el mismo
  alcance de 5 años (`MENORES_DESDE_FECHA`), aplica la misma corrección de IVA corrupto que ya usan los
  formales de Euskadi (el caso Prismaglobal/Vitoria-Gasteiz de anteriores noches), y hace un sanity
  check de importe (> ~50.000 € = por encima del techo legal con margen de IVA) que se imprime para
  revisión manual, sin excluir nada en automático.
- `_cargar_contratos_menores_euskadi()` en `app.py`: carga el fichero generado a `contratos_menors_locales`
  al arrancar (mismo patrón que el cargador manual de Murcia). Nota pública añadida en la ficha
  (`_NOTAS_FUENTE_CM["euskadi"]`).
- **Estado al escribir esto: LA DESCARGA SIGUE CORRIENDO EN SEGUNDO PLANO** (unos 3.700 contratos
  procesados en ~85 de 251 municipios, con parones de varios minutos en las ciudades grandes: Eibar,
  por ejemplo, tiene 24.126 contratos menores en total y el tope de seguridad del generador
  [200 páginas = 10.000 contratos] se quedó corto — solo se guardaron sus primeros 10.000).
  **Falta**: terminar la descarga completa, probarla contra una copia real de producción (mismo patrón
  que el backfill de Galicia) y hacer commit+push del fichero `.json.gz` + el loader. El código del
  loader ya está en `app.py` pero el fichero de datos (`contratos_menores_euskadi.json.gz`) **todavía
  NO se ha subido** — sin ese fichero el loader no hace nada (es un no-op si el fichero no existe), así
  que no hay ningún riesgo de que algo a medias llegue a producción.
- **Anomalía para revisar con calma**: Eibar (24.126 contratos menores en ~5 años, ~13 al día todos los
  días) es un volumen muy alto para una ciudad de ~27.000 habitantes. Puede ser real (una política de
  compra muy fragmentada) o un artefacto de cómo cuenta la propia API vasca — vale la pena mirarlo con
  detalle antes de darlo por bueno sin más, y quizás ampliar el tope de páginas para completar su
  cobertura real.

---

## 3. Contratos formales PSCP/Euskadi/Navarra — alcance de 5 años (YA desplegado y verificado)

Commit `a057820` (más un ajuste de `LIMITACIONES_COBERTURA.md` en `4fe462b`).

- Las tres fuentes ahora capturan la fecha real de adjudicación (PSCP: `data_adjudicacio_contracte`,
  verificado contra ajuntaments reales, fechas plausibles, no un valor relleno; Euskadi: `awardDate`,
  100% de cobertura en la muestra comprobada; Navarra: sin fecha de adjudicación real en la fuente —
  se usa la de publicación del anuncio, con esa salvedad dicha en la web) y descartan lo anterior a
  septiembre de 2021, igual que los menores.
- **Medido antes del cambio** (para que quede constancia de la magnitud): 65.761 contratos PSCP,
  17.579 Euskadi y 7.643 Navarra ya guardados en producción, de fecha desconocida — buena parte,
  probablemente, de antes de 2021.
- La limpieza de lo YA guardado es progresiva: no hay forma de saber la fecha de un contrato guardado
  ANTES de este cambio sin volver a consultar la fuente, así que la limpieza ocurre sola, municipio a
  municipio, cada vez que ese municipio se refresca con normalidad (visita de un usuario a una ficha
  caducada, o un refresco por lotes) — no se ha forzado un barrido de los ~900 municipios de estas tres
  fuentes esta noche (habría sido tráfico en vivo de varias horas, sin poder verificar cada uno contra
  producción antes de tocarlo).
- **Salvaguarda de seguridad añadida tras un caso real detectado en pruebas**: el reemplazo de una
  fuente solo ocurre si la búsqueda terminó sin errores de red Y trajo al menos 1 contrato — así un
  mapeo roto o un fallo silencioso de la fuente nunca puede vaciar todo el histórico de un municipio.
  Se reprodujo el caso (un municipio mal escrito en una prueba devolvía 0 filas "con éxito") y con la
  salvaguarda puesta ya no se pierde nada.
- **Verificado contra una copia real de la cache.db de producción** (25/09): Albons (PSCP) 12→9,
  Amurrio (Euskadi) 118→59, Tudela (Navarra) 447→289 contratos; las filas descartadas se archivaron en
  la nueva tabla `contratos_formales_archivo` (nunca se borran), y el render de ficha se probó sin
  errores.

---

## 4. Informe de viabilidad: Registro Mercantil (solo investigación, sin código)

`INFORME_VIABILIDAD_REGISTRO_MERCANTIL.md` (commit `cdad3aa`). Resumen de las dos preguntas:

- **(i) Fiabilidad del cruce por nombre sin DNI**: BORME nunca publica el DNI del administrador —es
  un límite estructural del dato público, no de cómo lo implementemos. Recomendación: exigir nombre
  completo (dos apellidos) + una señal de corroboración gratuita (provincia del domicilio social de la
  empresa, fecha de nombramiento), y nunca publicar una atribución automática sin revisión manual.
- **(ii) Fuente de cuentas anuales gratis/barata a escala**: existencia de empresa + administrador, sí
  (gratis, reutilizando `buscar_directivo`/BORME/empresia.es, invirtiendo el sentido de la búsqueda).
  Cifras reales de cuentas anuales (balance/PyG), NO — BORME solo confirma que hubo depósito, sin
  cifras; el Registro Mercantil directo y einforma/axesor/infocif son de pago por informe, inviable a
  miles de personas. Recomendación: construir solo la Fase 1 (gratis) por ahora.

---

## Qué falta para la próxima sesión

1. **Terminar la descarga de Euskadi menores**, probarla contra copia real de prod, commit+push del
   `.json.gz`. Revisar el caso Eibar (24.126 contratos, tope de páginas insuficiente).
2. **Backfill Galicia**: terminado (llegó al tope de 5 años, septiembre de 2021 — ver
   `LIMITACIONES_COBERTURA.md`, sección propia). Nada pendiente ahí.
3. **PSCP/Euskadi/Navarra**: código desplegado; la limpieza del histórico ya guardado es progresiva
   (se irá viendo con el tiempo, municipio a municipio, sin acción adicional necesaria salvo que
   quieras forzar un barrido completo algún día).
4. **Sueldos de concejales**: seguir con más municipios por población cuando quieras continuar (Gijón,
   Cáceres, Badajoz, Mérida no dieron fruto esta noche; quedan por probar muchas ciudades medianas).
5. **Registro Mercantil**: decisión tuya sobre si construir la Fase 1 (gratis) del informe de
   viabilidad.
