#!/usr/bin/env python3
# encoding: utf-8
"""
Canario anti-colapso para el auto-commit diario de cache.db (ver
INFORME_NOCHE.md 2026-07-25).

Uso:  canario_cache_db.py  <cache_db_repo>  <cache_db_nuevo>

Compara dos métricas básicas entre el cache.db que ya está en el repo y el
recién descargado de producción:
  - total de contratos (suma de len(contratos) en todas las filas de
    `municipios`, incluidas las pseudo-entradas como "Región de Murcia" /
    "Administración General del Estado", que son filas normales de esa tabla)
  - número de filas de `fondos_ue`

Sale con código != 0 (y emite ::error:: para GitHub Actions) si el nuevo cae
por debajo del 90% del anterior en cualquiera de las dos métricas -> mejor no
actualizar que commitear un colapso silencioso (p.ej. si un refresco murió a
medias y produjo un cache.db incompleto).

Si una tabla no existe en el cache.db del repo (p.ej. el seed antiguo no tenía
`fondos_ue`) su conteo anterior se toma como 0, de modo que el chequeo nunca
bloquea por una métrica sin línea base -- solo bloquea caídas reales respecto
a un valor conocido bueno.

Además imprime una línea `RESUMEN contratos=<n> fondos_ue=<n>` con los conteos
del cache.db NUEVO, para poder incluirlos en el mensaje del commit.
"""
import json
import sqlite3
import sys

UMBRAL = 0.90  # el nuevo debe ser >= 90% del anterior en cada métrica


def _contar(path):
    con = sqlite3.connect(path)
    total_contratos = 0
    try:
        for (data,) in con.execute("SELECT data FROM municipios"):
            try:
                total_contratos += len(json.loads(data).get("contratos", []))
            except Exception:
                pass
    except sqlite3.OperationalError:
        pass  # tabla municipios ausente (no debería, pero por robustez)
    try:
        fondos = con.execute("SELECT COUNT(*) FROM fondos_ue").fetchone()[0]
    except sqlite3.OperationalError:
        fondos = 0  # el seed antiguo puede no tener esta tabla
    con.close()
    return total_contratos, fondos


def main():
    if len(sys.argv) != 3:
        print("::error::uso: canario_cache_db.py <repo.db> <nuevo.db>")
        return 2
    repo_db, nuevo_db = sys.argv[1], sys.argv[2]
    c_old, f_old = _contar(repo_db)
    c_new, f_new = _contar(nuevo_db)

    print(f"contratos: repo={c_old} nuevo={c_new}")
    print(f"fondos_ue: repo={f_old} nuevo={f_new}")

    fallo = False
    for nombre, viejo, nuevo in (("contratos", c_old, c_new),
                                 ("fondos_ue", f_old, f_new)):
        if viejo > 0 and nuevo < UMBRAL * viejo:
            print(f"::error::COLAPSO en {nombre}: nuevo={nuevo} < 90% de repo={viejo}. "
                  f"NO se commitea el cache.db descargado.")
            fallo = True

    # Guardia extra: un cache.db nuevo totalmente vacío nunca se commitea,
    # aunque el repo también estuviera vacío (evita subir basura).
    if c_new == 0 and f_new == 0:
        print("::error::El cache.db nuevo está vacío (0 contratos, 0 fondos). NO se commitea.")
        fallo = True

    print(f"RESUMEN contratos={c_new} fondos_ue={f_new}")
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
