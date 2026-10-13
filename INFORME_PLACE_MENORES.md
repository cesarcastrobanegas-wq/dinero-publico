# Contratos menores de PLACE: estado de la importación y duplicados que quedan

Informe del 14-10-2026, hecho de noche por encargo de César. Mide la importación que ya está en producción desde el
30-09-2026 (fuente `place-menores`); no cambia ningún dato ni ninguna regla.

**Sobre qué se ha medido:** la copia de la base de producción del 10-10-2026, abierta en solo lectura. Las cifras de
hoy en producción serán algo mayores (el flujo semanal ha corrido después).

## Qué estaba ya hecho

La importación que se pedía construir existe y está desplegada:

- Generador `backend/actualizar_contratos_menores_place.py`, 62 ficheros mensuales (2021-09 a 2026-10) y flujo semanal
  `menores-place-semanal.yml` (jueves, 15:00 UTC), con caché de los ZIP para reanudar.
- Las tres decisiones están aplicadas: manda la fuente propia del ayuntamiento y el feed solo añade lo que no case con
  ella; el importe es el de sin IVA; y solo entra la ventana de 5 años.
- Alcance: toda España salvo Cataluña y País Vasco, que tienen registro propio de menores.

## Cifras

- Contratos menores guardados: 1.996.111. Del feed de PLACE: 855.602 (42,9 %), por 3.702,7 M€ sin IVA.
- Municipios con contratos del feed: 3.574, en 43 provincias. Solo tienen el feed 3.529; fuente propia y feed, 45;
  solo fuente propia, 888.
- Fechas: del 01-09-2021 al 07-10-2026; ninguna futura. Por año: 2021, 6.237; 2022, 81.036; 2023, 188.582; 2024,
  206.468; 2025, 225.009; 2026, 148.270. Los meses de 2021 y 2022 traen pocos contratos porque entonces publicaban en
  el feed muchos menos ayuntamientos, no por descargas fallidas.
- Importes: 8.164 a cero o vacíos, ninguno negativo, 212 por encima de 48.400 € (ya llevan aviso en la ficha).
- Dentro del propio feed hay 764 grupos con el mismo municipio, NIF, importe, fecha y objeto repetidos.

### Contratos del feed por provincia

| Provincia | Contratos | Municipios | Importe sin IVA |
|---|---|---|---|
| valencia | 107.547 | 216 | 497.688.268 € |
| albacete | 89.466 | 84 | 159.796.645 € |
| alicante | 56.477 | 105 | 172.602.629 € |
| madrid | 52.434 | 117 | 223.080.646 € |
| sevilla | 39.022 | 81 | 232.300.952 € |
| murcia | 38.965 | 35 | 109.985.658 € |
| malaga | 37.145 | 73 | 142.574.378 € |
| las_palmas | 33.971 | 27 | 185.224.363 € |
| santa_cruz_tenerife | 29.867 | 52 | 192.227.368 € |
| ciudad_real | 26.081 | 86 | 86.512.912 € |
| castellon | 25.022 | 114 | 122.693.173 € |
| toledo | 24.328 | 176 | 87.030.979 € |
| almeria | 21.332 | 70 | 99.590.665 € |
| huelva | 18.470 | 39 | 48.679.820 € |
| badajoz | 17.901 | 137 | 64.363.166 € |
| cadiz | 17.745 | 33 | 95.038.658 € |
| granada | 16.851 | 116 | 75.232.837 € |
| asturias | 16.081 | 62 | 68.871.841 € |
| cantabria | 14.242 | 77 | 72.949.608 € |
| valladolid | 13.555 | 57 | 46.741.439 € |
| baleares | 13.493 | 47 | 66.871.857 € |
| pontevedra | 13.273 | 44 | 65.832.578 € |
| zaragoza | 10.500 | 189 | 94.766.122 € |
| a_coruna | 10.112 | 68 | 59.455.316 € |
| guadalajara | 9.769 | 138 | 35.370.978 € |
| la_rioja | 8.864 | 48 | 40.853.669 € |
| huesca | 8.792 | 130 | 56.802.368 € |
| jaen | 8.105 | 81 | 45.636.603 € |
| lugo | 7.569 | 26 | 37.853.927 € |
| cordoba | 7.517 | 54 | 47.231.504 € |
| cuenca | 7.504 | 158 | 41.459.419 € |
| salamanca | 7.229 | 60 | 26.039.569 € |
| caceres | 6.739 | 188 | 42.518.210 € |
| leon | 6.522 | 77 | 34.010.381 € |
| zamora | 6.117 | 46 | 27.706.709 € |
| segovia | 4.899 | 70 | 35.223.619 € |
| teruel | 4.598 | 149 | 32.130.366 € |
| ourense | 4.544 | 39 | 51.361.610 € |
| burgos | 3.350 | 41 | 17.661.972 € |
| pais_vasco | 3.128 | 1 | 7.697.332 € |
| palencia | 3.046 | 32 | 18.627.462 € |
| soria | 1.896 | 78 | 21.025.802 € |
| avila | 1.534 | 53 | 13.393.746 € |

País Vasco aparece con un municipio (añadido a mano el 30-09 por estar fuera del registro vasco).

## Duplicados frente a las fuentes propias

En los 45 municipios que tienen fuente propia y feed hay 44.977 contratos del feed. Buscando, entre ellos, los que
coinciden con uno de la fuente propia en adjudicatario e importe (con o sin IVA):

- Con la fecha a 7 días o menos: 192 (0,43 %). La regla vigente los debería haber retirado; el caso mayor es Murcia
  capital (127). No se ha mirado uno a uno por qué siguen ahí.
- Con la fecha a entre 8 y 45 días: 3.189 más (7,1 %). Aquí hay de dos clases, y no se pueden separar solo con esta
  cuenta: contratos repetidos de verdad cuya fecha no coincide entre las dos fuentes, y contratos distintos del mismo
  proveedor por el mismo importe (suministros periódicos).

Fuentes con 10 o más candidatos:

| Fuente propia | Contratos propios | Del feed | Coinciden a ±7 días | Coinciden a 8-45 días |
|---|---|---|---|---|
| murcia-capital | 26.280 | 9.530 | 127 | 680 |
| getafe | 1.664 | 1.446 | 2 | 455 |
| ames | 2.856 | 3.030 | 0 | 452 |
| cartagena-governalia | 16.055 | 3.178 | 3 | 421 |
| alicante | 8.140 | 6.492 | 19 | 256 |
| torre-pacheco | 1.215 | 476 | 0 | 266 |
| toledo | 2.899 | 2.255 | 0 | 146 |
| laspalmasgc | 3.145 | 1.806 | 0 | 123 |
| sax-governalia | 2.710 | 680 | 1 | 105 |
| torrejon | 3.535 | 1.414 | 9 | 35 |
| vilamarxant-governalia | 784 | 125 | 0 | 42 |
| xirivella-governalia | 815 | 199 | 1 | 29 |
| valencia_capital | 10.693 | 1.799 | 2 | 27 |
| lugo | 4.519 | 2.163 | 11 | 13 |
| leganes | 254 | 65 | 0 | 23 |
| arona | 432 | 291 | 0 | 16 |
| burgos | 6.061 | 1.087 | 0 | 14 |
| madrid_capital | 27.959 | 997 | 2 | 10 |
| torrent | 893 | 445 | 1 | 11 |
| santiago | 7.986 | 218 | 0 | 10 |
| almeria | 1.765 | 1.510 | 2 | 8 |
| santa_cruz | 3.785 | 1.831 | 5 | 5 |

### Qué dice el desfase de fechas

Emparejando uno a uno (cada contrato propio solo casa con uno del feed) y ampliando hasta 120 días:

| Municipio (fuente) | Emparejados | A 0-7 días | 8-31 | 32-45 | 46-120 | El feed va antes | El feed va después |
|---|---|---|---|---|---|---|---|
| Cartagena (Governalia) | 1.565 | 3 | 96 | 333 | 1.133 | 1.295 | 267 |
| Sax (Governalia) | 453 | 1 | 8 | 105 | 339 | 433 | 19 |
| Torre Pacheco | 338 | 0 | 247 | 32 | 59 | 336 | 2 |
| Xirivella (Governalia) | 137 | 1 | 3 | 31 | 102 | 133 | 3 |
| Vilamarxant (Governalia) | 95 | 0 | 1 | 41 | 53 | 94 | 1 |
| Leganés | 21 | 0 | 21 | 0 | 0 | 21 | 0 |
| Alicante | 488 | 19 | 172 | 67 | 230 | 202 | 267 |
| Torrejón de Ardoz | 60 | 8 | 34 | 2 | 16 | 15 | 37 |

- En las fuentes de Governalia, Torre Pacheco y Leganés el feed va casi siempre ANTES: su fecha es la de adjudicación y
  la de la fuente propia es la de publicación, semanas o meses después. Ese sesgo en un solo sentido indica que son el
  mismo contrato, y que la ventana vigente (31 días para Governalia, 7 para el resto) se queda corta. Hasta 2.600
  contratos del feed podrían estar repetidos en esos seis municipios.
- En Alicante y Torrejón el desfase va en los dos sentidos: lo más probable es que sean contratos distintos y
  periódicos. No se propone tocarlos.
- Murcia capital, Ames, Getafe, Toledo y Las Palmas no se han podido emparejar uno a uno: sus fuentes propias vienen
  sin NIF o sin fecha de adjudicación (Toledo y Las Palmas no traen fecha; en Ames casi todas las fechas son 1 de enero
  o 1 de julio). Sus candidatos de la tabla anterior quedan sin confirmar.

## Qué queda por decidir

1. Ampliar la ventana de fechas para las fuentes que publican la fecha de publicación (Governalia, Torre Pacheco,
   Leganés): aceptar que el contrato del feed vaya hasta 120 días antes. Retiraría del orden de 2.600 contratos
   repetidos. Riesgo: en proveedores con el mismo importe todos los meses, emparejar dos contratos distintos; al casar
   uno a uno, el recuento total no cambia.
2. Mirar a mano los 127 de Murcia capital que coinciden a 7 días y siguen ahí.
3. Decidir si se revisan los 764 grupos repetidos dentro del propio feed.

## Qué no se ha hecho

- No se ha vuelto a descargar ni a cargar nada: la carga completa ya está en producción y el flujo semanal la mantiene.
- No se ha probado nada sobre una copia modificable de la base: la copia del 10-10 solo se ha leído.
- No se ha cambiado ninguna regla de duplicados.
