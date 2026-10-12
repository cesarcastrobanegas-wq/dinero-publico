# Diagnóstico de cobertura por comunidad (02-10-2026)

Encargo de César: antes de conectar más ayuntamientos, comparar las 19 comunidades en los puntos con huecos
conocidos, con Murcia, Cataluña (Girona) y País Vasco como referencia de "completo".

**Cómo se ha calculado.** `_calcular_indice_transparencia()` real, ejecutada en local sobre una copia de la base de
producción del 25-09 con todo lo posterior aplicado al arrancar (backfills, feed de menores de PLACE, fuentes
propias, clave compuesta). Los contratos formales son, por tanto, los de producción a 25-09 más los backfills; el
resto de datos son los de hoy. 8.131 municipios. Scripts: `backend/analisis_cobertura_ccaa/`.

## Tabla

| Comunidad | Munis | Menores: % munis | Menores: % población | % pobl. con fuente propia o agregador | Menores /1.000 hab | Sueldos concejales: munis con tabla (de >20.000 hab) | % pobl. | Alcalde ISPA % | Cuentas al día % | Cuentas sin dato % | Saldo % | Formales: % munis con alguno | Formales /1.000 hab | Directivo (media) | Índice (mediana) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Región de Murcia** (ref.) | 45 | 82,2 | 94,2 | 62,5 | 63,6 | 6 de 20 | 60,3 | 84,4 | 66,7 | 17,8 | 88,9 | 93,3 | 4,10 | 43,3 | 78,0 |
| **Cataluña** (ref.) | 947 | 78,5 | 97,3 | 97,3 | 80,1 | 7 de 70 | 35,2 | 91,4 | 95,6 | 2,2 | 96,5 | 94,0 | 6,97 | 37,8 | 85,7 |
| — Girona (provincia) | 221 | 75,6 | 95,9 | 95,9 | 134,8 | 1 de 10 | 13,1 | 91,0 | 99,5 | 0,0 | 99,1 | 91,9 | 9,60 | 45,8 | 86,6 |
| **País Vasco** (ref.) | 251 | 55,4 | 72,2 | 71,8 | 80,9 | 1 de 20 | 11,6 | 86,5 | n/d | n/d | 0,0 | 93,6 | 4,93 | 28,3 | 71,7 |
| Andalucía | 785 | 69,7 | 87,1 | 18,5 | 20,0 | 5 de 88 | 20,2 | 88,5 | 56,8 | 29,4 | 94,6 | 47,1 | 0,89 | 20,6 | 63,0 |
| Comunidad de Madrid | 179 | 66,5 | 93,5 | 65,1 | 15,6 | 7 de 37 | 59,6 | 74,9 | 100,0 | 0,0 | 93,3 | 58,7 | 0,29 | 28,3 | 68,9 |
| Comunitat Valenciana | 542 | 80,1 | 92,4 | 29,7 | 40,8 | 5 de 68 | 12,2 | 87,8 | 97,2 | 2,6 | 99,4 | 44,8 | 1,64 | 17,1 | 64,5 |
| Galicia | 313 | 56,5 | 82,1 | 34,2 | 29,2 | 1 de 23 | 10,9 | 89,5 | 99,7 | 0,3 | 98,4 | 49,8 | 0,86 | 25,0 | 69,8 |
| Castilla y León | 2.248 | 22,8 | 71,2 | 26,1 | 28,4 | 3 de 16 | 16,7 | 85,3 | 89,0 | 5,3 | 92,9 | 8,0 | 0,41 | 18,7 | 71,6 |
| Canarias | 88 | 89,8 | 90,3 | 42,9 | 36,3 | 3 de 30 | 31,0 | 85,2 | 100,0 | 0,0 | 100,0 | 83,0 | 0,43 | 14,7 | 72,9 |
| Castilla-La Mancha | 919 | 69,7 | 90,6 | 7,7 | 75,9 | 1 de 16 | 3,6 | 70,7 | 60,9 | 26,9 | 72,1 | 19,5 | 0,57 | 15,1 | 68,6 |
| Aragón | 731 | 63,5 | 91,4 | 51,0 | 18,3 | 3 de 4 | 57,8 | 86,9 | 99,9 | 0,1 | 97,1 | 14,5 | 0,31 | 15,5 | 65,7 |
| Illes Balears | 67 | 70,1 | 87,1 | 35,1 | 21,9 | 3 de 13 | 12,8 | 74,6 | 77,6 | 11,9 | 92,5 | 53,7 | 0,91 | 22,8 | 65,7 |
| Extremadura | 388 | 83,8 | 87,4 | 14,3 | 23,3 | 1 de 7 | 14,3 | 79,6 | 71,6 | 18,0 | 90,7 | 27,6 | 0,48 | 15,4 | 61,5 |
| Asturias | 78 | 79,5 | 64,6 | 26,6 | 52,4 | 2 de 7 | 48,7 | 92,3 | 85,9 | 9,0 | 96,2 | 53,8 | 0,25 | 22,2 | 69,7 |
| Navarra | 272 | **0,0** | **0,0** | 0,0 | 0,0 | 0 de 4 (*) | 0,0 | 99,6 | n/d | n/d | 0,0 | 86,4 | 6,03 | 8,5 | 63,0 |
| Cantabria | 102 | 75,5 | 87,3 | 0,0 | 23,9 | 0 de 5 | 0,0 | 82,4 | 77,5 | 13,7 | 92,2 | 41,2 | 0,30 | 21,7 | 65,2 |
| La Rioja | 174 | 27,6 | 86,3 | 0,0 | 26,9 | 1 de 2 | 46,5 | 87,9 | 73,6 | 16,1 | 89,7 | 14,9 | 0,51 | 25,8 | 63,0 |
| Melilla | 1 | 0,0 | 0,0 | 0,0 | 0,0 | 0 de 1 | 0,0 | n/d | n/d | n/d | 100,0 | 100,0 | 0,62 | 66,0 | 83,2 |
| Ceuta | 1 | 0,0 | 0,0 | 0,0 | 0,0 | 0 de 1 | 0,0 | n/d | n/d | n/d | 100,0 | 100,0 | 0,16 | 72,7 | 69,8 |
| **España** | 8.131 | 54,8 | 87,2 | 46,1 | 40,4 | 49 de 432 | 28,4 | 85,1 | 83,9 | 10,1 | 86,1 | 37,7 | 2,14 | 22,0 | 69,4 |

(*) Pamplona tiene 9 registros que no se enlazaban con su ficha; ver "Fallos encontrados". Deuda viva: 100 % en todas.

## Lectura

1. **El mayor hueco no son los menores: son los contratos formales.** Las comunidades de referencia (y Navarra)
   tienen el histórico de 5 años por su fuente regional (PSCP, API de Euskadi, portal navarro, BORM): 4-7 contratos
   por 1.000 habitantes y más del 86 % de municipios con alguno. El resto solo tiene los meses de PLACE procesados
   desde la extensión nacional más los backfills de nombres: 0,25-1,6 por 1.000 habitantes (Móstoles 19 contratos,
   Zaragoza 20, Sevilla 130, frente a Girona 841 o Bilbao 477). Arrastra tres componentes del Índice (adjudicatario,
   actividad, directivo = 40 % del peso). El atajo existe y es nacional: los ZIP mensuales de PLACE desde 09/2021,
   con el mismo mecanismo de fichero de backfill ya usado en Galicia y en "Ajuntament".
2. **Menores**: por población la cobertura ya es alta (87 %) gracias al feed de PLACE, pero fuera de la referencia
   casi todo es solo feed (fuente propia o agregador: 46 % de la población en España; Andalucía 18,5 %, Extremadura
   14,3 %, Castilla-La Mancha 7,7 %, Cantabria y La Rioja 0 %). **Navarra es el único cero total** (el feed no la
   cubre). Ciudades de más de 50.000 habitantes sin ningún menor: Bilbao, Oviedo, Pamplona, Dos Hermanas, Parla,
   León, Melilla, Orihuela, Ceuta, Santa Lucía de Tirajana, Avilés, Collado Villalba, Ponferrada, Linares, Eivissa,
   Rincón de la Victoria, Adeje.
3. **Sueldos de concejales con nombre y cargo**: 49 municipios (50 con Pamplona) de 432 de más de 20.000 habitantes,
   28 % de la población. Tampoco la referencia está completa (Cataluña 7 de 70, País Vasco 1 de 20, Murcia 6 de 20):
   aquí no hay comunidad "completa", es trabajo ayuntamiento a ayuntamiento en todas. Sin ninguno: Cantabria,
   Ceuta, Melilla.
4. **Cuentas anuales**: bien en casi todas (89-100 % al día). Huecos: Andalucía (29,4 % sin dato), Castilla-La
   Mancha (26,9 %), Extremadura (18 %), Murcia (17,8 %), La Rioja (16,1 %). Parte puede ser fallo de localización
   y no falta de rendición: València y Jaén capital no están en `cuentas_anuales.json` (nombres que el buscador
   confunde con otros municipios). País Vasco y Navarra: no disponible (tribunales forales), sin fuente conectada.
5. **Directivo identificado**: 15-25 % fuera de la referencia frente a 38-43 % en Murcia y Cataluña. Depende del
   enriquecimiento nocturno (tope de 30 minutos), no de fuentes nuevas.

## Fallos encontrados

- **Pamplona (arreglado en local, sin desplegar)**: los 9 sueldos de concejales estaban guardados como "Pamplona" y
  la ficha es "Pamplona/Iruña": no se mostraban, la ficha decía "no hemos localizado" y el Índice daba 50 en vez de 100.
- **Saldo no financiero en País Vasco y Navarra (sin tocar, decide César)**: el fichero de Hacienda no cubre el
  régimen foral y los 523 municipios puntúan 0 en ese componente (7,5 % del peso). Es un hueco de la fuente, no del
  municipio: con la regla "no disponible no es 0" debería quedar no disponible, como ya se hace con las cuentas.
- **Cuentas de València y Jaén (sin tocar, por verificar)**: puntúan 0 por "no localizadas".

## Atajos regionales comprobados hoy

- **Navarra — repositorio regional real, formato libre**: `hacienda.navarra.es/sicpportal/mtoBuscadorFacturasTrimestrales.aspx`
  ("Relaciones trimestrales de facturas", art. 88 de la ley foral de contratos). Lista por entidad y año; unas 68
  páginas de 20 documentos solo para entidades "Ayuntamiento". La entidad viene en el listado, así que la asignación
  no es ambigua. Pero cada ayuntamiento sube su propio Excel (Tudela: volcado contable de 46 columnas; EPEL
  Tudela-Cultura: NIF, proveedor, concepto, importe) y son **facturas, no contratos**. Precedente: Pamplona se
  excluyó del formato por publicar "apuntes contables, no contratos". Decisión de César antes de construir nada.
  Nota técnica: con Python 3.14 `requests` recibe un corte en el saludo TLS de ese servidor; con `curl` funciona.
- **Canarias** (`datos.canarias.es`): solo contratos del Gobierno de Canarias. **datos.gob.es**, búsqueda de
  "contratos menores": solo ayuntamientos sueltos (Málaga, Gijón, Vigo, Cartagena, Vitoria, Barcelona) y
  administraciones autonómicas. Sin agregador municipal en Andalucía, Extremadura, Cantabria, La Rioja ni Asturias.

## Orden de trabajo propuesto

1. Backfill nacional de contratos formales de PLACE (09/2021 en adelante), por tandas contra copia de producción.
2. Decisiones pendientes: saldo foral como no disponible; facturas trimestrales de Navarra.
3. Cuentas: revisar los "sin dato" de más de 20.000 habitantes (29 municipios), empezando por València y Jaén.
4. Ayuntamiento a ayuntamiento por población: menores de las 17 ciudades de la lista; sueldos de concejales de los
   383 municipios de más de 20.000 habitantes sin tabla.

## Sesión 2 (02-10, tarde)

### Cuentas anuales: tres reglas nuevas de localización

La comprobación en vivo contra rendiciondecuentas.es separa dos casos que el fichero no distinguía:

- **Fallo de localización (arreglado)**: el buscador del portal no encuentra "València" (lo tiene como "Valencia"),
  ni "el Prat de Llobregat" (lo tiene sin artículo), ni "Alcoy" (lo tiene como "Alcoy/Alcoi"). Tres reglas nuevas en
  `_buscar_id_entidad` (`actualizar_cuentas_anuales.py`), siempre con coincidencia exacta del nombre: término sin
  tildes, término sin artículo inicial y cualquiera de las dos mitades de una denominación bilingüe. Reintento de los
  770 municipios que faltaban: **31 recuperados, 1.052.090 habitantes** (València 840.792, el Prat de Llobregat 66.338,
  Alcoy 61.468, Llíria 25.333, la Seu d'Urgell 13.009, la Roca del Vallès 11.014 y 25 más pequeños). 6.836 -> 6.867.
- **Sin cuenta rendida (dato real, no fallo)**: 718 municipios están en el portal pero no tienen ninguna cuenta
  rendida en los ejercicios que muestra. Entre ellos Jaén, Mijas, El Puerto de Santa María, Vélez-Málaga, Utrera,
  Puerto Real, Écija, Mazarrón, Castro-Urdiales, Arcos de la Frontera y Seseña. Su 0 en el Índice es correcto.
- **Otros 21 con alias a mano**: el portal los tiene con otro nombre ("Torre del Campo", "Alfarp", "Herbés", "Candín"
  para Valle de Ancares, "Bisbal de Falset" para la Bisbal de Montsant...). Cada alias se comprobó en vivo (un único
  ayuntamiento en su provincia) y está en `ALIAS_BUSQUEDA`. Los 21 tienen cuenta rendida: 6.867 -> 6.888. Ya no queda
  ningún municipio sin localizar en las 46 provincias que cubre el portal.

Propuesta sin hacer: guardar también esos 718 con su identificador para que la ficha diga "no consta ninguna cuenta
rendida" con enlace al portal, en vez de no decir nada.

### Backfill nacional de formales de PLACE: piloto

`backend/generar_backfill_formales_place.py` (nuevo) guarda, mes a mes, todo contrato formal de PLACE que el patrón
vigente asigna a un municipio (mismas tres condiciones que `buscar_en_zip` con anclaje), en
`backend/backfill_formales_place/AAAAMM.json.gz`. Objetivo: 6.616 municipios (fuera Murcia, Cataluña, País Vasco y
Navarra, que ya tienen histórico). Piloto con los tres ZIP que había en disco:

| ZIP | Contratos en el ZIP | Asignados a municipios (nuevos) | Municipios | Tamaño |
|---|---:|---:|---:|---:|
| 2026-09 (parcial) | 9.168 | 2.544 | 821 | 303 KB |
| 2026-08 (completo) | 30.982 | 6.338 | 1.333 | 715 KB |
| 2026-07 (parcial) | 17.243 | 3.554 | 975 | 394 KB |

Para comparar: la copia de producción del 25-09 tiene 12.416 contratos de PLACE en total (6.625 fuera de Murcia).
Un mes completo aporta unos 6.300; 61 meses pueden quedar en 250.000-350.000 contratos y 30-45 MB comprimidos.
Falta la función de app.py que lo aplique al arrancar y medir el efecto en memoria y disco de producción.

### Decisiones de César (02-10, noche)

1. Backfill de formales: no desplegar hasta probarlo contra la copia de producción, medir el crecimiento de la base
   y recalcular la tabla.
2. Saldo no financiero en País Vasco y Navarra: **no disponible** (hecho en la rama).
3. Facturas trimestrales de Navarra: solo si traen adjudicatario + importe + objeto, y **etiquetadas aparte** como
   "Facturas trimestrales Navarra", nunca mezcladas con los contratos menores.
4. y 5. Desplegar el arreglo de sueldos de Pamplona y el de cuentas anuales.
6. Fichas sin cuenta rendida: decir "no consta ninguna cuenta rendida" con enlace al portal (hecho en la rama; el
   portal distingue "Cuenta no rendida" de "Cuenta rendida no disponible", y solo se afirma con la primera en todos
   los ejercicios que muestra).

### Facturas trimestrales de Navarra: inventario

`backend/analisis_cobertura_ccaa/navarra_facturas_inventario.py` y `navarra_facturas_muestra.py`.

- 1.344 documentos de 140 entidades (2018-2026; 200-266 por año desde 2021). Se casan con 130 de los 272 municipios
  navarros, que suman 584.285 de 683.500 habitantes (85 %). Sin casar a la primera: 10 entidades (Arce/Artzi,
  Baztan, Aranguren, Metauten, Allín, Cendea de Cizur, Larraona, Lantz y dos organismos dependientes).
- Formato del documento más reciente de cada entidad: **104 PDF, 32 hojas de cálculo (31 xlsx, 1 xls), 3 docx, 1 ods**.
- De las 32 hojas de cálculo, 16 traen adjudicatario + importe + objeto en la cabecera (9 además con NIF); otras 8
  traen adjudicatario e importe sin objeto; el resto son volcados contables (Tudela, Mendigorría, Aoiz) o no se leen.
- Los PDF no están clasificados todavía: hay que ver cuántos son tablas con texto y cuántos escaneados.

## Backfill nacional de formales: resultado (03-10)

61 meses de PLACE (09/2021-09/2026), 249.457 contratos de 6.616 municipios en 43 provincias; 23 MB en
`backend/backfill_formales_place_prov/`. Probado contra la copia de producción del 25-09 con el código de hoy, una vez
sin el histórico y otra con él (tablas en `analisis_cobertura_ccaa/diag_tabla_sin.json` y `diag_tabla_con.json`).

- Primer arranque: 225.806-226.295 contratos añadidos (el resto ya estaban), 7 homónimos sin ficha creados; +77 s
  solo la primera vez, los arranques siguientes no repiten nada (hash por provincia).
- Base compactada: 457 MB sin histórico -> 611 MB con él (+154 MB; sin compactar, unos +190 MB).
- Formales por 1.000 hab.: España 2,14 -> 6,68. Fuera de la referencia todas pasan de 0,25-1,64 a 3,7-16,8, al nivel
  de la referencia (4,1-7,0). Municipios con contratos formales: 37,7 % -> 73,2 %.
- Índice (mediana): sube fuera de la referencia (Andalucía 63,0 -> 67,7; C. Valenciana 64,5 -> 74,7; Extremadura
  61,5 -> 69,7) y BAJA en la referencia (Murcia 78,0 -> 69,4; Cataluña 85,7 -> 81,1; País Vasco 79,4 -> 70,4). No
  es un fallo: "actividad" es un percentil dentro de cada tramo de población en toda España, y la referencia
  puntuaba alto porque el resto no tenía histórico. El componente "directivo" baja donde entra el histórico
  (Andalucía 20,7 -> 6,7 de media): esos contratos no tienen directivo y desde el 02-10 solo se rellena con el BORME.
