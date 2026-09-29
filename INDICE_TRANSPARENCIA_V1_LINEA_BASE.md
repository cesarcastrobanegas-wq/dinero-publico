# Índice de Transparencia v1 — línea base en producción (29-09-2026)

Foto del índice ANTES de cualquier cambio de la v2, para poder comparar. Datos leídos de producción recorriendo las
81 páginas de `/rankings` (parámetro `pag_idx`), con el desglose de cada municipio. Solo lectura; script y JSON
completo en el directorio temporal de la sesión (`indice_v1_baseline.py`, `indice_v1_produccion.json`).

## Distribución de notas

| Medida | Valor |
|---|---:|
| Municipios con índice | **8.086** |
| Mínimo | 15,2 |
| Percentil 25 | 72,3 |
| Mediana | 80,2 |
| Percentil 75 | 88,4 |
| Máximo | 99,2 |
| Media | 78,3 |

| Nota | Municipios | % |
|---|---:|---:|
| ≥ 99 | 2 | 0,0 % |
| ≥ 97 | 119 | 1,5 % |
| ≥ 95 | 375 | 4,6 % |
| ≥ 90 | 1.665 | 20,6 % |
| ≥ 80 | 4.106 | 50,8 % |
| ≥ 70 | 6.599 | 81,6 % |
| ≥ 50 | 7.724 | 95,5 % |

**La mitad de España tiene más de 80 sobre 100 y cuatro de cada cinco municipios más de 70**: el índice discrimina poco.

## Empates

- 659 notas distintas para 8.086 municipios. El mayor grupo empatado: **38 municipios con 71,8**.
- En la nota máxima (99,2) hay 1 municipio en `/rankings`, pero **4 empatados en "99/100"** en el lateral de la
  portada, porque allí se redondea a entero.

Empates en cada puesto del top 10 (`/rankings`, un decimal):

| Puesto | Nota | Municipios empatados |
|---:|---:|---:|
| 1 | 99,2 | 1 |
| 2 | 99,1 | 1 |
| 3 | 98,8 | 1 |
| 4 | 98,6 | 1 |
| 5 | 98,5 | 2 |
| 7 | 98,4 | 4 (puestos 7 a 10) |

En el lateral de la portada (redondeo a entero) los empates se disparan: 4 municipios con "99", **60 con "98"** y
113 con "97".

## Qué componentes tiene cada municipio

| Combinación de componentes ausentes | Municipios |
|---|---:|
| Faltan adjudicatario y directivo (no tenemos contratos formales suyos) | **5.167 (64 %)** |
| Ninguno (7/7) | 2.308 (29 %) |
| Falta cuentas anuales (País Vasco, Navarra, Ceuta, Melilla) | 458 |
| Otras | 153 |

**En el 64 % de los municipios la nota sale solo de 4 señales de sí/no más la "actividad"**.

| Componente | Disponible en | Media donde está | Puntúa 100 | Puntúa 0 |
|---|---:|---:|---:|---:|
| Cuentas anuales | 94 % | 89,6 | 89,6 % | 10,4 % |
| Deuda/hab. publicada | 100 % | 99,4 | **99,4 %** | 0,6 % |
| Saldo no financiero | 100 % | 85,7 | 85,7 % | 14,3 % |
| Sueldo del alcalde (ISPA) | 100 % | 85,2 | 85,2 % | 14,8 % |
| Adjudicatario identificado | 35 % | 92,8 | 69,7 % | 3,1 % |
| Directivo identificado | 34 % | 65,5 | 37,1 % | 12,8 % |

"Deuda publicada" vale 100 en el 99,4 % de los municipios: pesa un 12,5 % y no distingue a casi nadie.

## Sesgos medidos

1. **La nota sube con la cobertura de este proyecto**: mediana **90,9 con 7/7** componentes frente a **77,5 con
   5/7** (y 71,2 con 6/7, 70,2 con 4/7).
2. **Sesgo regional**: las 4 provincias catalanas tienen las medianas más altas (Girona 94,3, Lleida 94,0, Barcelona
   93,0, Tarragona 92,4), donde tenemos contratos formales (PSCP) y menores (RPC) de todos sus municipios. Las más
   bajas: Valencia 72,7, Cádiz 72,7, Castellón 72,1, Alicante 71,8 y Navarra 70,5. En la Comunitat Valenciana
   influyó el fallo de "Ajuntament de X" (contratos formales no asignados), corregido y rellenado hacia atrás el
   29-09-2026, que todavía no se refleja del todo en esta foto.
3. **El top 10 son pueblos muy pequeños** (Villarejo y Ledesma de la Cogolla en La Rioja, Cava, Fulleda, Montoliu de
   Segarra, Bovera, Canejan y Esterri de Cardós en Lleida, Prado en Zamora, Sotillo en Segovia): con pocos contratos,
   todos identificados, y las 4 señales de sí/no en verde, se roza el 100.
