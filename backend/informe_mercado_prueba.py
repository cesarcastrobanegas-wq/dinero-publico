# encoding: utf-8
"""Prueba sin red del informe de mercado (informe_mercado.py) con una base INVENTADA en un fichero temporal.

Comprueba: personas físicas nunca con nombre ni NIF en el PDF, NIF de persona física rechazado, menores repetidos
entre fuentes contados una vez, importe repetido de un acuerdo marco repartido, adjudicatario «No localizada» aparte,
alias de organismos, sector fijado con --sector en modo empresa, licitaciones que encajan por CPV y PDF de 3-5 páginas.
Uso: python backend/informe_mercado_prueba.py   (necesita reportlab y pypdf o pypdfium2 para contar páginas)
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402

FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        FALLOS.append(txt)


def base(ruta):
    db = sqlite3.connect(ruta)
    db.execute("CREATE TABLE municipios (municipio TEXT, provincia TEXT, data TEXT)")
    db.execute("CREATE TABLE contratos_menors_locales (id TEXT, municipio TEXT, organisme TEXT, adjudicatari TEXT, "
               "import_num REAL, data_adjudicacio TEXT, tipus_contracte TEXT, descripcio TEXT, codi_cpv TEXT, "
               "exercici TEXT, ts TEXT, provincia TEXT, fuente TEXT, nif TEXT)")
    formales = []
    for i in range(30):
        formales.append(dict(titulo=f"Servicio de limpieza de colegios lote {i}", empresa="LIMPIEZAS PRUEBA SL",
                             nif="B00000001", importe_num=20000 + i * 1000, fecha=f"2025-{1 + i % 12:02d}-15",
                             organo="Junta de Gobierno Local del Ayuntamiento de Villaprueba", licitacion_id=f"E{i}",
                             cargo="Administrador único", directivo="NOMBRE DE ADMINISTRADOR QUE NO DEBE SALIR"))
    for i in range(12):
        formales.append(dict(titulo="Limpieza de dependencias municipales", empresa="BRILLO COMPETIDOR SA",
                             nif="A00000002", importe_num=50000, fecha=f"2025-{1 + i % 12:02d}-10",
                             organo="Pleno del Ayuntamiento de Villaprueba", licitacion_id=f"F{i}", cargo=""))
    # acuerdo marco: mismo expediente e importe para tres empresas
    for emp, nif in (("UNA SL", "B00000003"), ("OTRA SL", "B00000004"), ("TERCERA SL", "B00000005")):
        formales.append(dict(titulo="Acuerdo marco de limpieza viaria", empresa=emp, nif=nif, importe_num=900000,
                             fecha="2025-06-01", organo="Ayuntamiento de Villaprueba", licitacion_id="AM1", cargo=""))
    formales.append(dict(titulo="Concesión de limpieza de playas", empresa="No localizada", nif="",
                         importe_num=5000000, fecha="2025-07-01", organo="Ayuntamiento de Villaprueba",
                         licitacion_id="X1", cargo=""))
    formales.append(dict(titulo="Limpieza de un local", empresa="PERSONA FISICA DE PRUEBA", nif="00000000T",
                         importe_num=9000, fecha="2025-03-01", organo="Ayuntamiento de Villaprueba",
                         licitacion_id="P1", cargo="Persona física"))
    formales.append(dict(titulo="Obras de pavimentación", empresa="OBRAS AJENAS SL", nif="B00000006",
                         importe_num=300000, fecha="2025-04-01",
                         organo="Gerencia de la Empresa Municipal de Aguas y Saneamiento de Murcia S.A.",
                         licitacion_id="O1", cargo=""))
    db.execute("INSERT INTO municipios VALUES (?,?,?)", ("villaprueba", "murcia", json.dumps({"contratos": formales})))
    menores = [("m1", "PERSONA AUTONOMA", 3000, "2025-02-02", "90910000", "00000001R", "propia"),
               ("m2", "LIMPIEZAS PRUEBA SL", 4000, "2025-05-05", "90911200", "B00000001", "propia"),
               ("m3", "LIMPIEZAS PRUEBA S.L.", 4000, "2025-05-05", "90911200", "B00000001", "place")]   # repetido
    for i, nombre, imp, f, cpv, nif, fuente in menores:
        db.execute("INSERT INTO contratos_menors_locales (id, municipio, organisme, adjudicatari, import_num, "
                   "data_adjudicacio, descripcio, codi_cpv, provincia, fuente, nif) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (i, "villaprueba", "Ayuntamiento de Villaprueba", nombre, imp, f, "Limpieza", cpv, "murcia",
                    fuente, nif))
    db.commit()
    db.close()


def paginas(ruta):
    try:
        import pypdfium2
        return len(pypdfium2.PdfDocument(ruta))
    except ImportError:
        from pypdf import PdfReader
        return len(PdfReader(ruta).pages)


def texto_pdf(ruta):
    try:
        import pypdfium2
        return "\n".join(p.get_textpage().get_text_range() for p in pypdfium2.PdfDocument(ruta))
    except ImportError:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() for p in PdfReader(ruta).pages)


def main():
    d = tempfile.mkdtemp(prefix="informe_mercado_")
    ruta_db = os.path.join(d, "copia.db")
    base(ruta_db)
    cs = I.cargar_contratos(ruta_db, "murcia", "2024-10-10", "2026-10-10")
    ok(len([r for r in cs if r["tipo"] == "menor"]) == 2, "menor repetido entre fuentes contado una vez")
    am = [r for r in cs if r["texto"].startswith("Acuerdo marco")]
    ok(all(abs(r["importe"] - 300000) < 0.01 for r in am), "acuerdo marco repartido entre sus 3 adjudicatarias")
    ok(any(r["organismo"] == "Aguas de Murcia (EMUASA)" for r in cs), "alias de EMUASA")
    ok(any(r["organismo"] == "Ayuntamiento de Villaprueba" and r["texto"].startswith("Servicio de limpieza de")
           for r in cs), "«Junta de Gobierno Local del Ayuntamiento de X» -> «Ayuntamiento de X»")
    ahora = datetime(2026, 11, 4, 10, 0)
    lic = [dict(id="L1", titulo="Servicio de limpieza del polideportivo", organo="Ayuntamiento de Villaprueba",
                fin_plazo="2026-11-20 14:00", presupuesto="40000", cpvs=["90911200"], cpv="90911200",
                url="https://ejemplo.test/a?b=1&c=2", req={}, provincia="murcia"),
           dict(id="L2", titulo="Suministro de ordenadores", organo="Ayuntamiento de Villaprueba",
                fin_plazo="2026-11-21 14:00", presupuesto="30000", cpvs=["30213000"], cpv="30213000", req={},
                provincia="murcia")]
    A = I.analizar(cs, lic, sector="Limpieza")
    ok([x["id"] for x in A["abiertas"]] == ["L1"], "solo encaja la licitación de limpieza (por CPV)")
    ok(A["sin_adj"]["n"] == 1 and A["sin_adj"]["importe"] == 5000000, "«No localizada» va aparte")
    ok(all(a["nif"][0] in I.LETRAS_SOCIEDAD for a in A["ranking"]), "el ranking solo tiene sociedades")
    ok(A["otros"]["n"] == 2, "persona física y autónomo sumados sin nombre")
    pdf = os.path.join(d, "sector.pdf")
    n, _ = I.informe_pdf(pdf, A, "murcia", "2024-10-10", "2026-10-10", ahora)
    ok(1 <= paginas(pdf) <= 5, f"PDF de sector con {paginas(pdf)} páginas (máx. 5)")
    t = texto_pdf(pdf)
    ok("PERSONA FISICA" not in t.upper() and "PERSONA AUTONOMA" not in t.upper(), "ninguna persona física con nombre")
    ok("00000000T" not in t and "00000001R" not in t, "ningún NIF de persona física")
    ok("NOMBRE DE ADMINISTRADOR" not in t.upper(), "nunca el administrador (campo directivo)")
    ok("LIMPIEZAS PRUEBA SL" in t.upper() and "BRILLO COMPETIDOR" in t.upper(), "las sociedades salen con nombre")
    try:
        I.analizar(cs, lic, nif="00000000T")
        ok(False, "NIF de persona física rechazado")
    except SystemExit:
        ok(True, "NIF de persona física rechazado")
    E = I.analizar(cs, lic, nif="B00000001", sector="Limpieza")
    ok(E["sectores"] == ["Limpieza"] and E["empresa"]["nombre"] == "LIMPIEZAS PRUEBA SL", "modo empresa con --sector")
    pdf2 = os.path.join(d, "empresa.pdf")
    I.informe_pdf(pdf2, E, "murcia", "2024-10-10", "2026-10-10", ahora)
    t2 = texto_pdf(pdf2)
    ok("Contratos ganados por LIMPIEZAS PRUEBA SL" in t2, "modo empresa: apartado de sus contratos")
    ok(1 <= paginas(pdf2) <= 5, f"PDF de empresa con {paginas(pdf2)} páginas (máx. 5)")
    print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'} (ficheros en {d})")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
