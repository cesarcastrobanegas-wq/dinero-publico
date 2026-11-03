# encoding: utf-8
"""
Pruebas de la clasificación de beneficiarios de la PAC (pac_fega.py) con nombres INVENTADOS. No descarga nada ni toca
la base de datos ni la web. Lo que importa es que ninguna persona física salga con nombre: ante la duda, anónimo.
Uso:  python backend/pac_fega_prueba.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pac_fega as P   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        fallos.append(txt)


def grupo(crudo):
    return P.clasificar(P.norm(crudo), crudo)


def visible(crudo):
    return grupo(crudo) in P.VISIBLES


# ─── apellidos que coinciden con abreviaturas de sociedad: anónimos ────────────────────────────────────────────────
for nombre in ("PEREZ GOMEZ JOSE SA", "LOPEZ MARIA DEL CARMEN SÁ", "GARCIA RUIZ ANTONIO SAL", "MARTIN SAL",
               "RUIZ DIAZ ANA B V", "SANCHEZ N V", "Fernández Sá", "PEREZ GOMEZ JOSE S L"):
    ok(not visible(nombre), f"persona con apellido o iniciales al final, anónima: {nombre!r} -> {grupo(nombre)}")
ok(grupo("PEREZ GOMEZ JOSE SA") == "dudoso", "la abreviatura ambigua sin marca va a «dudoso» (lista de revisión)")
ok(not visible("JOSE SA COSTA"), "«SA» en medio del nombre no hace sociedad")

# ─── la misma abreviatura con puntos o detrás de una coma: sociedad ────────────────────────────────────────────────
for nombre in ("TRANSPORTES INVENTADOS S.A.", "PEREZ GOMEZ, SA", "PEREZ GOMEZ, S.A.L.", "INVENTADA S. A.",
               "INVENTADA SA.", "PEREZ GOMEZ S.A.L", "INVENTADA B.V.", "INVENTADA, NV", "PEREZ GOMEZ S.L.",
               "PEREZ GOMEZ, S L", "INVENTADA S. L."):
    ok(grupo(nombre) == "mercantil", f"abreviatura marcada, sociedad: {nombre!r} -> {grupo(nombre)}")

# ─── sin marca pero con palabra de empresa en el nombre: sociedad ─────────────────────────────────────────────────
for nombre in ("AGRICOLA INVENTADA SA", "GANADOS DEL VALLE INVENTADO SAL", "INVERSIONES INVENTADAS BV"):
    ok(grupo(nombre) == "mercantil", f"palabra de empresa + abreviatura, sociedad: {nombre!r} -> {grupo(nombre)}")

# ─── formas que no se confunden con apellidos: sociedad aunque solo haya un espacio ────────────────────────────────
for nombre in ("PEREZ GOMEZ SL", "INVENTADA SLU", "INVENTADA S.L.U.", "INVENTADA, SOCIEDAD LIMITADA",
               "INVENTADA SOCIEDAD ANONIMA", "INVENTADA SAU", "INVENTADA S.R.L.", "INVENTADA LTD", "INVENTADA GMBH"):
    ok(grupo(nombre) == "mercantil", f"forma inequívoca, sociedad: {nombre!r} -> {grupo(nombre)}")

# ─── el resto de grupos, como antes ────────────────────────────────────────────────────────────────────────────────
ok(grupo("SOCIEDAD COOPERATIVA AGRARIA INVENTADA") == "cooperativa_sat", "cooperativa")
ok(grupo("SAT INVENTADA") == "cooperativa_sat", "SAT")
ok(grupo("AYUNTAMIENTO DE VILLAINVENTADA") == "publica", "ayuntamiento")
ok(grupo("COMUNIDAD DE REGANTES INVENTADA") == "asociativa", "comunidad de regantes")
for nombre in ("PEREZ GOMEZ JOSE Y OTROS CB", "HEREDEROS DE PEREZ GOMEZ", "PEREZ GOMEZ HERMANOS SC"):
    ok(grupo(nombre) == "sin_personalidad", f"sin personalidad jurídica, anónima: {nombre!r}")
ok(grupo("PEREZ GOMEZ JOSE") == "persona_fisica_probable", "persona física")
ok(not visible("PEREZ GOMEZ JOSE"), "la persona física no sale con nombre")

# ─── la comprobación de la web (sin el nombre tal cual) nunca es más permisiva ─────────────────────────────────────
for nombre in ("PEREZ GOMEZ JOSE SA", "TRANSPORTES INVENTADOS S.A.", "PEREZ GOMEZ SL"):
    sin_crudo = P.clasificar(P.norm(nombre))
    ok(not (sin_crudo in P.VISIBLES and not visible(nombre)), f"sin el nombre tal cual no se abre nada: {nombre!r}")

# ─── caducidad: publicación + 2 años ───────────────────────────────────────────────────────────────────────────────
ok(P._caduca("2026-05-25") == "2028-05-25", "caduca a los dos años")
ok(P._caduca("2024-02-29") == "2026-02-28", "29 de febrero")

# ─── purga de las copias de cache.db (pac_purgar_copia.py) ─────────────────────────────────────────────────────────
import sqlite3     # noqa: E402
import tempfile    # noqa: E402
import pac_purgar_copia as PC   # noqa: E402

with tempfile.TemporaryDirectory() as d:
    ruta = os.path.join(d, "copia.db")
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE municipios (n TEXT)")
    con.execute("INSERT INTO municipios VALUES ('ficha')")
    for t in PC.TABLAS:
        con.execute(f"CREATE TABLE {t} (ejercicio INTEGER, data TEXT, caduca TEXT)")
        con.executemany(f"INSERT INTO {t} VALUES (?,?,?)",
                        [(2024, "ZZCADUCADA" + "x" * 500, "2027-05-26"), (2025, "ZZVIGENTE", "2028-05-25")] * 50)
    con.commit()
    con.close()
    ok(PC.purgar(ruta, "2027-05-25") == {}, "copia: el día antes de caducar no se borra nada")
    borradas = PC.purgar(ruta, "2027-05-26")
    ok(borradas == {t: 50 for t in PC.TABLAS}, f"copia: el día de la caducidad se borra ese ejercicio ({borradas})")
    con = sqlite3.connect(ruta)
    quedan = {t: con.execute(f"SELECT ejercicio, count(*) FROM {t} GROUP BY ejercicio").fetchall() for t in PC.TABLAS}
    otras = con.execute("SELECT count(*) FROM municipios").fetchone()[0]
    con.close()
    ok(all(v == [(2025, 50)] for v in quedan.values()) and otras == 1, "copia: queda lo vigente y el resto de la base")
    with open(ruta, "rb") as f:
        crudo = f.read()
    ok(b"ZZCADUCADA" not in crudo and b"ZZVIGENTE" in crudo, "copia: lo borrado no queda en el fichero")
    vacia = os.path.join(d, "sin_pac.db")
    sqlite3.connect(vacia).execute("CREATE TABLE municipios (n TEXT)").connection.close()
    ok(PC.purgar(vacia, "2030-01-01") == {}, "copia sin tablas de la PAC: no hace nada")

print("FALLOS:", len(fallos))
sys.exit(1 if fallos else 0)
