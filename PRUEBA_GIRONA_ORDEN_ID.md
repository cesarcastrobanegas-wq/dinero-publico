# Contractes menors de Girona: orden por `:id` (rama wip/girona-orden-id)

Preparado el 25-10-2026. **Sin desplegar.** Fecha prevista: jueves 29-10 por la tarde (después de la reunión del 27-10).

## Qué pasaba

En la noche del 25-10 (ejecución 40165424326), el flujo dio el aviso «menors-girona lleva 30 min sin terminar».
El trabajo no se quedó atascado: terminó en el servidor en **58,6 min con 72.811 contratos**, pero el flujo solo lo
espera 30 min. Después lanzaba los directivos de Girona con la tabla todavía a medio rellenar. Además hubo
**5 municipios cortados por tiempo agotado** (20 s por petición) que se quedaron sin refrescar o a medias.

Causa (medida el 25-10 en Girona capital, código 1707920002, 31.814 contratos menores desde 2021): la consulta
pedía las páginas ordenadas por `codi_expedient`, y la fuente (Socrata) tarda mucho con ese orden.

| Una página de 1.000 filas | Tiempo |
|---|---|
| `$order=codi_expedient` (antes) | 22 s a más de 120 s |
| sin orden | 1,5 s |
| `$order=:id` (ahora), offset 0 | 2,8 s |
| `$order=:id` (ahora), offset 30.000 | 9 s |

## Qué cambia

1. `buscar_en_rpc_menors` ordena por `:id`. El resultado es el mismo, porque `_dedup_rpc_menors` no depende del
   orden. Sirve para las cuatro provincias catalanas.
2. Cada página se reintenta 2 veces, con 5 s de pausa, ante tiempo agotado, error de conexión, 5xx o 429. Los 4xx no
   se reintentan. Si falla igual, se guarda lo leído hasta ahí, como antes.
3. El registro del trabajo dice el municipio en cada línea («Consultando RPC…: Figueres», «RPC no disponible en
   Figueres (ReadTimeout, offset 2000)»).
4. Flujo `actualizar-diario.yml`: si los menores pasan de 30 min, se espera a que terminen (con el tope del presupuesto
   de la noche) y solo después se lanzan sus directivos. Si la noche se agota con los menores aún en marcha, los
   directivos de esa provincia no se lanzan y queda un aviso. No cambia nada en verde/rojo.

No se toca la consulta de contratos formales de Cataluña (PSCP, `buscar_en_pscp`), que también ordena por
`codi_expedient`. Si la prueba sale bien, se puede estudiar el mismo cambio para ella, aparte.

Comprobado en local: sintaxis de Python, YAML y bash; prueba aislada de la consulta con 8 casos simulados
(paginación, orden, municipio en el registro, tiempo agotado, 503, 400, 429, sin filas); simulación del bloque del
flujo con reloj falso (menores en 20 min, en 59 min y noche agotada).

## Prueba del jueves 29-10 por la tarde

Datos de comparación (noche del 25-10): **58,6 min, 72.811 contratos, 5 tiempos agotados**.

1. **Antes de nada.** Comprobar que no hay ningún refresco en marcha. El nocturno del 29-10 tiene que haber acabado:
   `gh run list --workflow actualizar-diario.yml -L 3`. No desplegar mientras corre (reinicia la web y mata el
   trabajo).
2. **Desplegar.** Llevar la rama a `main` **sin** `[skip render]`: el cambio de la consulta está en `app.py` y solo
   funciona con la web reiniciada. Esperar a que la web vuelva (`/api/diagnostico-arranque` responde y
   `hilo_directivos.desde` es posterior al despliegue).
3. **Disparar solo Girona:**
   `gh workflow run actualizar-diario.yml -f provincia=girona`
   Hace los contratos de Girona (unos 12 min), luego los contractes menors y luego sus directivos.
4. **Mirar en el registro de la ejecución** (`gh run view <id> --log`):
   - `menors-girona=done` **antes** de los 30 min, sin el aviso «lleva 30 min sin terminar»;
   - en el registro del trabajo: `RPC: N contractes menors guardados en total (221 municipios, girona)`, y
     cuántas líneas `RPC no disponible en …` y `reintento` aparecen (ahora con el nombre del municipio);
   - que «Disparando /actualizar-directivos-contratos-menores (turno girona)» sale **después** del `done` de menores.
   Si la web se ha reiniciado, el registro se pierde. Para leerlo:
   `curl -s https://dinero-publico.onrender.com/api/job/<job_menors>` (campos `total`, `duracion_min`, `log`).
5. **Dar por buena la prueba si:** `duracion_min` está muy por debajo de 58,6 (se espera de 5 a 15 min); `total` es
   igual o mayor que 72.811 (si es menor, mirar qué municipios fallaron antes de aceptarlo); ningún municipio queda
   «no disponible» tras los reintentos, o como mucho alguno suelto con nombre y motivo.
6. **Si sale mal:** revertir el commit en `main` (fuera del horario del nocturno). Los datos no se estropean: la
   tabla solo se inserta o se sobrescribe, nunca se borra por municipio.
7. **Primera noche después:** cuando la rotación vuelva a pasar por Girona/Lleida, comprobar que no aparece el aviso
   de los 30 min y apuntar los tiempos de las cuatro provincias catalanas.
