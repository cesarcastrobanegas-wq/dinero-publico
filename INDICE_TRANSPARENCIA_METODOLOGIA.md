# Índice de Transparencia Dinero Público — metodología (v2.1)

Versión 2.1, 09-10-2026 (umbral de evidencia y suavizado, ver su sección; desplegada el 09-10-2026). Versión 2, 29-09-2026. La v1 (7 componentes, agosto de 2026) y su distribución real en producción están en
`INDICE_TRANSPARENCIA_V1_LINEA_BASE.md`. El código es `_calcular_indice_transparencia` en `backend/app.py`.

**Qué es y qué no es.** Una valoración propia de la disponibilidad y calidad de los datos públicos de cada
municipio que este proyecto consigue reunir. No es una certificación de cumplimiento de la Ley 19/2013: el proyecto
no es organismo acreditador.

## Regla común: "no disponible" no es 0

Si a un municipio le falta un dato por un hueco de cobertura de este proyecto (fuente no conectada, fuente oficial
que no cubre su comunidad, portal aún no revisado), ese componente queda **no disponible**: se excluye y su peso se
reparte entre los componentes disponibles. Solo puntúa 0 lo que la fuente oficial sí cubre y el municipio no publica.
La misma regla se aplica dentro de un componente (ver "menores" en agregadores).

- Nota = media ponderada (0-100) de los componentes disponibles, redondeada a 1 decimal (también en la portada).
- **Umbral mínimo: 4 componentes disponibles** (v1: 3). Por debajo, el municipio sale como "cobertura insuficiente".
- **Umbral de evidencia (v2.1): 20 contratos** (formales + menores guardados). Por debajo, la nota se calcula y se
  enseña en la ficha con la etiqueta «muestra pequeña», pero el municipio no entra en rankings ni tiene puesto.

## Componentes y pesos

| Componente | Peso v2 | Peso v1 | Cómo se puntúa |
|---|---:|---:|---|
| Contratos menores publicados | **20** | — | Solo con fuente conectada. Portal municipal: publicarlos 40 + años cubiertos desde 2021 20 + frescura del último registro 20 (≤90 días 100, ≤180 70, ≤365 40, más 10) + % con adjudicatario identificado 20. Agregador regional (RPC Cataluña, API Euskadi): años y frescura **no disponibles**; nota = (40 + 20 × %adjudicatario) / 60. **Feed de menores de PLACE** (desde el 30-09): misma fórmula que un portal, con años esperados desde **2023**. Sin ningún contrato menor: no disponible. |
| Adjudicatario identificado | **15** | 20 | % de contratos formales (PLACE/PSCP/Euskadi/Navarra) con adjudicatario identificado, **suavizado (v2.1)**: (num + 10·p₀) / (den + 10), con p₀ = media nacional. |
| Retribuciones de cargos electos | **10** | 10 (sí/no alcalde) | 100 si publica el sueldo de los concejales con nombre e importe (tabla revisada a mano, `sueldos_concejales.json`); **50 si solo consta el del alcalde** (ISPA); 0 si ni eso. No disponible solo en Ceuta/Melilla (ISPA no las cubre). |
| Formato del portal propio | **5** | — | Portal donde el ayuntamiento publica sus menores: dataset/API o fichero estructurado 100, tabla web o consulta 66, PDF con texto 33, PDF escaneado o sin listado propio (remite a PLACE) 0. Solo para los municipios clasificados a mano (conector propio + auditoría de las 29 ciudades >100.000 hab.); el resto, no disponible. |
| Actividad de publicación | **15** | 20 | Contratos **formales** por 1.000 habitantes, en percentil dentro de su tramo de población (<1.000, <5.000, <20.000, <100.000, >100.000). |
| Cuentas anuales | **10** | 15 (binario) | Según el último ejercicio rendido a rendiciondecuentas.es frente al último **exigible por ley**: al día 100, un año de retraso 50, dos o más o sin rendir 0. No disponible en País Vasco, Navarra, Ceuta y Melilla (Tribunal de Cuentas foral o no listadas). |
| Deuda viva publicada | **7,5** | 12,5 | Binario (Ministerio de Hacienda). |
| Saldo no financiero publicado | **7,5** | 12,5 | Binario (Ministerio de Hacienda). |
| Directivo identificado | **10** | 10 | % de adjudicatarios (formales + menores) con directivo/administrador identificado. No se suaviza. |

## Por qué cada cambio respecto a la v1

- **Contratos menores (nuevo, 20 %)**: son la mayor parte del gasto contractual fragmentado y lo que menos se
  publica de forma reutilizable; la v1 no los medía. Con el feed nacional de menores de PLACE (30-09, opción A de
  César) es calculable en el **~55 %** de los municipios (antes 11,5 %). Un municipio sin ningún contrato menor en
  ninguna fuente sigue siendo **no disponible**, no 0 (opción B descartada): registrar los menores en PLACE no es
  obligatorio y muchos pueblos los publican en su web o en PDF.
- **Feed de PLACE graduado, no como agregador** (30-09): con la regla de agregadores casi todo municipio presente en
  el feed sacaba ~99-100 (el feed trae NIF en el 99,6 %), un componente binario por presencia que habría vuelto a
  amontonar las notas cerca de 100. Se gradúa como un portal (años cubiertos y frescura, criterio de la rama
  wip/indice-transparencia-v2) con los años esperados desde 2023, primer año con el feed generalizado (en 2021-2022
  apenas tiene datos). Efecto aceptado: un pueblo con 1-2 contratos antiguos en el feed puntúa bajo en menores.
- **Menores en agregadores regionales, sin años ni frescura** (corrección del 29-09): en el RPC o en Euskadi, que un
  pueblo pequeño no tenga contratos recientes significa que no contrató, no que dejara de publicar. Con esos dos
  subcomponentes, Viladamat bajaba de 93,7 a 70,6 y Granyanella de 96,6 a 72,7 por tener 3 contratos antiguos,
  quedando por debajo de pueblos sin ningún dato.
- **Actividad solo con contratos formales**: en la v1 los contratos menores entraban en el percentil, así que
  subía quien tenía una fuente de menores conectada (sesgo de cobertura del proyecto, no de transparencia real):
  Gijón, con 37.000 menores, pasaba al percentil alto de su tramo. PLACE/PSCP cubren por igual a toda España.
- **Retribuciones con escala 0/50/100 para todos** (corrección del 29-09): en la primera versión de la v2, "solo
  el alcalde" daba 50 en los ~36 portales revisados sin tabla de concejales y 100 en los no revisados — el
  municipio revisado salía peor que el no revisado con la misma información publicada (Torrejón de Ardoz caía de
  #2.323 a #4.309 solo por eso).
- **Cuentas graduadas por el último ejercicio rendido** (corrección del 29-09): con el binario de la v1, cuentas,
  deuda, saldo y retribuciones (el 50 % del peso) valían 100 en casi todos y las notas se amontonaban arriba (v1:
  18,6 % de municipios con 90 o más; top 10 lleno de empates). Escala propuesta por César (100 al día / 50 un año
  de retraso / 0 dos o más o sin dato), anclada al **último ejercicio exigible**: la Cuenta General del año N se
  rinde antes del 15 de octubre de N+1 (art. 223 TRLRHL). Contar desde el año natural habría puesto a 50 a los
  5.130 municipios que ya rindieron 2024 dos semanas antes de que venza el plazo de 2025. Hasta el 14-10-2026 lo
  exigible es 2024 (2025 o 2024 = 100, 2023 = 50); desde el 15-10-2026, 2025 (la escala se actualiza sola).
- **Formato (nuevo, 5 %)**: premia publicar en formato reutilizable. Peso bajo porque solo hay 67 municipios
  clasificados; el resto no disponible, nunca una nota por defecto.
- **Umbral de 3 a 4 componentes**: con 9 componentes posibles, 3 era demasiado poco. Ningún municipio pasa de
  "cobertura suficiente" a "insuficiente" con el cambio (los 48 con exactamente 4 siguen dentro).

## v2.1 (09-10-2026): umbral de evidencia y suavizado

**Diagnóstico.** El top nacional de la v2 lo ocupaban pueblos de menos de 100 habitantes con 3-4 contratos
(Cellorigo: 15 hab., 4 contratos, 93,3; 9 de los 20 primeros tenían menos de 10 contratos). Tres causas que se
suman: la actividad por 1.000 habitantes se dispara con poblaciones minúsculas; adjudicatario y directivo dan 100 %
con muestras de 4; y menores y formato, no disponibles, reparten su peso entre los componentes fáciles.

**Cambios** (código: `_INDICE_MIN_CONTRATOS_RANKING`, `_INDICE_SUAVIZADO_K`, `_indice_filas_ranking` en `backend/app.py`):

- **Umbral de evidencia**: constante `_INDICE_MIN_CONTRATOS_RANKING = 20`. Cuenta los contratos formales más los
  menores que la base guarda del municipio (todo el periodo guardado, hoy desde 2021). Por debajo, la ficha muestra
  la nota con la etiqueta «muestra pequeña», la explicación y el desglose, y el municipio queda fuera de todo lo que
  ordena o da puesto: tabla de /rankings, lateral de portada, «Liderando ahora mismo», lista de la ficha, buscador de
  posiciones y «tu municipio». Para subir el umbral basta cambiar la constante: la interfaz y los textos la leen de ahí.
- **Suavizado bayesiano solo en adjudicatario**: nota = (num + K·p₀) / (den + K), con K = 10 y p₀ = media nacional
  del componente, calculada como suma de numeradores entre suma de denominadores de todos los municipios (92,0 % en
  la medición). Equivale a añadir a cada municipio 10 contratos «medios». El detalle del desglose conserva el
  recuento real y añade la nota suavizada. No cambia qué municipios tienen el componente disponible.
- **Directivo no se suaviza** (decisión de César, 09-10, tras ver la primera medición): su media nacional es baja
  (32,6 %) y depende del avance de nuestro cruce con el BORME, así que tirar hacia ella bajaba de 100 a 48 a quien
  tenía 3 de 3 por un motivo ajeno al ayuntamiento.
- **Portada**: «Liderando ahora mismo» muestra el líder de cada tramo de población (<1.000, 1.000-5.000,
  5.000-20.000, 20.000-100.000, >100.000) en una fila compacta con nombre y nota, y mantiene el enlace al ranking. A
  igual nota sale el que tiene más contratos, con «+n» si hay más empatados.

**Lo que no cambia**: pesos, componentes, la regla «no disponible no es 0», el mínimo de 4 componentes y el
percentil de actividad (se sigue calculando entre todos los municipios del tramo, estén o no en el ranking).

**Decisiones de César (09-10-2026)**, con las mediciones delante: umbral **20** (se midió primero con 10: quitaba los
casos de 3-4 contratos, pero dejaba en el top 20 nacional a Fuendetodos con 13, Griegos con 15 y Soportújar con
19); el umbral cuenta **formales + menores** (contar solo formales no iguala el reparto entre comunidades y deja
fuera a ciudades cuyos formales no tenemos asignados por un problema de nombre en PLACE: San Vicente del Raspeig y
Las Rozas tienen 0 formales y 2.192 y 517 menores); y suavizado solo en adjudicatario.

**Medición** sobre la copia real de producción del **09-10-2026** (tablas completas en
`INDICE_TRANSPARENCIA_V2_1_MEDICION.md`, que incluye como referencia la alternativa «B», umbral contando solo
contratos formales):

| | v2 | v2.1 (umbral 20) |
|---|---:|---:|
| Municipios con nota | 8.083 | 8.083 |
| En el ranking | 8.083 | 3.563 |
| «Muestra pequeña» | — | 4.520 (55,9 %; 2,67 M hab.) |
| Mediana de los que están en el ranking | 72,8 | 78,3 |
| Con 90 o más | 81 | 41 |

- **Umbral de referencia**: con 5 quedarían fuera 3.028 (37,5 %); con 10, 3.767 (46,6 %); con 20, 4.520 (55,9 %).
  Con 20 sale el 79 % de los municipios de menos de 1.000 hab., el 32 % de los de 1.000-5.000, el 6 % de los de
  5.000-20.000, 5 de 20.000-100.000 y ninguno de más de 100.000.
- **Efecto desigual por comunidad** en los de menos de 1.000 hab.: siguen en el ranking el 5 % de los de Castilla y
  León (106 de 2.007) y el 3 % de Navarra (4 de 155), frente al 53 % de Cataluña y el 62 % de la Comunitat
  Valenciana. Refleja cuántos contratos tenemos de cada sitio (los registros autonómicos traen más menores), no solo
  cuánto contratan. El top 20 de ese tramo tiene 19 municipios catalanes.
- **Top nacional**: Girona 93,1, Lleida 92,5, Aguilar de la Frontera 92,1, Duesaigües 91,9, Vitoria-Gasteiz 91,8...
  El municipio con menos contratos del top 20 tiene 29 (Fígols i Alinyà). Cellorigo (4 contratos) queda en 88,8
  como «muestra pequeña».
- **Líderes por tramo**: Duesaigües 91,9 (<1.000), Toques 91,6 (1.000-5.000), Aguilar de la Frontera 92,1
  (5.000-20.000), Calvià 91,2 (20.000-100.000), Girona 93,1 (>100.000).
- **Capitales de provincia**: las 50 siguen en el ranking. Sus notas no cambian (entre −0,1 y +0,1); el puesto
  mejora por el acortamiento de la lista y, entre los mismos municipios, el suavizado las mueve una mediana de −8
  puestos (de −32 a +23).
- **Suavizado por sí solo**: 2.354 municipios cambian 1 punto o más y 241 cambian 5 o más (de −1,9 a +19,4); las
  subidas grandes son de municipios con 0 de 1 o 0 de 2 en adjudicatario. Media nacional de adjudicatario: 92,0 %.

**Verificado en producción tras desplegar (09-10-2026, 16:32)**: 3.563 municipios en el ranking y 4.520 de «muestra
pequeña», igual que en la medición. Las notas de producción salen algo más altas que las de la medición local (hasta
unos 3 puntos) porque en local falta el fichero de administradores del BORME, que solo existe en el disco de
producción y sube «directivo»: Melilla 89,1 en producción frente a 86,4 en local; Logroño 90,2 frente a 88,9. Por
eso los líderes reales por tramo son Fígols i Alinyà 92,3 (29 contratos), Begur 91,7, Aguilar de la Frontera 92,1,
Calvià 91,7 y Girona 93,2. Los recuentos por umbral no dependen de ese fichero.

**Ajeno a la v2.1**: «directivo» ha bajado desde el 03-10 en los municipios con mucho histórico, porque los contratos
que entonces estaban «pendientes de buscar en el BORME» ya se han buscado y, donde no se encontró administrador,
cuentan en el denominador. En producción Melilla está en 63 (832 de 1.315; el 03-10 medía 97,7 con casi todo
pendiente) y ha dejado de liderar; Logroño, en 59. Pasa igual con la fórmula de la v2.

## Comparación v1 → v2 (misma copia real de producción, 25-09-2026)

Calculada sobre la misma base con el código de cada versión, **ya con el arreglo de nombres del 29-09** (depuración
de contratos ajenos + recuperación retroactiva de 61 meses, 9.986 contratos en 247 municipios):

| | v1 | v2 |
|---|---:|---:|
| Municipios con índice | 8.086 | 8.107 (+22 con población nueva, −1 Cabanes de Girona por homónimo) |
| Mediana | 80,1 | 70,4 |
| P25 / P75 | 72,3 / 88,0 | 62,2 / 78,5 |
| Máximo | 99,2 | 94,0 |
| ≥ 90 | 18,6 % | 1,4 % |
| Mayor empate | 40 municipios en 90,8 (dentro del top) | 51 en 61,1 (zona media) |
| Top 10 | empates de hasta 40 municipios | 8 notas distintas, un empate de 3 |

- Cambian de puesto 8.072 de 8.085; mediana del cambio 350 puestos. La nota baja en 7.875 (mediana −10,2 puntos),
  sobre todo por retribuciones (50 donde solo consta el alcalde) y cuentas graduadas: es el efecto buscado de
  desamontonar, no un empeoramiento real.
- "Cobertura suficiente" → "insuficiente": solo Cabanes (Girona), a propósito (homónimo, ver abajo).
- Subidas grandes: ciudades cuya actividad ya no queda por debajo de las que tenían menores conectados
  (Vitoria-Gasteiz 68,5 → 82,2) y municipios que tenían **0 contratos formales** por el fallo de nombres y ahora
  tienen los suyos: Rivas-Vaciamadrid 71,9 → 78,9 (#6.177 → #1.901), Dénia 71,7 → 75,8, El Campello 71,6 → 77,9,
  La Rinconada 73,1 → 75,9, Sant Joan d'Alacant 71,8 → 74,4, El Ejido 72,3 → 73,6.
- Bajadas grandes: municipios cuya nota de v1 se apoyaba en **contratos de otro municipio** que el arreglo ha
  retirado (Valsequillo 97,2 → 61,7, Navalmoral 85,5 → 49,4, El Cuervo 85,1 → 56,3...), y ciudades cuya actividad
  inflaban los menores conectados (Santa Cruz de Tenerife 83,7 → 71,0, Gijón 88,4 → 79,7).
- Sin cambio relevante por el arreglo: Sevilla 81,5 → 81,7, Madrid 80,7 → 77,5, Almería 79,1 → 77,9; Fuenlabrada
  87,9 → 79,7 por la corrección de actividad (sus contratos pendientes son de organismos: patronatos, empresas).
- **Efecto transitorio conocido**: los contratos recuperados entran sin directivo enriquecido, así que "directivo"
  sale 0 en los municipios recuperados (El Ejido, Rivas, Dénia...) hasta que el enriquecimiento de producción los
  procese. Les resta como mucho el 10 % de peso durante ese tiempo.

## Límites conocidos

- Contratos menores: ~55 % de cobertura con el feed de PLACE (30-09). Formato: 67 municipios clasificados.
- Municipios con el mismo nombre en dos provincias: resuelto el 30-09 con la clave compuesta municipio+provincia
  (`clave_municipio`); los 16 pares tienen cada uno sus propios datos y componentes.
- ~80 contratos formales al mes de organismos municipales sin "ayuntamiento" en el nombre, y los municipios que
  PLACE nombra distinto que la app, siguen sin asignarse hasta conectar la asignación por código DIR3.
