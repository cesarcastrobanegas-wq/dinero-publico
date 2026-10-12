# Informe de viabilidad: "Licitaciones y subvenciones vigentes"

Fecha: 04-10-2026. Encargo de César: viabilidad antes de escribir código de producción, con estas decisiones ya tomadas:
licitaciones (PLACSP) y subvenciones (BDNS) juntas desde el inicio, sin alertas por correo en esta fase y sección
gratuita sin monetización. **No se ha implementado nada**: solo se han hecho pruebas reales contra las dos fuentes
(lectura, a ritmo bajo y sin guardar nada en producción).

---

## 0. Hallazgo previo, urgente y ajeno a la sección nueva: el Índice está dejando de recibir contratos de PLACE

Al mirar cómo consume hoy la app el feed de PLACE, he visto un fallo que ya está afectando a producción.

- `descargar_zip_place(anomes)` descarga el ZIP mensual de PLACE **una vez** y, si el fichero ya existe en
  `place_cache/`, lo reutiliza para siempre: `if os.path.exists(cache_path): return cache_path`.
- Pero PLACE **regenera cada día** el ZIP del mes en curso: el de octubre tenía `Last-Modified: 04-10-2026 04:00` y
  el de septiembre `01-10-2026 04:00`. El primer día del mes el ZIP está casi vacío y va creciendo.
- Estado real del disco de Render hoy (`/api/diagnostico-arranque`):

  | ZIP | En Render | Completo en PLACE |
  |---|---|---|
  | place_202608.zip | 152,7 MB | completo |
  | place_202609.zip | **16,1 MB** | más de 122 MB (mi descarga se cortó ahí: el servidor de PLACE se colgó y no admite reanudar) |
  | place_202610.zip | **0,0 MB** (no es un ZIP válido; se ignora en cada pasada y no se vuelve a pedir) | 17,2 MB a día 04 |

- Consecuencia: de los contratos formales de PLACE de septiembre solo se procesó lo publicado hasta el día en que se
  descargó por primera vez (los primeros 3-4 días: como mucho un 15 % del mes; si además la descarga quedó truncada, el ZIP ni siquiera abre y no se procesó nada). Y de octubre, nada desde el ZIP. Lo único
  que entra es el feed "en vivo" que la app consulta en cada pasada, que solo trae las últimas ~290 entradas (unas
  horas en día laborable, ~30 h en fin de semana). PLACE publica ~1.100 entradas adjudicadas o resueltas por día
  laborable (medido en septiembre: entre 900 y 1.750 al día), así que el feed en vivo recoge en torno a un 10 %.
  **Estimación: falta en el Índice entre el 75 % y el 90 % de los contratos formales de PLACE de septiembre y
  octubre de 2026.**
- Otra forma del mismo fallo: si el servidor de PLACE corta la conexión limpiamente a mitad de la descarga (me ha
  pasado hoy), `descargar_zip_place` da el fichero por completo sin comprobar nada y lo guarda para siempre.
- No es nuevo: en local también estaba `place_202606.zip` con 521 bytes (una respuesta de error guardada como ZIP).
  El mismo patrón puede haber dejado otros meses a medias antes de la purga de 3 meses. El backfill de formales
  (02-10) usó ZIP completos, así que el histórico de 2021 a agosto de 2026 debería estar bien; el hueco serio es
  septiembre y octubre de 2026, y el riesgo es que se repite cada mes.
- **Arreglo propuesto (pequeño, independiente de este informe)**: volver a descargar el ZIP del mes en curso y del
  anterior cuando el del servidor sea más reciente (Last-Modified, o simplemente si el local tiene más de ~20 h), y
  no dar nunca por bueno un fichero que no abre como ZIP. Después, una pasada que reprocese septiembre y octubre.
  Decisión 1 del §D.

---

## A) Licitaciones (PLACSP)

### A.1 ¿Ya consumimos este feed? Sí

La app ya lee exactamente `sindicacion_643/licitacionesPerfilesContratanteCompleto3` en sus dos formas:

- ZIP mensual (`PLACE_ZIP_BASE`, `descargar_zip_place`), con descarga reanudable y caché en disco.
- Atom en vivo (`PLACE_FEED_LIVE`, `buscar_en_feed_vivo`).

El parser es `_entry_to_contratos` (más `_parse_summary`, `_re_tag`, `_re_tag_block`, órgano, código postal, lotes y
adjudicatarios). Hoy **descarta a propósito** todo lo que no esté adjudicado:
`if estado not in ("ADJ", "RES", "FOR"): return []`. Las licitaciones abiertas (`PUB`) pasan por delante y se tiran.

Conclusión: no hace falta un parser nuevo. Se añade una función hermana, `_entry_a_licitacion(entry_xml)`, que
reutiliza los mismos helpers y se queda con lo que hoy se descarta. Y el recorrido de los ZIP o del Atom se hace una
sola vez para las dos cosas.

### A.2 Qué trae cada entrada (medido)

Medido con los ZIP de julio y agosto de 2026 (236 MB, 79.693 entradas, 48.747 expedientes distintos):

- Estados de la última versión de cada expediente:
  - RES (resuelta): 22.339
  - PUB (en plazo): 9.416
  - EV (pendiente de adjudicar): 8.785
  - ADJ: 7.891
  - PRE (anuncio previo): 168
  - ANUL: 3
- Tamaño de cada entrada: mediana 26 KB, p99 104 KB, máximo 3,2 MB. Ninguna justifica cargar nada entero en memoria;
  se procesan una a una.
- De las PUB con plazo a 15-08 (6.858), los campos para la ficha:

  | Campo | Disponible |
  |---|---|
  | título, órgano, NIF del órgano, enlace a la ficha oficial | 100 % |
  | presupuesto sin IVA y valor estimado | 100 % |
  | fecha y hora fin de presentación (`TenderSubmissionDeadlinePeriod/EndDate`) | 99,7 % de las PUB |
  | provincia (NUTS) | 99,9 % |
  | pliegos (enlaces) | 99,2 % |
  | CPV | 98,7 % |
  | código DIR3 del órgano | 88 % |

- Tipo de contrato: servicios 40 %, suministros 29 %, obras 25 %, el resto otros.
- Con lotes: 16 %.

**¿Cuántas hay abiertas a la vez?** Medido a día 04-10, con los ZIP de julio, agosto, septiembre (hasta el 23) y
octubre (125.000 entradas, 63.807 expedientes):

- **3.027 licitaciones con plazo abierto hoy**. Falta la última semana de septiembre, que no llegó a bajar; con ella,
  calculo **entre 4.000 y 5.000 abiertas en cualquier momento**.
- Un dato importante para la regla de "vigente": **dos tercios de las que siguen en PUB ya tienen el plazo vencido**
  (6.639 de 9.666). El estado de PLACE no se actualiza a EV hasta que el órgano lo publica, así que el estado solo no
  basta: manda la fecha fin.

### A.3 Definición de "vigente"

Una licitación es vigente si se cumplen las cuatro condiciones:

1. su **última** versión (mayor `<updated>` para el mismo `<id>` de entrada) tiene `ContractFolderStatusCode = PUB`;
2. `EndDate` (+ `EndTime`) de presentación es igual o posterior a ahora;
3. no hay después un `at:deleted-entry` para ese id;
4. no hay versión posterior en EV/ADJ/RES/ANUL.

El estado "ADJ" llega como **nueva versión del mismo `<id>`**, así que la regla de la última versión cubre el caso de
"adjudicación posterior para el mismo expediente". No conviene cruzar por `ContractFolderID`: no es único entre
órganos (253 repetidos solo entre las abiertas de julio y agosto). La clave es el `<id>` de la entrada.

Sin fecha fin (0,3 %): no se muestra como vigente. Otra opción es "plazo según pliego", pero me parece peor, porque es
justo lo que suele estar mal.

### A.4 Modelo de datos (SQLite, la misma `cache.db`, tabla nueva)

```
licitaciones (
  id TEXT PRIMARY KEY,          -- <id> de la entrada de PLACE
  actualizado TEXT,             -- <updated>
  estado TEXT,                  -- PUB/EV/ADJ/RES/ANUL...
  fin_plazo TEXT,               -- AAAA-MM-DDTHH:MM (índice)
  titulo TEXT, organo TEXT, nif_organo TEXT, dir3 TEXT,
  municipio_clave TEXT,         -- clave_municipio(...) si el órgano es un ayuntamiento (enlace con la ficha)
  provincia TEXT, nuts TEXT, cpv TEXT, cpv2 TEXT, tipo TEXT, procedimiento TEXT,
  presupuesto REAL, valor_estimado REAL, lotes INTEGER,
  url TEXT, url_pliegos TEXT,
  visto TEXT                    -- última vez que lo vimos en la fuente
)
índices: (estado, fin_plazo), (provincia, fin_plazo), (cpv2), (municipio_clave)
```

Tamaño estimado: unas 4.000-5.000 vigentes × ~1 KB, más las que pasan a cerradas (se borran a los 30 días del fin de
plazo). Del orden de 10-20 MB en disco y **0 MB permanentes en RAM**: las páginas consultan con `LIMIT/OFFSET` y los
filtros van por índice, igual que el resto del sitio tras el arreglo de memoria del 03-10.

### A.5 Cadencia de actualización

- **Carga inicial**: ZIP del mes en curso y del anterior; las abiertas de hace más de 2 meses son raras. Se procesan
  `.atom` a `.atom` y entrada a entrada, nunca el ZIP entero en memoria. Es el mismo ZIP que ya baja el Índice: no hay
  descarga extra.
- **Diaria, incremental**: el Atom en vivo trae ~290 entradas por página (8,5 MB, **78 s** de descarga: el servidor
  de PLACE es lento) y un enlace `rel="next"` a la página anterior. Se siguen páginas `next` hasta llegar a una
  entrada ya vista (`actualizado` <= el último guardado). En día laborable PLACE publica ~1.300 entradas, unas 5
  páginas: ~40 MB y ~7 min al día. El ZIP del mes queda como red de seguridad semanal: si el Atom falla algún día, se
  recupera ahí, siempre que se arregle lo del §0.
- **Caducidad**: una consulta barata cada hora (`UPDATE ... WHERE fin_plazo < now`) o, simplemente, filtrar por
  `fin_plazo >= now` al mostrar. No hace falta ninguna tarea extra.
- **Dónde se ejecuta**: igual que hoy los contratos. El flujo diario de GitHub Actions lanza un job en Render
  (`/api/job`), y el job corre en un hilo del worker, después de `post_fork`, nunca al importar. Así no se repite el
  fallo de `--preload` y se ve en el diagnóstico. Pico de memoria esperado: una página Atom (8,5 MB) o un `.atom` del
  ZIP a la vez, más el parseo de una entrada. Despreciable frente a los 780 MB actuales.

---

## B) Subvenciones (BDNS)

### B.1 Prueba real contra la API: el parámetro `soloAbiertas` no existe

- La API oficial (`https://www.infosubvenciones.es/bdnstrans/api`, especificación OpenAPI publicada en
  `/bdnstrans/estaticos/doc/snpsap-api.json`, versión 1.1.0, 52 rutas) **no tiene ningún parámetro para filtrar
  convocatorias abiertas**.
- Probé `soloAbiertas=true`, `soloAbiertas=S`, `abierto`, `abiertas`, `convocatoriasAbiertas` y `estado=abierta`:
  todas devuelven el total completo, **656.107** convocatorias. El parámetro se ignora en silencio.
- La búsqueda (`/convocatorias/busqueda`) solo filtra por:
  - texto, número BDNS y fechas de **registro** (`fechaDesde`/`fechaHasta` en formato dd/mm/aaaa);
  - administración (estatal, autonómica, local), órganos y regiones (NUTS);
  - tipo de beneficiario, instrumento, finalidad, MRR y ayuda de Estado.
- La búsqueda y la exportación CSV (`/convocatorias/exportar`) **no traen el plazo**, solo el número, el órgano, la
  fecha de registro y el título.
- El plazo y el resto de la ficha solo vienen en el detalle de cada convocatoria
  (`/convocatorias?vpd=GE&numConv=N`), es decir, **una petición por convocatoria**.

### B.2 Tamaño, paginación y límites (medido)

- Búsqueda: pagina con `page` y `pageSize`. Admite `pageSize=10000` (4 MB, 5 s) y no más: el máximo por página es
  10.000.
- Volumen de registro: ~5.400 convocatorias al mes (septiembre de 2026: 5.390; enero a septiembre de 2026: 51.923;
  1 de enero de 2025 a 30 de junio de 2026: 106.252).
- Detalle: ~3 KB por convocatoria, latencia mediana de 0,13 s.
- Límite de tasa: en 500 peticiones de detalle a 1 por segundo **no hubo ningún 429 ni error**. No hay cabeceras de
  límite. Pero cada respuesta incluye un aviso: la Administración "podrá adoptar medidas restrictivas de acceso al API
  ante situaciones de manifiesto abuso". Hay que ir a ritmo bajo (1 petición por segundo), identificarse en el
  User-Agent como con el BOE y no repetir peticiones.
- Aviso legal de reutilización: la propia API lo enlaza
  (`https://www.infosubvenciones.es/bdnstrans/GE/es/avisolegal`). Hay que leerlo entero antes de publicar; está en el
  §D. Las convocatorias no llevan datos personales; las concesiones a beneficiarios sí, pero quedan fuera de esta
  sección.

### B.3 ¿Trae lo necesario para una ficha mínima? Sí, salvo el plazo en un tercio de los casos

Sobre las convocatorias vigentes de la muestra:

| Campo | Disponible |
|---|---|
| título | 100 % (también el título en lengua cooficial cuando lo hay: `descripcionLeng`) |
| organismo (`organo.nivel1/2/3`: administración / comunidad o municipio / órgano) | 97 % |
| importe (`presupuestoTotal`) | 99 % |
| beneficiarios (`tiposBeneficiarios`) | 100 % |
| región (`regiones`, NUTS) | 100 % |
| sector y finalidad | 100 % |
| enlace a las bases (`urlBasesReguladoras`) | 100 % |
| documentos (PDF de bases y extracto, descargables por la API) | 100 % |
| enlace oficial a la ficha BDNS | se construye con el número |

- **Plazo**: `fechaInicioSolicitud`/`fechaFinSolicitud` vienen en ~60 % de los casos. En el resto no hay fecha fin.
  A veces hay un texto (`textFin`, p. ej. "20 días hábiles desde la publicación del extracto") y a veces nada.
- **El campo `abierto` de la API no es fiable**: en 76 de 300 casos decía `false` estando hoy dentro de
  [inicio, fin]. El estado hay que calcularlo por fechas.

Muestra de 200 convocatorias clasificadas por fechas a día 04-10:

| Registradas en | Abiertas por fechas | Sin fecha fin | Cerradas | Aún no abren |
|---|---|---|---|---|
| ene 2025 - jun 2026 (120) | 33 % | 31 % (8 con `abierto=true`) | 34 % | - |
| jul - oct 2026 (80) | 26 % | 54 % (9 con `abierto=true`) | 18 % | - |

Estimación, con mucha incertidumbre porque la muestra es pequeña: entre **25.000 y 45.000 convocatorias abiertas por
fechas**, más varias decenas de miles "sin fecha fin" cuyo estado real no se puede saber sin leer las bases. Son
muchas más que las licitaciones, y casi todas locales (77 % de las vigentes de la muestra son de ayuntamientos y
diputaciones).

### B.4 Modelo de datos y cadencia

```
subvenciones (
  bdns TEXT PRIMARY KEY, id INTEGER, registrada TEXT,
  titulo TEXT, titulo_cooficial TEXT,
  nivel1 TEXT, nivel2 TEXT, organo TEXT, municipio_clave TEXT, provincia TEXT, nuts TEXT,
  presupuesto REAL, beneficiarios TEXT, sector TEXT, finalidad TEXT, instrumento TEXT, tipo TEXT, mrr INTEGER,
  inicio TEXT, fin TEXT, texto_fin TEXT,
  estado TEXT,                  -- abierta / proxima / sin_fecha / cerrada (calculado por fechas)
  url_bases TEXT, revisado TEXT
)
índices: (estado, fin), (provincia, estado), (nivel1, estado), (municipio_clave)
```

- **Carga inicial (una sola vez)**: listar por meses desde 2024 (~200.000 números de convocatoria, con 20-30
  peticiones de 10.000) y pedir el detalle de cada una a 1 por segundo: **~55 horas**. Se puede repartir en varias
  noches desde GitHub Actions (máximo 6 h por ejecución, reanudable) o hacerla en el PC y subir el resultado. Se
  guardan solo las abiertas, las próximas y las "sin fecha" de los últimos 12 meses; de las cerradas basta con el
  número para no volver a pedirlas.
- **Diaria**: las registradas ayer (~250 detalles, ~4 min) y volver a revisar las que cambian de estado sin aviso: las
  "próximas" el día que abren y las "sin fecha" una vez por semana. Unas 500-1.500 peticiones al día, 10-25 min a
  1 por segundo.
- **Dónde**: igual que las licitaciones, un job lanzado por Actions que corre en Render tras `post_fork`. La carga
  inicial, fuera de Render.
- **Memoria**: nada en RAM; tabla con índices y páginas con `LIMIT`. En disco, ~50-150 MB según cuántas "sin fecha"
  se guarden.

---

## C) Diseño de la sección (propuesta, no decidido)

### C.1 Dónde vive

Propongo una sección nueva en el menú, **"Convocatorias abiertas"**, con dos pestañas: Licitaciones y Subvenciones.
Además, una entrada pequeña en las fichas existentes:

- **Ficha de municipio**: "Licitaciones abiertas de este ayuntamiento (N)" y "Subvenciones abiertas (N)", que llevan a
  la sección ya filtrada. El enlace es por `municipio_clave`: el órgano de PLACE con el mismo anclaje que ya usa el
  Índice ("Ayuntamiento de X" más el código postal), y en la BDNS `nivel1=LOCAL` con `nivel2` igual al municipio.
- **Ficha de empresa** (si se hace): las licitaciones abiertas no tienen empresa todavía, así que no aplica. Solo
  tendría sentido más adelante, como "licitaciones abiertas en su CPV habitual", y sería otra fase.

Motivo: el público de esta sección (autónomos, pymes, asociaciones) busca por "qué hay abierto para mí", no por
organismo. Pero el enlace desde la ficha del municipio es barato y da contexto a lo que ya es la web.

### C.2 Filtros mínimos

- **Licitaciones**: provincia o comunidad, tipo (obras, servicios, suministros), sector (CPV a 2 dígitos con nombre
  legible: 45 Construcción, 72 Informática...), importe (tramos), plazo (cierra en 7 días / 30 días / todas) y texto
  libre. Orden por defecto: las que cierran antes.
- **Subvenciones**: ámbito (estatal, autonómica, local), comunidad o provincia, tipo de beneficiario (personas
  físicas, pymes y autónomos, entidades sin ánimo de lucro...), sector o finalidad, plazo y texto libre. Las "sin
  fecha fin" van en su propio bloque o con un filtro "incluir las que no indican plazo", con la nota "plazo según
  bases: consúltalas antes de presentar nada".
- Cada fila: título, órgano, importe, "cierra el dd/mm (en N días)" y enlace a la fuente oficial. Ninguna acción
  propia: no se presentan ofertas ni solicitudes desde aquí.

### C.3 Idiomas

- Gallego y catalán, como el resto del sitio: textos de interfaz por `.po`, unos 40-60 textos nuevos. Euskera sigue
  en pausa, como se decidió.
- Los títulos de las convocatorias van tal cual vienen. La BDNS da a veces el título en lengua cooficial
  (`descripcionLeng`), y se puede mostrar ese cuando el idioma de la página coincide. PLACE no lo da.

### C.4 Avisos legales y de producto

- Nota fija: "Información de PLACSP/BDNS a fecha dd/mm. El plazo y los requisitos que valen son los de la
  publicación oficial."
- Página de metodología: qué es "vigente", con qué frecuencia se actualiza y qué se excluye (sin fecha, anuncios
  previos).

---

## D) Decisiones pendientes para César

1. **Arreglo del §0 (contratos de PLACE de septiembre y octubre que faltan en el Índice).** Recomiendo hacerlo ya,
   antes y por separado de la sección nueva: es un cambio pequeño, más una pasada que reprocese septiembre y octubre,
   que vigilaré igual que las anteriores. ¿Lo hago?
2. **Subvenciones sin fecha fin (~30-50 % de la BDNS).** Las opciones son:
   - (a) mostrarlas aparte, con "plazo según bases";
   - (b) ocultarlas;
   - (c) intentar calcular el plazo leyendo `textFin` ("N días desde la publicación del extracto"), cruzado con la
     fecha del extracto en el boletín.

   Recomiendo (a) ahora y (c) como mejora posterior.
3. **Alcance temporal de la carga inicial de la BDNS**: desde 2024 (~55 h de peticiones, repartidas en noches) o
   solo los últimos 12 meses (~18 h, perdiendo algunas plurianuales). Recomiendo 2024.
4. **Dónde hacer la carga inicial de la BDNS**: GitHub Actions (gratis en repositorio público, sin coste) o tu PC.
   Recomiendo Actions.
5. **Aviso legal de la BDNS**: hay que leerlo entero y aceptar sus condiciones antes de publicar. Puedo resumírtelo
   en el siguiente paso, antes de escribir código.
6. **Nombre y lugar en el menú**: "Convocatorias abiertas", con pestañas Licitaciones y Subvenciones, o dos entradas
   separadas.
7. **Anuncios previos (PRE) de PLACE**: mostrarlos como "próximamente" o no. Son pocos (~170 en dos meses).
   Recomiendo que no, en la primera versión.

### Estimación aproximada de esfuerzo (sesiones de trabajo como las de estos días)

| Pieza | Esfuerzo | Notas |
|---|---|---|
| §0 arreglo de los ZIP de PLACE | 0,5 | incluye la pasada de reprocesado y su vigilancia |
| Licitaciones: parser, tabla, carga inicial e incremental diaria | 2-3 | reutiliza el parser y la descarga del Índice |
| Subvenciones: cliente de la API, tabla, carga inicial (más ~55 h de reloj desatendidas) y diaria | 2-3 | fuente nueva; lo lento es la carga inicial, no el código |
| Sección web: listado, filtros, fichas de municipio, metodología | 2-3 | sin JavaScript nuevo pesado; páginas por consulta SQL |
| gl/ca y pruebas en copia de producción | 1 | |
| **Total** | **~8-10** | más la carga inicial de la BDNS corriendo en paralelo |
