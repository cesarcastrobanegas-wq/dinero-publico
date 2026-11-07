# Herramientas del día del alta

Para fusionar los PR de venta (#13, #24, #22, #25, #20, #19, #26) cuando llegue el alta. No cambian la web: no las importa
`backend/` y no se ejecutan en Render ni en Actions.

- `resolver_conflictos.py N`: dentro de la rama del PR N, después de `git merge origin/main`, resuelve los conflictos
  ya conocidos (PR 22, 25, 20 y 19). Si encuentra un bloque que no conoce, no toca ese fichero y lo dice.
  - Ensayado el 05-11-2026.
  - Vuelto a ensayar el 07-11-2026 con main + #30, #32, #29, #31, #33, #18 y #16. Sale un conflicto nuevo en
    `.gitignore` del #20 contra el #16 (los dos añaden su bloque al final). Para él está la regla «20».
- `pruebas_dia_del_alta.py CARPETA apagado|encendido [CARPETA_MAIN/backend]`: pasa las 8 pruebas, una detrás de otra.
  - No usa la red y trabaja con un `cache.db` vacío en una carpeta temporal.
  - En modo «encendido» usa valores inventados.
  - El 07-11-2026 pasaron todas en los dos modos.
