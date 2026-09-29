# Índice de Transparencia Dinero Público — metodología (v2)

Versión 2, 29-09-2026. La v1 (7 componentes, agosto de 2026) y su distribución real en producción están en
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

## Componentes y pesos

| Componente | Peso v2 | Peso v1 | Cómo se puntúa |
|---|---:|---:|---|
| Contratos menores publicados | **20** | — | Solo con fuente conectada. Portal municipal: publicarlos 40 + años cubiertos desde 2021 20 + frescura del último registro 20 (≤90 días 100, ≤180 70, ≤365 40, más 10) + % con adjudicatario identificado 20. Agregador regional (RPC Cataluña, API Euskadi): años y frescura **no disponibles**; nota = (40 + 20 × %adjudicatario) / 60. Sin fuente: no disponible. |
| Adjudicatario identificado | **15** | 20 | % de contratos formales (PLACE/PSCP/Euskadi/Navarra) con adjudicatario identificado. |
| Retribuciones de cargos electos | **10** | 10 (sí/no alcalde) | 100 si publica el sueldo de los concejales con nombre e importe (tabla revisada a mano, `sueldos_concejales.json`); **50 si solo consta el del alcalde** (ISPA); 0 si ni eso. No disponible solo en Ceuta/Melilla (ISPA no las cubre). |
| Formato del portal propio | **5** | — | Portal donde el ayuntamiento publica sus menores: dataset/API o fichero estructurado 100, tabla web o consulta 66, PDF con texto 33, PDF escaneado o sin listado propio (remite a PLACE) 0. Solo para los municipios clasificados a mano (conector propio + auditoría de las 29 ciudades >100.000 hab.); el resto, no disponible. |
| Actividad de publicación | **15** | 20 | Contratos **formales** por 1.000 habitantes, en percentil dentro de su tramo de población (<1.000, <5.000, <20.000, <100.000, >100.000). |
| Cuentas anuales | **10** | 15 (binario) | Según el último ejercicio rendido a rendiciondecuentas.es frente al último **exigible por ley**: al día 100, un año de retraso 50, dos o más o sin rendir 0. No disponible en País Vasco, Navarra, Ceuta y Melilla (Tribunal de Cuentas foral o no listadas). |
| Deuda viva publicada | **7,5** | 12,5 | Binario (Ministerio de Hacienda). |
| Saldo no financiero publicado | **7,5** | 12,5 | Binario (Ministerio de Hacienda). |
| Directivo identificado | **10** | 10 | % de adjudicatarios (formales + menores) con directivo/administrador identificado. |

## Por qué cada cambio respecto a la v1

- **Contratos menores (nuevo, 20 %)**: son la mayor parte del gasto contractual fragmentado y lo que menos se
  publica de forma reutilizable; la v1 no los medía. Hoy solo es calculable en el **11,5 %** de los municipios con
  índice (931 de 8.108); en el resto es no disponible hasta conectar el feed nacional de menores de PLACE. Cuando se
  conecte, un municipio con fuente y 0 contratos sí será un 0 real (ver `DATOS_PETICION_MENORES.md` §6).
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

- Contratos menores: 11,5 % de cobertura hoy. Formato: 67 municipios clasificados.
- Municipios con el mismo nombre exacto en dos provincias (hoy Torrent y Cabanes) comparten fila (clave sin
  provincia). Torrent (Valencia) y Cabanes (Castellón) no tienen población propia y no entran en el índice; en sus
  homónimos de Girona, actividad, adjudicatario, directivo y formato son no disponibles, y los demás componentes solo
  cuentan si el registro es de la misma provincia (Cabanes de Girona queda con cobertura insuficiente).
- ~80 contratos formales al mes de organismos municipales sin "ayuntamiento" en el nombre, y los municipios que
  PLACE nombra distinto que la app, siguen sin asignarse hasta conectar la asignación por código DIR3.
