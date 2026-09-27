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
- **Estado final: 697 registros en 36 municipios** (commit `ba5a7f2`, lote 14 — se sumó Torrevieja
  después: otra ficha individual por representante, igual que Pozuelo). Bitácora completa,
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
- **Descarga completa terminada**: 155.708 contratos menores en los 251 municipios (113 sin ninguno).
  Volumen real por ciudad grande: Irun 31.969, Errenteria 21.085, Hernani 24.869, Tolosa 15.926, Eibar
  24.126, Elgoibar 10.537, Getxo 12.623 — órdenes de magnitud altísimos para su población (Irun, ~62.000
  habitantes, tendría ~17 contratos menores AL DÍA todos los días durante 5 años). Puede ser real (una
  política de compra muy fragmentada/granular) o reflejar cómo la propia API vasca cuenta/duplica
  entradas — queda anotado para revisar con calma, no se ha podido confirmar ni descartar esta noche.
- **Tope de páginas insuficiente en la primera pasada**: el generador tenía un tope de seguridad de
  200 páginas (10.000 contratos) por municipio, pensado para un caso normal — 7 ciudades lo agotaron sin
  llegar al final de su historial real (Eibar, Elgoibar, Errenteria, Getxo, Hernani, Irun, Tolosa,
  confirmado comparando páginas totales reales — hasta 640 páginas en Irun). **Corregido en el propio
  script** (tope subido a 700 páginas/35.000 contratos, con un corte por TIEMPO de 15 min/municipio en
  vez de por páginas como red de seguridad, y guardado incremental cada 10 municipios para no perder
  progreso si hay que relanzarlo) — el barrido completo ya usó el código viejo (arrancó antes de la
  mejora), así que se ha relanzado un segundo pase **solo para esas 7 ciudades** con el tope nuevo;
  sigue en marcha al escribir esto (unas 2-3 horas estimadas, son las 7 ciudades más grandes).
- **Hallazgo de calidad de datos importante, ya mitigado**: 52 de los 155.708 contratos tienen un
  importe disparatado para un contrato menor (hasta 8.447.000 € por "retirada de columnas de antiguo
  alumbrado" en Loiu, 4.839.353 € por instalar césped artificial en una pista de tenis en Deba...) —
  mismo tipo de error de origen que el caso Prismaglobal/Vitoria-Gasteiz de noches anteriores, pero aquí
  no hay URL por contrato para verificarlo caso a caso (la fuente no la publica para menores) y el
  volumen hace inviable curar cada uno a mano como sí se hizo con Prismaglobal/Cartagena/Lugo. En vez de
  ocultarlos o inventar una cifra corregida, `app.py` ahora muestra un aviso automático (no una lista
  cerrada) en cualquier fila de fuente Euskadi por encima de 100.000 € (`EUSKADI_MENOR_IMPORTE_SOSPECHOSO`),
  explicando que puede ser un error de origen sin forma de comprobarlo. Portugalete concentra más de una
  decena de los 52 casos — posible problema específico de esa fuente/municipio, sin confirmar.
- **YA DESPLEGADO (commit `5955fc8`)**: probado contra una copia real de producción (155.708 filas cargan sin
  romper nada más; render de ficha con formales+menores+sueldos mixtos sin errores; el aviso automático se
  muestra correctamente en las filas altas de Loiu) y subido: `backend/contratos_menores_euskadi.json.gz`,
  `backend/actualizar_contratos_menores_euskadi.py` y el aviso de `app.py`.
- **Decisión sobre las 7 ciudades grandes**: se intentó un segundo pase solo para ellas con el script ya
  corregido (700 páginas), pero Errenteria sola tardó más de 15 minutos (su propio límite de seguridad) sin
  terminar — completar las 7 en serio son varias horas más. Maté el proceso a mitad (sin pérdida: el fichero
  que ya estaba en disco, con la cobertura parcial de esas 7 ciudades, es el que se ha desplegado) en vez de
  seguir esperando esta noche. Quedan documentadas en `LIMITACIONES_COBERTURA.md` con su cobertura exacta
  (31 %-71 % según la ciudad) y el comando exacto para completarlas cuando se decida dedicarle el tiempo.

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
