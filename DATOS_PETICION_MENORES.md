# Datos para petición pública: contratos menores en España

Documento de trabajo. **Actualizado el 2026-09-30** con el feed oficial de contratos menores de PLACE ya conectado
(la versión anterior, del 28-09, contaba 1.069.237 contratos en 919 municipios). Cada cifra indica su consulta SQL
exacta o el script que la calcula (`backend/analisis_peticion_menores/`, ver Apéndice) y su alcance real.

## ⚠️ Antes de usar cualquier cifra de este documento

1. **Fuente de datos y su fecha**: copia de la base de **producción del 25-09-2026** más **todas las fuentes de
   contratos menores del repositorio** cargadas con el mismo código que usa la web (los 57 conectores municipales y
   regionales y el feed de PLACE hasta el 28-09-2026). Es el estado que tiene producción desde el despliegue del 30-09,
   salvo los refrescos diarios posteriores. No se ha usado el `ADMIN_TOKEN`.
2. **Ventana temporal**: todo lo que sigue filtra `data_adjudicacio >= '2021-09-01'` salvo que se diga lo
   contrario. Los registros anteriores ya están archivados fuera de la tabla activa (0 filas por debajo de la
   ventana), así que el filtro es sobre todo una salvaguarda.
3. **El importe mezcla bases distintas de IVA**: unas fuentes publican el importe CON IVA, otras SIN IVA, y de
   bastantes **no está verificado**. Cualquier cifra de importe "en bruto" de este documento lo dice explícitamente.
   Solo la sección 3 normaliza a una base común, y solo para las fuentes donde la base está confirmada; desde el
   30-09 eso incluye el feed de PLACE (importe sin IVA explícito), así que esa sección ya cubre casi la mitad de los
   contratos.
4. **Sigue sin ser "toda España"**: son los **4.447 municipios** (de unos 8.130) con algún contrato menor en alguna
   fuente conectada. El feed de PLACE solo recoge lo que cada ayuntamiento registra en su perfil de la Plataforma,
   que **no es obligatorio**: un municipio que no aparece puede publicar sus menores en su web o en PDF. Cataluña y
   País Vasco se cubren por sus agregadores regionales (RPC, API Euskadi); Navarra, Ceuta y Melilla no tienen ninguna
   fuente con datos.

---

## Tabla resumen

| # | Cifra | Valor | Alcance | Fuente de datos |
|---|---|---|---|---|
| 1.1 | Contratos menores indexados en la ventana de 5 años | **1.976.530** | Municipios con fuente conectada | `contratos_menors_locales`, `data_adjudicacio >= '2021-09-01'` |
| 1.2 | Importe total (bruto, bases IVA mezcladas) | **6.803.390.020,72 €** | Idem. **No usar como cifra limpia**, ver §1.2 | Idem |
| 1.3 | Municipios con al menos un contrato menor en alguna fuente | **4.447** de ~8.130 (54,7 %) | — | `COUNT(DISTINCT municipio)` |
| 1.3b | De ellos, contratos que vienen solo del feed oficial de PLACE | **849.898** contratos (43 % del total) en **3.562** municipios | Donde el municipio tiene fuente propia, del feed solo entra lo que esta no trae | `fuente = 'place-menores'` |
| 1.4 | Municipios de >20.000 hab. SIN ningún contrato menor en ninguna fuente | **44** de 430 (10 %) | Ver §1.4 | Cruce `contratos_menors_locales` × `poblacion.json` |
| 2.1 | Formatos/plataformas distintos integrados | **9 tipos** (inventario del 28-09 sobre 48 conectores; desde entonces +8 conectores y el feed, ver §2) | — | Inspección del código de cada conector |
| 2.2 | Fuentes que exigieron Playwright o ingeniería inversa de una API oculta | **13 de 48** (27 %) a 28-09 | — | Idem |
| 3.1 | Contratos con importe normalizable a base SIN IVA de forma verificada | **919.462** (46,5 % del total en ventana) | 20 de 58 fuentes con base IVA confirmada; el feed de PLACE aporta la mayoría | Ver §3 |
| 3.2 | Tramo 13.000-14.999 € (sin IVA) vs. tramo de igual anchura 11.000-12.999 € | **55.068 vs. 24.987 → 2,2 veces más** (500 € antes del umbral: 33.580 vs. 5.271 → 6,4 veces) | Solo el subconjunto normalizable (§3.1) | `analisis2.py` |
| 3.3 | Tramo 38.000-39.999 € (sin IVA) vs. tramo de igual anchura 36.000-37.999 € | **7.280 vs. 2.074 → 3,5 veces más** (1.000 € antes del umbral: 5.786 vs. 1.169 → 4,9 veces) | Idem | Idem |
| 3.4 | Municipios con mayor concentración bajo el umbral de 15.000 € (con más de 1.000 contratos) | **Pájara 25,0 %**, San Cristóbal de La Laguna 23,8 %, Arrecife 22,7 %, Ourense 22,0 %, Utrera 21,6 % | Solo fuentes normalizables | `analisis4_extra.py` |
| 4.1 | Contratos con importe 0 € o sin importe | **11.220** (0,57 %); 8.086 del feed de PLACE | — | SQL en §4 |
| 4.2 | Contratos con importe > 40.000 € bruto | **2.789** (0,14 %); **409** (0,021 %) superan incluso 48.400 € (= 40.000 € + IVA) | Mezcla bases IVA, ver §4.2 | SQL en §4 |
| 4.3 | Contratos con fecha de adjudicación vacía | **7.385** (0,37 % de la tabla) | El 82 % en 2 fuentes (Las Palmas GC y Toledo) | SQL en §4 |
| 5.1 | De las 29 ciudades >100.000 hab. que el 28-09 no tenían fuente conectada | **24 ya tienen contratos menores** (feed de PLACE o conector nuevo); sin ninguno: Oviedo, Pamplona, Dos Hermanas, Parla y León | Estado a 30-09 | §5 |

---

## 1. Cobertura actual de menores

### 1.1-1.2 Totales

```sql
SELECT COUNT(*), SUM(import_num)
FROM contratos_menors_locales
WHERE data_adjudicacio >= '2021-09-01';
```
→ **1.976.530 contratos, 6.803.390.020,72 € en bruto.**

**El importe NO es una cifra limpia.** Es la suma directa de `import_num` de las 55 fuentes con filas en la ventana
(de 58 conectadas; 3 tienen la fecha vacía en el 100 % de sus registros, ver §4.3), sin normalizar IVA: mezcla
contratos publicados con IVA, sin IVA, y de algunas fuentes no se sabe. Además incluye 287 importes imposibles del
feed de PLACE (hasta 71,5 M€, ver §4.2). No se puede dar aquí un "importe total nacional" fiable; la sección 3 da un
importe limpio para el 46,5 % de los contratos.

Otros datos del mismo corte:
- Filas totales en la tabla (incluida cualquier fecha): 1.983.915.
- Filas con fecha anterior a 2021-09-01: **0** (archivadas fuera de esta tabla).
- Filas con fecha vacía: 7.385, ver §4.3.
- Municipios con al menos 1 fila en ventana: **4.447**.

### 1.3 Desglose por fuente

```sql
SELECT fuente, COUNT(*) n, SUM(import_num) importe, COUNT(DISTINCT municipio) n_municipios,
       MIN(data_adjudicacio) desde, MAX(data_adjudicacio) hasta
FROM contratos_menors_locales
WHERE data_adjudicacio >= '2021-09-01'
GROUP BY fuente ORDER BY n DESC;
```

| Fuente | Contratos | Municipios | Desde | Hasta |
|---|---:|---:|---|---|
| **Feed oficial de menores de PLACE** (toda España salvo Cataluña y País Vasco) | **849.898** | **3.562** | 2021-09-01 | 2026-09-28 |
| RPC Barcelona | 341.726 | 264 | 2021-09-01 | 2028-08-28¹ |
| API Euskadi | 178.221 | 138 | 2021-09-01 | 2029-03-09¹ |
| RPC Tarragona | 149.739 | 160 | 2021-09-01 | 2029-09-18¹ |
| RPC Girona | 112.136 | 167 | 2021-09-01 | 2026-12-23¹ |
| RPC Lleida | 48.962 | 152 | 2021-09-01 | 2027-12-20¹ |
| Gijón | 37.226 | 1 | 2021-09-01 | 2026-09-25 |
| Madrid capital | 27.959 | 1 | 2021-09-01 | 2026-08-28 |
| Murcia capital | 26.280 | 1 | 2022-01-01 | 2025-12-30 |
| Alcalá de Henares | 15.070 | 1 | 2021-09-03 | 2026-07-31 |
| Palma | 13.645 | 1 | 2021-10-01 | 2026-03-31 |
| Cartagena (Governalia) | 13.560 | 1 | 2022-06-25 | 2025-12-27 |
| Valladolid | 11.392 | 1 | 2021-09-01 | 2026-06-30 |
| A Coruña | 11.373 | 1 | 2021-09-01 | 2026-03-30 |
| València capital | 10.693 | 1 | 2021-09-01 | 2026-09-25 |
| San Cristóbal de La Laguna | 10.596 | 1 | 2021-09-01 | 2025-12-29 |
| Lorca | 10.451 | 1 | 2024-10-01 | 2026-04-01 |
| Pontevedra | 9.401 | 1 | 2023-05-25 | 2026-09-24 |
| Fuenlabrada | 8.436 | 1 | 2021-09-02 | 2026-06-24 |
| Alicante | 8.140 | 1 | 2021-09-01 | 2026-06-25 |
| Santiago de Compostela | 7.986 | 1 | 2021-09-01 | 2026-06-30 |
| Vigo | 6.631 | 1 | 2021-09-10 | 2026-09-23 |
| Burgos | 6.061 | 1 | 2021-09-01 | 2026-06-30 |
| Málaga | 4.948 | 1 | 2021-10-01 | 2026-04-01 |
| Lugo | 4.519 | 1 | 2021-09-01 | 2025-09-18 |
| Castelló (Governalia) | 4.407 | 1 | 2022-06-10 | 2026-09-14 |
| Alzira (Governalia) | 3.825 | 1 | 2022-06-21 | 2026-09-08 |
| Santa Cruz de Tenerife | 3.785 | 1 | 2022-01-04 | 2025-12-31 |
| Torrejón de Ardoz | 3.535 | 1 | 2022-04-01 | 2026-06-30 |
| Salamanca | 2.951 | 1 | 2021-09-01 | 2024-12-26 |
| Ames | 2.856 | 1 | 2022-01-01 | 2025-07-01 |
| Sax (Governalia) | 2.710 | 1 | 2022-06-21 | 2026-09-22 |
| Mula | 2.537 | 1 | 2022-01-19 | 2026-03-26 |
| Móstoles | 2.448 | 1 | 2021-09-01 | 2026-06-25 |
| Fuente Álamo | 2.398 | 1 | 2022-04-07 | 2027-12-26¹ |
| Cartagena (portal propio) | 2.352 | 1 | 2026-01-07 | 2026-09-23 |
| Molina de Segura | 1.774 | 1 | 2022-01-04 | 2025-12-30 |
| Almería | 1.765 | 1 | 2021-10-13 | 2026-06-26 |
| Getafe | 1.664 | 1 | 2022-05-20 | 2026-09-22 |
| Ciudad Real | 1.412 | 1 | 2025-01-27 | 2026-04-28 |
| Ferrol | 1.397 | 1 | 2021-09-03 | 2026-09-23 |
| Sevilla | 1.229 | 1 | 2021-09-06 | 2026-08-28 |
| Torre Pacheco | 1.215 | 1 | 2023-03-16 | 2026-09-11 |
| Zaragoza | 1.085 | 1 | 2021-09-01 | 2026-09-21 |
| Ibi (Governalia) | 963 | 1 | 2022-11-14 | 2026-09-22 |
| Cádiz | 943 | 1 | 2023-02-06 | 2024-04-01 |
| Torrent | 893 | 1 | 2021-09-01 | 2026-06-29 |
| Xirivella (Governalia) | 815 | 1 | 2022-06-22 | 2026-05-21 |
| Vilamarxant (Governalia) | 784 | 1 | 2022-08-10 | 2026-09-20 |
| San Pedro del Pinatar | 755 | 1 | 2022-01-01 | 2025-01-01 |
| Lorquí | 307 | 1 | 2021-09-09 | 2026-07-07 |
| Santa Brígida (Governalia) | 301 | 1 | 2022-08-03 | 2026-08-28 |
| Leganés | 254 | 1 | 2021-09-07 | 2026-07-30 |
| Telde | 93 | 1 | 2025-01-29 | 2025-12-29 |
| Badajoz | 28 | 1 | 2022-08-25 | 2024-09-10 |

¹ Fechas de adjudicación posteriores a hoy: vienen así del dato de origen (fecha futura de formalización o error
de captura). No se han corregido a mano.

**El feed de PLACE no duplica a las fuentes propias**: donde el municipio ya tiene conector, del feed solo entra lo
que ese conector no trae (mismo adjudicatario, importe compatible con o sin IVA y fecha ±7 días; 31 días para
Governalia, que publica fecha de publicación y no de adjudicación; por trimestre para Málaga). Se descartaron
**66.009** contratos del feed por estar ya en la fuente propia. Detalle en `LIMITACIONES_COBERTURA.md`.

El feed es escaso al principio de la ventana (6.237 contratos en sep-dic 2021, unos 81.600 en 2022) y se generaliza
desde 2023 (~190.000-225.000 al año): las cifras por año del feed no miden la actividad real de 2021-2022.

**Tres fuentes conectadas NO aparecen en esta tabla** porque el 100 % de sus filas tienen fecha vacía: **Las Palmas
de Gran Canaria** (3.145 registros), **Toledo** (2.899) y **Arona** (432). Ver §4.3.

### Desglose por comunidad autónoma

`analisis4_extra.py` (agrupa la columna `provincia` por comunidad con `COMUNIDAD_AUTONOMA_POR_PROVINCIA` de
`app.py`; "municipios INE" = municipios de esa comunidad en `poblacion.json`):

| CCAA | Contratos | Municipios con datos | Municipios (INE) |
|---|---:|---:|---:|
| Cataluña (RPC) | 652.563 | 743 | 947 |
| Comunitat Valenciana | 222.799 | 435 | 540 |
| País Vasco (API Euskadi; Zalla por el feed de PLACE) | 181.349 | 139 | 251 |
| Andalucía | 173.479 | 547 | 785 |
| Castilla-La Mancha | 157.471 | 639 | 917 |
| Comunidad de Madrid | 111.211 | 118 | 178 |
| Región de Murcia | 100.464 | 37 | 45 |
| Galicia | 79.271 | 177 | 313 |
| Canarias | 78.304 | 79 | 88 |
| Castilla y León | 68.151 | 513 | 2.242 |
| Asturias | 52.024 | 61 | 77 |
| Illes Balears | 27.061 | 47 | 67 |
| Aragón | 24.832 | 464 | 731 |
| Extremadura | 24.547 | 325 | 387 |
| Cantabria | 14.192 | 76 | 101 |
| La Rioja | 8.812 | 48 | 174 |
| **Navarra** | **0** | **0** | 270 |
| **Ceuta y Melilla** | **0** | **0** | 2 |

**Navarra, Ceuta y Melilla no tienen ningún contrato menor en ninguna fuente**: Navarra publica en su propio Portal
de Contratación (no en PLACE) y no tiene un conjunto de datos de menores conectado; Ceuta y Melilla no aparecen en el
feed. Castilla y León y La Rioja tienen una cobertura muy baja por número de municipios (23 % y 28 %): son
comunidades de municipios muy pequeños, muchos de los cuales no registran ningún menor en PLACE en cinco años.

### 1.4 Municipios de más de 20.000 hab. sin ningún contrato menor

**Metodología** (`analisis3_cobertura20k.py`):
1. Municipios de `poblacion.json` (INE, Padrón) con población ≥ 20.000 hab.: **430**.
2. Cataluña y País Vasco se tratan como **"cubiertos por agregador regional"** en bloque.
3. Para el resto, un municipio cuenta como "con fuente" si tiene al menos un contrato en `contratos_menors_locales`
   (conector propio o feed de PLACE).

**Resultado: 44 de 430 municipios (10 %) no tienen ningún contrato menor en ninguna fuente** (el 28-09 eran 303 de
426). Por comunidad: Andalucía 12, Comunidad de Madrid 5, Comunitat Valenciana 5, Navarra 4, Canarias 4, Galicia 3,
Región de Murcia 3, Asturias 2, Castilla y León 2, Illes Balears 2, Ceuta 1 y Melilla 1.

| Municipio | Población | CCAA |
|---|---:|---|
| Oviedo | 223.968 | Asturias |
| Pamplona/Iruña | 209.094 | Navarra |
| Dos Hermanas | 142.519 | Andalucía |
| Parla | 137.471 | Comunidad de Madrid |
| León | 123.446 | Castilla y León |
| Melilla | 86.780 | Melilla |
| Orihuela | 84.560 | Comunitat Valenciana |
| Ceuta | 83.595 | Ceuta |
| Santa Lucía de Tirajana | 78.584 | Canarias |
| Avilés | 75.517 | Asturias |
| Collado Villalba | 67.274 | Comunidad de Madrid |
| Ponferrada | 63.186 | Castilla y León |
| Linares | 55.633 | Andalucía |
| Eivissa | 55.337 | Illes Balears |
| Rincón de la Victoria | 52.454 | Andalucía |
| Adeje | 50.021 | Canarias |
| Alhaurín de la Torre | 45.066 | Andalucía |
| Antequera | 41.849 | Andalucía |
| Tudela | 38.903 | Navarra |
| Oleiros | 38.793 | Galicia |
| Los Palacios y Villafranca | 38.761 | Andalucía |
| Villajoyosa | 37.449 | Comunitat Valenciana |
| Galapagar | 36.758 | Comunidad de Madrid |
| Maó | 30.666 | Illes Balears |
| Jávea | 30.642 | Comunitat Valenciana |
| Mutxamel | 28.621 | Comunitat Valenciana |
| Ribeira | 27.102 | Galicia |
| Novelda | 26.606 | Comunitat Valenciana |
| Ciempozuelos | 26.350 | Comunidad de Madrid |
| Caravaca de la Cruz | 26.126 | Región de Murcia |
| Almonte | 24.864 | Andalucía |
| Martos | 24.462 | Andalucía |
| Teguise | 24.027 | Canarias |
| Las Gabias | 23.584 | Andalucía |
| Valle de Egüés/Eguesibar | 22.825 | Navarra |
| Las Torres de Cotillas | 22.676 | Región de Murcia |
| Tías | 21.613 | Canarias |
| Burlada/Burlata | 21.280 | Navarra |
| O Porriño | 20.965 | Galicia |
| Loja | 20.951 | Andalucía |
| Baza | 20.587 | Andalucía |
| Humanes de Madrid | 20.500 | Comunidad de Madrid |
| Palma del Río | 20.438 | Andalucía |
| Los Alcázares | 20.408 | Región de Murcia |

**"Sin ningún contrato" no significa "no publica"**: estos 44 no registran menores en PLACE ni tienen conector
propio en este proyecto. Varios de ellos pueden publicarlos en su web (Oviedo y León tienen consulta propia, ver §5).

---

## 2. Fragmentación de formatos

> **Estado a 30-09**: este inventario es del **28-09** (48 conectores). Desde entonces se han añadido 8 conectores
> municipales (Gijón: dataset abierto TSV; Málaga: CKAN con XLSX trimestrales; Almería: XLSX/PDF anual; Sevilla: PDF
> mensual; Torrejón: XLSX/PDF trimestral; Santa Cruz de Tenerife: PDF anual; Cádiz: PDF 2023; Telde: ODS 2025), Alzira
> ya aporta datos, y el **feed oficial de menores de PLACE** (ATOM/CODICE en ZIP mensuales, con jerarquía oficial del
> órgano y NIF del adjudicatario), que es el único conjunto de datos estructurado y de ámbito nacional. Las cifras de
> esta sección no se han recalculado para esos 10.

Este apartado **no sale de una consulta SQL**: es un inventario de las técnicas usadas para construir cada uno de
los 48 conectores con datos reales (más 1, Alzira, que figura en el código pero no ha producido ninguna fila
todavía), obtenido inspeccionando el código fuente de cada uno (`backend/actualizar_contratos_menores_*.py`) y
`LIMITACIONES_COBERTURA.md`. Un mismo conector puede combinar más de una técnica (p. ej., un XLSX cuyo enlace de
descarga solo aparece tras interactuar con la página).

| Tipo de origen | Nº de fuentes (de 48) | Ejemplos |
|---|---:|---|
| API pública propia (documentada) | 6 | RPC Cataluña (4 provincias), API Euskadi, y probablemente Zaragoza |
| API oculta tipo "Governalia" (sin documentar, localizada con Playwright, después se consume con peticiones HTTP directas) | 7 | Cartagena, Ibi, Sax, Vilamarxant, Castelló, Xirivella y Santa Brígida, todas sobre la misma plataforma (Alzira usa la misma técnica, pero no tiene datos y no cuenta entre las 48) |
| PDF (texto o tabla) | ≥7 | Alcalá de Henares, Burgos, Móstoles, Badajoz, Salamanca, Vigo, Lugo |
| XLSX/XLS | ≥8 | Palma, Leganés, Toledo, Ciudad Real, Fuenlabrada, Valladolid, La Laguna, Torrent |
| CSV / portal de datos abiertos (tipo Socrata / `datos.madrid.es`) | ≥3 | Madrid capital, Getafe, Las Palmas GC |
| ODS | ≥2 | Alicante, A Coruña |
| Otros / mixtos (varios documentos, varias eras de formato dentro de la misma fuente) | resto | Murcia (agrupa 20+ municipios con formatos distintos entre sí), Torrent (mezcla `.xlsx` y una carpeta legacy) |

**Fuentes que exigieron Playwright (navegador real, no una petición HTTP simple) para descargar el dato, cada
vez que se actualiza**: Arona, Badajoz, La Laguna, Las Palmas de Gran Canaria, Salamanca, Torrent — **6 de 48**.

**Fuentes que exigieron ingeniería inversa de una API oculta** (localizar con Playwright la llamada de red real
detrás de un botón o un iframe, una sola vez, para después consumirla con peticiones HTTP directas): las 7
fuentes "Governalia" con datos de la tabla de arriba, más el hallazgo del dataset abierto detrás de las fichas de
`opendata.gijon.es` (ese último es de sueldos de concejales, no de menores, se menciona solo como ejemplo de la
misma técnica). **7 de 48** para menores.

En total, **13 de las 48 fuentes (27 %) no tenían ninguna forma de descarga directa y documentada**: hubo que
automatizar un navegador, interceptar tráfico de red, o ambas cosas.

**Casos de histórico que desapareció o cambió por un cambio de portal** (documentados en
`LIMITACIONES_COBERTURA.md`):
- **Cartagena**: el municipio tiene DOS fuentes con datos que se solapan un 62 % pero son bases de datos
  distintas — un espejo de PLACE vía Governalia (2022-2025) y el portal propio del ayuntamiento (desde
  2026-01-07). No es que el histórico haya desaparecido, es que la fuente cambió de sistema y el proyecto
  mantiene ambas por separado, con notas de que la base de importe difiere (una con IVA, otra sin IVA).
- **Guadalajara y Mérida**: la fuente propia de menores de ambos ayuntamientos deja de publicar en 2018 — desde
  entonces remiten (según su propio texto) a la Plataforma de Contratación del Estado. Mismo patrón exacto en
  Elche, Albacete y Ponferrada. La Plataforma **sí** tiene un conjunto de datos abierto de contratos menores
  (ver §5.1), pero la ley solo obliga a publicarlos, no a hacerlo en ese formato estructurado: cada ayuntamiento
  decide si registra ahí cada contrato, si cuelga un documento suelto en su perfil o si no aparece nada.

---

## 3. Fraccionamiento (concentración de importes justo por debajo de los umbrales legales)

### Aviso de normalización de IVA — léase antes de estas cifras

Los umbrales de la Ley 9/2017 (15.000 € servicios/suministros, 40.000 € obras) se aplican **sin IVA**. De las 58
fuentes conectadas, **20 tienen la base de IVA verificada** (lista sincronizada con `_FUENTES_CM_SIN_IVA` de
`app.py`):

- **Confirmadas SIN IVA** (17): el **feed oficial de menores de PLACE** (importe adjudicado sin IVA,
  `TaxExclusiveAmount`), Torre Pacheco, las 8 fuentes Governalia (Cartagena, Ibi, Sax, Vilamarxant, Castelló,
  Xirivella, Santa Brígida, Alzira), València capital, Alicante, Leganés, Torrent, La Laguna, Sevilla y Torrejón.
- **Confirmadas CON IVA** (3, se dividen entre 1,21 antes de calcular): Mula, San Pedro del Pinatar y Cartagena
  (portal propio).
- **Excluidas por base no verificada** (38): los 4 RPC de Cataluña, Euskadi, Madrid capital, Murcia capital, Gijón,
  Málaga y el resto de conectores municipales.

Esto deja **919.462 contratos analizables sobre 1.976.530 (46,5 %)** en 3.553 municipios. El feed de PLACE aporta la
gran mayoría, así que la muestra ya es de ámbito casi nacional, **pero no incluye Cataluña ni el País Vasco** (sus
agregadores no confirman la base de IVA). El 28-09 esta sección cubría solo 60.930 contratos (5,7 %) y las
proporciones eran otras (3,2x y 2,7x): no mezclar cifras de las dos versiones.

```
python backend/analisis_peticion_menores/analisis2.py <copia de cache.db>
-- equivale a: SELECT fuente, import_num FROM contratos_menors_locales
--   WHERE data_adjudicacio >= '2021-09-01' AND fuente IN (<las 20 de arriba>) AND import_num > 0
-- (importe sin IVA fila a fila; los tramos se agrupan en Python)
```

### Umbral de 15.000 € (servicios/suministros)

| Tramo (sin IVA) | Nº contratos |
|---|---:|
| 11.000 – 12.999 € (tramo de control, igual anchura) | 24.987 |
| **13.000 – 14.999 € (justo por debajo del umbral)** | **55.068** |
| 15.000 – 16.999 € (justo por encima) | 3.838 |

**El tramo justo debajo del umbral tiene 2,2 veces más contratos que el tramo de control de igual anchura**, y justo
por encima caen 14 veces menos (3.838). Ventana más estrecha (500 € de ancho):

| Tramo estrecho (sin IVA) | Nº contratos |
|---|---:|
| 12.500 – 12.999 € | 5.271 |
| **14.500 – 14.999 € (500 € antes del umbral)** | **33.580** |
| 15.000 – 15.499 € | 1.594 |

**En los 500 € anteriores al umbral hay 6,4 veces más contratos que en los 500 € equivalentes 2.000 € más abajo.**

### Umbral de 40.000 € (obras)

| Tramo (sin IVA) | Nº contratos |
|---|---:|
| 36.000 – 37.999 € (tramo de control) | 2.074 |
| **38.000 – 39.999 € (justo por debajo del umbral)** | **7.280** |
| 40.000 – 41.999 € (justo por encima) | 42 |

**3,5 veces más contratos justo debajo del umbral que en el tramo de control**, y casi nada justo encima (42).
Ventana estrecha:

| Tramo estrecho (sin IVA) | Nº contratos |
|---|---:|
| 37.000 – 37.999 € | 1.169 |
| **39.000 – 39.999 € (1.000 € antes del umbral)** | **5.786** |
| 40.000 – 40.999 € | 31 |

**No se ha separado obras de servicios/suministros** (el campo `tipus_contracte` no está normalizado entre fuentes):
se muestran los dos umbrales por separado, sin asumir qué contratos son de qué tipo. Parte de los contratos de
38.000-39.999 € pueden ser de servicios por encima de su propio límite (15.000 €), que es otra anomalía distinta.

### Municipios con mayor concentración justo bajo el umbral de 15.000 €

`analisis4_extra.py`: % de sus contratos normalizables (con importe positivo) en la franja 13.000-14.999 € sin IVA,
entre los **223 municipios con más de 1.000 contratos** normalizables:

| Municipio | % en la franja | Contratos en la franja | Total normalizable |
|---|---:|---:|---:|
| Pájara (Las Palmas) | **25,0 %** | 252 | 1.010 |
| San Cristóbal de La Laguna | **23,8 %** | 2.551 | 10.722 |
| Arrecife | 22,7 % | 430 | 1.896 |
| Ourense | 22,0 % | 355 | 1.613 |
| Utrera | 21,6 % | 274 | 1.268 |
| Torrent | 20,5 % | 272 | 1.328 |
| Puerto del Rosario | 20,4 % | 461 | 2.257 |
| Mérida | 19,4 % | 221 | 1.141 |
| Santa Cruz de Tenerife | 17,0 % | 306 | 1.798 |
| Arroyomolinos (Madrid) | 16,5 % | 170 | 1.029 |

Con umbrales más bajos de tamaño aparecen porcentajes mucho mayores sobre bases pequeñas (Antigua, 52,0 % de 325;
Cartes, 51,4 % de 107): no se incluyen en la tabla porque con pocos contratos el porcentaje es inestable.

**Cautela**: un porcentaje alto no prueba fraccionamiento en un municipio concreto (puede haber servicios que
cuestan eso de forma natural); lo que es difícil de explicar sin fraccionamiento es la **forma agregada** de la
distribución (el salto antes del umbral y el hueco después). No se listan importes ni adjudicatarios individuales.

---

## 4. Anomalías de publicación

### 4.1 Importe 0 € o sin importe

```sql
SELECT COUNT(*) FROM contratos_menors_locales
WHERE data_adjudicacio >= '2021-09-01' AND (import_num IS NULL OR import_num = 0);
```
→ **11.220 contratos (0,57 % del total en ventana)**. Por fuente (top):

| Fuente | Nº | % de esa fuente |
|---|---:|---:|
| Feed de PLACE | 8.086 | 0,95 % |
| Móstoles | 1.010 | 41,3 % |
| Cartagena (Governalia) | 992 | 7,3 % |
| Mula | 679 | 26,8 % |
| RPC Barcelona | 144 | 0,04 % |
| API Euskadi | 93 | 0,05 % |

Del feed de PLACE, 3.626 contratos (antes de descartar duplicados) **no traen importe en origen** (se guardan con 0 €, misma convención que el resto
de fuentes) y el resto trae 0 € explícito. **Móstoles (41,3 %) y Mula (26,8 %)** siguen destacando: entre uno de
cada dos y uno de cada cuatro contratos publicados no tiene importe. No se ha investigado la causa.

### 4.2 Importes por encima del máximo legal

```sql
SELECT COUNT(*) FROM contratos_menors_locales WHERE data_adjudicacio >= '2021-09-01' AND import_num > 40000;
SELECT COUNT(*) FROM contratos_menors_locales WHERE data_adjudicacio >= '2021-09-01' AND import_num > 48400;
```
→ **2.789 contratos con importe BRUTO > 40.000 €** (0,14 %). Mezcla bases de IVA: un contrato de 40.001 € con IVA
son ~33.000 € sin IVA, legal como obra. Siendo generosos con el IVA (40.000 € × 1,21 = 48.400 €), quedan **409
(0,021 %)** que no pueden ser un contrato menor legal con ninguna base:

| Fuente | Nº > 48.400 € | Importe máximo |
|---|---:|---:|
| Feed de PLACE | 210 | 71.540.000,00 € |
| Murcia capital | 92 | 2.297.456,25 € |
| API Euskadi | 59 | 8.447.000,00 € |
| Madrid capital | 21 | 231.251,57 € |
| Almería | 6 | 753.043,00 € |
| Vilamarxant (Governalia) | 5 | 3.679.090,00 € |
| Resto (12 fuentes) | 16 | 6.000.000,00 € (Cartagena, Governalia) |

**El feed de PLACE es un caso aparte, porque su importe es SIN IVA**: ahí basta con superar 40.000 € para ser
imposible como contrato menor (máximo legal de obras). Son **287** contratos del feed, hasta 71,5 M€ ("Reparación de
la Vía Verde", El Viso del Alcor) o 28,9 M€ (Cullera). La web los muestra tal cual con un aviso automático en la fila
("Importe sin IVA por encima del máximo legal de cualquier contrato menor..."), igual que los de Euskadi por encima
de 100.000 € y una lista cerrada de casos puntuales de otras fuentes. Son errores o anomalías **de origen**, no del
proyecto, y están señalados en la propia web.

### 4.3 Fechas vacías

```sql
SELECT COUNT(*) FROM contratos_menors_locales WHERE data_adjudicacio = '' OR data_adjudicacio IS NULL;
```
→ **7.385 de 1.983.915 filas totales (0,37 %)**, sin cambios respecto al 28-09 (el feed de PLACE trae fecha en todos
sus contratos):

| Fuente | Nº sin fecha | % de esa fuente |
|---|---:|---:|
| Las Palmas de Gran Canaria | 3.145 | **100 %** |
| Toledo | 2.899 | **100 %** |
| Fuente Álamo | 801 | 25,0 % |
| Arona | 432 | **100 %** |
| Ciudad Real | 108 | 7,1 % |

Las Palmas GC, Toledo y Arona no tienen fecha en NINGUNA fila de su fuente propia: esos contratos quedan fuera de
cualquier cifra filtrada por ventana. Desde el 30-09, Las Palmas GC y Toledo sí aparecen en las cifras por los
contratos que registran en el feed de PLACE.

---

## 5. Las 29 ciudades de más de 100.000 hab. sin fuente conectada: qué publican de verdad

> **Estado a 30-09**: de estas 29 ciudades, **24 ya tienen contratos menores en la base** (8 por conector propio
> nuevo -- Gijón, Málaga, Almería, Sevilla, Torrejón, Santa Cruz de Tenerife, Cádiz y Telde -- y el resto, o además,
> por el feed de PLACE). **Siguen sin ninguno: Oviedo, Pamplona, Dos Hermanas, Parla y León.** La investigación de
> abajo es del 28-09 y se mantiene como estaba: describe qué publica cada ayuntamiento en su web, que no cambia por
> haber conectado el feed. §5.1 decía que el proyecto "no usa" el feed: ya lo usa desde el 30-09.

Investigación hecha el **28-09-2026**, solo lectura: portal de transparencia y sede de cada ayuntamiento, buscador
web (con `site:` o dominio del ayuntamiento cuando hacía falta) y, cuando la página era dinámica, un navegador real
(Playwright). **Son 29, no 30**: en la lista de §1.4, el siguiente municipio (Las Rozas, 99.037 hab.) ya baja de
100.000.

Criterio: **"No localizado"** solo se escribe después de buscar de verdad (portal, sede y buscador web) sin
encontrar nada. **No significa "no publica"**. Si el ayuntamiento dice que publica en la Plataforma de Contratación
del Sector Público (PLACE) y no tiene listado propio, se pone **"Remite a PLACE"**. Cada URL de la tabla se abrió o
descargó el 28-09-2026, salvo cuando se indica que no se pudo.

### 5.1 Hallazgo transversal: el feed oficial de contratos menores de PLACE

Hacienda publica un conjunto de datos específico: **"Contratos menores publicados en los perfiles del contratante
ubicados en la PLCSP"**
([ficha](https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/ContratosMenores.aspx)). Es un
ATOM/CODICE que se actualiza a diario, con un ZIP por año desde **2018** y un ZIP por mes para el año en curso:
`https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1143/contratosMenoresPerfilesContratantes_AAAAMM.zip`.
Cada entrada trae expediente, órgano, tipo, importe sin y con IVA, fecha de adjudicación, número de ofertas y
adjudicatario con NIF.

**Este proyecto no lo usa** (`grep sindicacion_1143` en `backend/` sin resultados). Hasta este
hallazgo, §2 y `LIMITACIONES_COBERTURA.md` decían que PLACE "no expone menores de forma sistemática"; §2 ya está
corregido (`LIMITACIONES_COBERTURA.md` no). Se
descargó y escaneó el ZIP de **agosto de 2026** (16,8 MB, 57 ficheros). Estos son los contratos únicos (por `<id>`)
de órganos **municipales** de cada ciudad:

| Con entradas en ago-2026 | Contratos únicos |
|---|---:|
| Alcobendas (Concejalías 40, JGL 17, sociedades municipales 63) | 120 |
| Almería (Patronato de Deportes 48, JGL 24, otros 4) | 76 |
| Huelva (varias concejalías) | 60 |
| Torrejón de Ardoz | 55 |
| Marbella | 50 |
| Málaga (concejalías y distritos) | 35 |
| Alcorcón | 31 |
| Albacete | 22 |
| Santa Cruz de Tenerife (distritos y organismos) | 20 |
| Santander (JGL 10, Deportes 7) | 17 |
| Córdoba (JGL 5, entes 10) | 15 |
| Sevilla ("Órganos Directivos") | 13 |
| Cádiz (solo sociedades/institutos municipales, 0 de la JGL) | 7 |
| Logroño | 6 |
| Jaén (solo 2 patronatos municipales) | 4 |
| Roquetas de Mar | 4 |
| Rivas-Vaciamadrid (publica "Rivas Vaciamadrid", sin guion) | 3 |
| Granada | 2 |
| **Cero entradas**: Gijón, Elche, Oviedo, Jerez, Pamplona (Navarra usa su propio portal), Dos Hermanas, Parla, Algeciras, León, Ourense, Telde | 0 |

**Límites de esta muestra**: es **un solo mes**. No se ha comparado con la fuente propia de cada ayuntamiento, así
que no se sabe qué fracción de sus menores sube cada uno a PLACE. Es posible, por ejemplo, que Sevilla suba muy
pocos, porque su PDF mensual propio es mucho más largo. Aun así, para **Marbella, Alcorcón, Albacete, Huelva,
Alcobendas y Roquetas** es la única vía actual con datos. El ZIP y el script (`scan_place_muni.py`) están en el
directorio temporal de esta investigación, fuera del repo.

### 5.2 Tabla por municipio

Leyenda de "Masiva": **Sí** = un fichero o una API que da todo el histórico de una vez. **Por periodo** = un fichero
por mes, trimestre o año, que hay que recoger uno a uno. **No** = consulta interactiva o documentos sueltos.

| # | Municipio | ¿Publica listado propio? | Formato | Masiva | Desde · periodicidad | URL verificable | Feed PLACE ago-26 |
|---|---|---|---|---|---|---|---:|
| 1 | Sevilla | **Sí** | PDF con texto (incluye CIF, fecha, importes sin IVA y el IVA aparte) | Por periodo | Páginas por año 2012-2026 (2021 verificado) · **mensual**, último agosto de 2026 | [contratos/2025](https://www.sevilla.org/servicios/contratacion/contratos/2025) · [ej. enero 2025](https://www.sevilla.org/servicios/contratacion/contratos/2025/menores-enero-2025.pdf) | 13 |
| 2 | Málaga | **Sí** | XLSX + PDF (y ODS desde 3T-2025), un dataset CKAN por trimestre | **Sí** (API CKAN) | 1T-2016 → 2T-2026 (42 datasets) · trimestral | [API](https://datosabiertos.malaga.eu/api/3/action/package_search?q=title:%22contratos%20menores%22%20ayuntamiento&rows=100) · [2T-2026](https://datosabiertos.malaga.eu/dataset/contratos-menores-2o-trimestre-2026-ayuntamiento-de-malaga) | 35 |
| 3 | Córdoba | **Sí** | PDF trimestral con texto (NIF, adjudicatario, importes, fecha, decreto); XLS/ODS solo en 2023, 1T y 3T de 2024 y 2T-2026 | Sí (API CKAN, un solo dataset) | 1T-2021 → 2T-2026 · trimestral | [dataset](https://datosabiertos.cordoba.es/ckan/api/3/action/package_show?id=contratacion-administrativa-contratos-menores) | 15 |
| 4 | Gijón | **Sí** | TSV / Excel / API OpenDataSoft, dataset único con histórico (CIF, importes sin IVA y el IVA aparte, fecha, procedimiento, órgano) | **Sí** | 2018 → hoy; **63.978 filas**, última adjudicación el 25-09-2026 · casi diaria | [TSV](https://opendata.gijon.es/descargar.php?id=725&tipo=TSV) · [Observa](https://observa.gijon.es/explore/dataset/contratos-menores-adjudicados/) | 0 |
| 5 | Elche | Remite a PLACE | — | — | La página de menores redirige al perfil PLACE (ya documentado en `LIMITACIONES_COBERTURA.md`); según prensa, sube las relaciones a la pestaña "Documentos" del perfil | [perfil](https://www.elche.es/perfil-del-contratante-del-ajuntament-delx/mesa-de-contratacion/) | 0 |
| 6 | Granada | **Sí** | XLSX + PDF | Por periodo | 2021 → 2025 (2021, 2022 y 2024 anuales; 2023 por trimestres; 2025 primer semestre + anual); 2026 todavía nada · irregular | [iframe con enlaces](https://transparencia.granada.org/transparente/textAnual.html) · [2025 xlsx](https://www.granada.org/pdf_trans/CM/Contratos%20menores%202025.xlsx) | 2 |
| 7 | Oviedo | Sí, **solo consulta** | Cuadro Pentaho con filtro de fechas (consulta CDA "Contratos menores adjudicados") | No localizado | **No verificado**: el servidor `bi.ovdatos.es` rechaza la conexión desde aquí y la sede no terminó de cargar en 60 s | [sede](https://sede.oviedo.es/perfil-del-contratante/ayuntamiento-de-oviedo/contratos-menores-ayuntamiento-de-oviedo) | 0 |
| 8 | Jerez de la Frontera | Remite a PLACE | — | — | La pestaña "Contratos Menores" solo enlaza al perfil PLACE. La empresa municipal EMUVIJESA sí publica PDF trimestral propio | [transparencia](https://transparencia.jerez.es/infopublica/contratacion/contratos) | 0 |
| 9 | Santa Cruz de Tenerife | **Sí** | PDF anual 2016-2025; CSV 2023-2024 (**sin columna de adjudicatario**); 2025: el CSV/XLSX/ODS es solo un resumen (1.162 contratos, 6,6 M€) y el detalle con adjudicatario está en el PDF (82 págs.) | Por periodo | 2016 → 2025 · anual | [página](https://www.santacruzdetenerife.es/gobiernoabierto/transparencia/contratos) | 20 |
| 10 | Pamplona | **Sí**, con salvedad | XLS anual (~24 MB). **No es un registro de contratos**: son "documentos contables de gastos seleccionados con criterio de importe de contratos menores" | Por periodo | 2019 → 2025 (el de 2025 actualizado el 01-04-2026) · anual | [ficha 2024](https://opendata.pamplona.es/verDatosFichero.aspx?idFichero=419&idioma=1&nifEntidad=P3120100G) · [índice](https://www.pamplona.es/contratos-del-ayuntamiento-de-pamplona) | 0 |
| 11 | Almería | **Sí** | XLSX + PDF anual acumulado (sin CIF, importe con IVA). **Error de la fuente**: el enlace "2025 (XLS)" apunta a un fichero de contratos ABIERTOS; para 2025 solo vale el PDF | Por periodo | 2019 → 2026 (actualizado el 04-08-2026) · se actualiza durante el año | [página](https://almeriaciudad.es/transparencia/contratos-menores/) | 76 |
| 12 | Alcorcón | Remite a PLACE | — | — | Ya documentado: 5 vías revisadas sin fuente propia | (ver `LIMITACIONES_COBERTURA.md`) | 31 |
| 13 | Santander | **Sí** | Un PDF por trimestre y por tipo (servicios, suministro, obras y TUS aparte) | Por periodo (~4 PDF por trimestre, 17 páginas de listado) | Febrero 2012 → 2T-2026 · trimestral (mensual en 2012) | [listado](https://www.santander.es/servicios-empresas/perfil-contratante?field_lv_tipo_contrato_tid=All&field_forma_adjudicacion_tid=All&field_tipo_perfil_contratante_tid=905) | 17 |
| 14 | Albacete | Remite a PLACE | — | — | Ya documentado | (ver `LIMITACIONES_COBERTURA.md`) | 22 |
| 15 | Marbella | Solo histórico | PDF anual "Relación de contratos menores formalizados" | Por periodo | 2015-2019 y 2022; 2020, 2021 y de 2023 en adelante no localizados. El portal actual remite a PLACE | [2022](https://ayuntamiento.marbella.es/images/media/attachments/contratacion/ejercicio-2022/4547_relacion-de-los-contratos-meno/contratos_menores_2022.pdf) · [portal](https://informacionpublica.marbella.es/ambitos/gestion-economica-y-administrativa/contratacion-publica/contratos-menores.html) | 50 |
| 16 | Logroño | Solo histórico | Un único fichero PDF / XLS / CSV | Sí (el fichero único) | **2017-2021**, "datos actualizados en enero de 2022"; nada posterior localizado | [página](https://logrono.es/contratos-menores) | 6 |
| 17 | Torrejón de Ardoz | **Sí** | XLSX desde 1T-2025; PDF de 1T-2022 a 4T-2024 | Por periodo | 1T-2022 → 2T-2026 · trimestral (2021 no localizado) | [página](https://www.ayto-torrejon.es/concejalias/contratacion/contratos-formalizados) · [2T-2026](https://www.ayto-torrejon.es/sites/default/files/LISTADO%20CONTRATOS%20MENORES%20SEGUNDO%20TRIMESTRE%202026.xlsx) | 55 |
| 18 | Huelva | Parcial / histórico | XLSX trimestral en 2022; PDF 1T-2T en 2023 (el enlace del 3T apunta por error a un decreto suelto) | Por periodo | 2022-2023; de 2024 en adelante no localizado | [índice](https://www.huelva.es/portal/transparencia/se-publican-periodicamente-los-contratos-menores) · [2022](https://www.huelva.es/portal/documentos/contratos-menores-2022) | 60 |
| 19 | Dos Hermanas | **No localizado** (actual) | — | — | El portal de transparencia no tiene sección de menores. La sede tiene "Contratación menor", pero hoy no responde (curl, navegador y WebFetch agotan el tiempo); el buscador web solo muestra relaciones de 2015-2018 | [sede](https://sede.doshermanas.es/portal/contratante/pc_contenedor1.jsp?seccion=pc_buscador_de_contrataciones.jsp&codResi=1&language=es&codMenu=3&directo=1&contratacion_estado=4) | 0 |
| 20 | Parla | Remite a PLACE | Según la propia web, en el perfil PLACE, pestaña "DOCUMENTOS" (formato no verificado) | — | — | [página](https://transparencia.ayuntamientoparla.es/contrataciones-de-servicios/contratos-menores/) | 0 |
| 21 | Algeciras | **No localizado** | Solo 5 decretos sueltos (2025-2026) en la carpeta "Contratos menores" de la sede, sin ninguna relación | — | — | [carpeta](https://algeciras.sedelectronica.es/transparency/ac5ebc5c-468f-417f-993b-99f2a01cbbff/) | 0 |
| 22 | León | Sí, **solo consulta** | Tabla en vivo, 10 filas por página, sin exportación | No | Ya documentado (desproporcionadamente caro de extraer) | (ver `LIMITACIONES_COBERTURA.md`) | 0 |
| 23 | Alcobendas | Sí, **no verificable hoy** | CKAN "contratos-menores-total" en CSV/XLSX/ODS/XML/JSON | Sí | Según datos.gob.es, última modificación el 14-09-2022 (probablemente sin datos posteriores). Todo `*.alcobendas.org` devuelve 403 (Akamai) desde aquí | [dataset](https://datos.alcobendas.org/dataset/contratos-menores) | 120 |
| 24 | Jaén | Remite a PLACE | — | — | "Desde la Ley 9/2017 publica su perfil en la PLCSP" | [página](https://transparencia.aytojaen.es/node/47) | 4 |
| 25 | Roquetas de Mar | **Sí** | Relaciones trimestrales (.xls que en realidad es una tabla HTML) alojadas como documentos en PLACE | Por periodo | 1T-2021 → 4T-2025 · trimestral. **Desde el 01-02-2026 las publica como entradas de menores en PLACE** (según la propia web) | [página](https://www.roquetasdemar.es/transparencia/contratacion/contratos-menores) | 4 |
| 26 | Cádiz | Parcial | Solo 2023, en un PDF anual con texto (157 págs.); el resto, "toda la información en PLACE" | Por periodo | 2023 | [página](https://transparencia.cadiz.es/contratos-menores/) · [2023](https://transparencia.cadiz.es/wp-content/uploads/2024/05/Contratos-Menores-Ayuntamiento-Cadiz-2023.pdf) | 7 |
| 27 | Ourense | Remite a PLACE | Pestaña "Documentos" del perfil PLACE (contenido actual no verificado; según prensa, en abril de 2023 lo último era 1T-2022) | — | — | [transparencia, indicador 49](https://ourense.gal/es/servizos/transparencia) | 0 |
| 28 | Telde | **Sí** (2025) y PLACE | ODS + PDF "Relación de contratos menores AÑO 2025": 182 expedientes, con adjudicatario, importe y fecha | Por periodo | 2025 (años anteriores no localizados en la página) · anual | [página](https://www.telde.es/transparencia/contratos-convenios-concesiones-y-subvenciones/contratos-menores/) · [ODS](https://www.telde.es/wp-content/uploads/2026/04/transparencia-contratosmenores.ods) | 0 (*) |
| 29 | Rivas-Vaciamadrid | **No localizado** | — | — | Ni el portal de transparencia ni la sede tienen sección de menores; el perfil solo redirige a PLACE | [transparencia](https://www.rivasciudad.es/transparencia/) | 3 |

(*) La web de Telde dice que sus menores están en PLACE, pero en el feed de agosto de 2026 no aparece ninguna
entrada suya. Queda sin resolver.

### 5.3 Resumen

| Situación | Nº | Municipios |
|---|---:|---|
| Listado propio actual y descargable | 12 | Sevilla, Málaga, Córdoba, Gijón, Granada, Santa Cruz de Tenerife, Pamplona (contable), Almería, Santander, Torrejón, Roquetas (hasta 2025), Telde (2025) |
| — de ellos, con descarga masiva real (API o fichero único con histórico) | 3 | Málaga, Córdoba, Gijón |
| Solo consulta interactiva | 2 | Oviedo, León |
| Listado propio solo histórico o parcial | 5 | Logroño (≤2021), Marbella (≤2022), Huelva (2022-23), Cádiz (2023), Alcobendas (no verificable) |
| Remite a PLACE sin listado propio | 7 | Elche, Jerez, Alcorcón, Albacete, Parla, Jaén, Ourense |
| No localizado tras buscar | 3 | Dos Hermanas, Algeciras, Rivas-Vaciamadrid |

Para la petición pública, lo más relevante es esto:

1. **12 de 29 no tienen listado propio actual** (7 remiten a PLACE y 5 solo publicaron durante un tiempo), pero lo que cada uno sube a PLACE
   varía mucho. Algunos suben entradas de contratos menores al feed (Marbella, Alcorcón, Albacete). Otros suben un
   documento suelto a la pestaña "Documentos" del perfil (Parla, Ourense, Elche según prensa). Otros, según el feed,
   nada en todo agosto de 2026 (Jerez, Parla, Ourense, Elche).
2. **Solo 3 de 29 ofrecen algo parecido a un dataset abierto de verdad** (Málaga, Córdoba y Gijón). El resto son
   ficheros sueltos con nombres no predecibles, cada uno con su formato. En esta muestra ya aparecen al menos 8
   variantes: PDF mensual, PDF trimestral por tipo de contrato, XLSX anual acumulado, XLS contable, CSV sin
   adjudicatario, tabla HTML disfrazada de .xls, consulta Pentaho y tabla paginada en vivo.
3. **Errores en la propia fuente**, detectados abriendo los ficheros: en Almería, el enlace de menores de 2025
   lleva a contratos abiertos; en Huelva, el enlace del 3T-2023 lleva a un decreto suelto; en Santa Cruz, el CSV
   de 2024 no tiene adjudicatario.

### 5.4 Confirmación sobre el punto 2 del encargo anterior (formatos y portales distintos)

**Está incluido.** Es la sección **§2 "Fragmentación de formatos"** de este documento (inventario de los 48
conectores: tipos de origen, fuentes que exigieron Playwright o ingeniería inversa, y casos de histórico
perdido). Esta §5 lo amplía con las 29 ciudades que aún no están conectadas. §2 decía antes, siguiendo a
`LIMITACIONES_COBERTURA.md`, que PLACE "no expone menores de forma sistemática". Ya está corregido según §5.1:
PLACE sí tiene un conjunto de datos de menores, pero nada obliga a cada ayuntamiento a usarlo, ni a usarlo igual.

---

## 6. Contratos menores en el Índice de Transparencia (v2)

- **Peso: 20 %** del Índice de Transparencia v2 (el componente con más peso).
- **Desde el 30-09 el feed de PLACE cuenta en el índice** (opción A, decisión de César; la opción B -- municipio sin
  ningún contrato menor = 0 -- se descartó porque castigaría a pueblos que publican sus menores en su web o en PDF,
  cuando registrarlos en PLACE no es obligatorio). Un municipio sin ningún contrato menor en ninguna fuente sigue
  siendo **no disponible**, no 0.
- **Graduado, no binario**: con la regla de agregadores de RPC/Euskadi casi todo municipio del feed sacaba 100 (4.192
  de 4.439). Se puntúa como un portal: publicar 40 + años cubiertos 20 + frescura del último contrato 20 + % con
  adjudicatario 20, con los años esperados **desde 2023** para los municipios que solo tienen el feed (en 2021-2022 el
  feed apenas tiene datos). Cataluña y País Vasco siguen con la regla de agregadores (años y frescura no disponibles).

Comparación sobre la copia de producción del 25-09 con todas las fuentes cargadas (y los ficheros de población,
cuentas, deuda y sueldos regenerados el 30-09):

| | Antes (producción) | Después (30-09) |
|---|---:|---:|
| Municipios con nota de menores | 931 (11,5 %) | **4.445 (54,8 %)** |
| Nota de menores = 100 | 891 de 931 | 1.864 de 4.445 (90-99: 640; 75-90: 921; 60-75: 1.010; <60: 10) |
| Mediana del índice (P25 / P75) | 70,4 (62,2 / 78,5) | 69,4 (61,6 / 77,1) |
| Municipios con 90 o más | 1,4 % | 1,0 % |
| Puestos movidos (mediana / P90) | — | 315 / 1.329 |

Lo que más cambia, y por qué:
- **Suben** municipios pequeños que no tenían ni menores ni directivo y ahora tienen ambos (Algímia d'Alfara 10,9 →
  32,9; Zarza Capilla 14,2 → 36,8), y otros por la regeneración de las cuentas anuales, que encontró a municipios
  que antes no casaban (Sotés, Peñausende, Gotarrendura: +20).
- **Bajan** hasta 16 puntos pueblos muy pequeños con 1-2 contratos de 2022 en el feed y ninguno desde 2023 (Retamoso de
  la Jara 83,7 → 67,8; Santiuste, 15 hab., 83,0 → 67,4): la frescura y los años cubiertos les dan 62 en menores y su
  adjudicatario, sin directivo buscado todavía, les da 0 en "directivo". Es el efecto esperado de graduar; el de
  "directivo" se corrige solo según avanza el enriquecimiento del Registro Mercantil.
- Sin saltos por comunidad: la variación mediana por comunidad está entre −2,2 (Canarias) y 0.
- Entran 6 municipios que faltaban en las listas (Falset, Vila-rodona y Sant Jaume dels Domenys 85,7; Santa Fe del
  Penedès y Sant Jaume de Frontanyà 71,4; Zalla 62,0). Elantxobe no llega al mínimo de 4 componentes.

## Apéndice: cómo reproducir este documento

1. Copia de trabajo de `cache.db`: copia de la base de producción del 25-09-2026 arrancada con el `app.py` del 30-09
   (carga todas las fuentes del repositorio y el feed de PLACE) -- nunca el original.
2. Scripts, **en el repositorio** (`backend/analisis_peticion_menores/`), todos con `sqlite3` puro y sin red:
   `analisis.py` (secciones 1 y 4), `analisis2.py` (sección 3), `analisis3_cobertura20k.py` (§1.4) y
   `analisis4_extra.py` (tabla por comunidad, >48.400 € por fuente y ranking de §3). Uso:
   `python <script> <copia de cache.db>`; cada uno escribe su `resultado_*.json` en el directorio actual.
3. `poblacion.json` (INE/Padrón) es el mismo fichero que usa la aplicación.
4. Todas las consultas SQL literales están citadas en cada sección.
