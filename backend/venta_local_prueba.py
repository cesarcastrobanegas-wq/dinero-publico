# encoding: utf-8
"""Prueba SIN RED de llamadas.py y prueba_gratis.py con la base INVENTADA de informe_mercado_prueba.py.

Comprueba: la lista solo lleva sociedades (nunca personas físicas), columnas vacías para apuntar, teléfono y web solo
si constan en el Excel de contactos, fichas de media página (2 por hoja), y en la prueba gratis: alta, filtro por
sector/CPV y municipio, nuevas frente a «siguen abiertas», todo dentro de la carpeta indicada, baja que la borra y
ninguna conexión a la red ni a Resend.
Uso: python backend/venta_local_prueba.py   (necesita reportlab, openpyxl y pypdfium2 o pypdf)
"""
import csv
import os
import socket
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402
import informe_mercado_prueba as IP  # noqa: E402
import llamadas as L  # noqa: E402
import prueba_gratis as PG  # noqa: E402

FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        FALLOS.append(txt)


def paginas(ruta):
    import pypdfium2
    d = pypdfium2.PdfDocument(ruta)
    try:
        return len(d)
    finally:
        d.close()           # en Windows, un PDF abierto no se puede borrar (la baja lo borra)


def texto_pdf(ruta):
    import pypdfium2
    d = pypdfium2.PdfDocument(ruta)
    try:
        return "\n".join(p.get_textpage().get_text_range() for p in d)
    finally:
        d.close()


def sin_red(*a, **k):
    raise AssertionError("la prueba no debe conectarse a nada")


def main():
    socket.socket.connect = sin_red            # cualquier intento de conexión hace fallar la prueba
    d = tempfile.mkdtemp(prefix="venta_local_")
    ruta_db = os.path.join(d, "copia.db")
    IP.base(ruta_db)
    contratos = I.cargar_contratos(ruta_db, "murcia", "2024-01-01", "2026-10-10")
    ok(all("municipio" in r for r in contratos), "los contratos llevan su municipio")
    ahora = datetime(2026, 11, 4, 10, 0)
    lic = [dict(id="L1", titulo="Servicio de limpieza del polideportivo", organo="Ayuntamiento de Villaprueba",
                fin_plazo="2026-11-20 14:00", presupuesto="40000", cpvs=["90911200"], cpv="90911200",
                url="https://ejemplo.test/1", req={}, provincia="murcia", expediente="E-1"),
           dict(id="L2", titulo="Limpieza de colegios", organo="Ayuntamiento de Otroslugar",
                fin_plazo="2026-11-12 14:00", presupuesto="20000", cpvs=["90919200"], cpv="90919200",
                url="https://ejemplo.test/2", req={}, provincia="murcia", expediente="E-2"),
           dict(id="L3", titulo="Limpieza del hospital", organo="Servicio Murciano de Salud",
                fin_plazo="2026-11-25 14:00", presupuesto="90000", cpvs=["90911200"], cpv="90911200",
                url="https://ejemplo.test/3", req={}, provincia="murcia", expediente="E-3"),
           dict(id="L4", titulo="Suministro de ordenadores", organo="Ayuntamiento de Villaprueba",
                fin_plazo="2026-11-21 14:00", presupuesto="30000", cpvs=["30213000"], cpv="30213000", req={},
                provincia="murcia", expediente="E-4")]
    # lista de clientes potenciales inventada: dos sociedades y una persona física (que no debe salir nunca)
    csv_ruta = os.path.join(d, "clientes.csv")
    with open(csv_ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["puesto", "nombre", "nif", "municipio_sede"])
        w.writerow([1, "LIMPIEZAS PRUEBA SL", "B00000001", "Villaprueba"])
        w.writerow([2, "BRILLO COMPETIDOR SA", "A00000002", "(sin dato: ver municipio_donde_mas_contrata)"])
        w.writerow([3, "PERSONA FISICA DE PRUEBA", "00000000T", "Villaprueba"])
    import openpyxl
    xlsx = os.path.join(d, "contactos.xlsx")
    wb = openpyxl.Workbook()
    wb.active.append(["★", "Nombre", "NIF", "Municipio (sede)", "Sector", "x", "y", "z", "Web",
                      "Contacto corporativo (de su web)", "Fuente del contacto", "Fecha de comprobación"])
    wb.active.append(["", "LIMPIEZAS PRUEBA SL", "B00000001", "", "", "", "", "", "www.ejemplo.test",
                      "Tel. 968 000 000 · info@ejemplo.test", "web de la empresa", "25-10-2026"])
    wb.save(xlsx)
    salida = os.path.join(d, "llamadas")
    el = L.generar(contratos, lic, csv_ruta, salida, "2026-10-10", ahora, xlsx, n=30)
    nifs = [e["nif"] for e in el]
    ok(set(nifs) == {"B00000001", "A00000002"}, f"solo las dos sociedades ({nifs})")
    ok(el[0]["nif"] == "B00000001", "la de más contratos y licitaciones que le encajan, primera")
    e1 = el[0]
    ok([x["id"] for x in L.licitaciones_ficha(e1)][:1] == ["L1"], "en la ficha, primero la de un municipio donde gana")
    ok("L4" not in [x["id"] for x in e1["abiertas"]], "la de otro sector no entra en su ficha")
    wb = openpyxl.load_workbook(os.path.join(salida, "Lista de llamadas.xlsx"))
    filas = list(wb["Llamadas"].iter_rows(values_only=True))
    cab = list(filas[0])
    for c in L.COLUMNAS_APUNTAR:
        ok(c in cab and all(not f[cab.index(c)] for f in filas[1:]), f"columna vacía para apuntar: {c}")
    fila1 = dict(zip(cab, filas[1]))
    ok(fila1["Teléfono"] == "968 000 000" and fila1["Web"] == "www.ejemplo.test", "teléfono y web del Excel")
    ok(not dict(zip(cab, filas[2]))["Teléfono"], "sin contacto en el Excel: teléfono en blanco (no se inventa)")
    todo = " ".join(str(x) for f in filas for x in f if x)
    ok("PERSONA FISICA" not in todo.upper() and "00000000T" not in todo, "ninguna persona física en la lista")
    pdf_l = os.path.join(salida, "Lista de llamadas.pdf")
    pdf_f = os.path.join(salida, "Fichas de llamada.pdf")
    ok(os.path.exists(pdf_l) and paginas(pdf_l) >= 1, "lista en PDF")
    ok(paginas(pdf_f) == (len(el) + 1) // 2, f"fichas: media página cada una ({paginas(pdf_f)} páginas)")
    tf = texto_pdf(pdf_f)
    ok("ganó" in tf and "Servicio de limpieza del polideportivo" in tf and "quedan 16 días" in tf,
       "ficha con gancho y licitación abierta con plazo")
    ok("PERSONA FISICA" not in tf.upper() and "NOMBRE DE ADMINISTRADOR" not in tf.upper(), "ficha sin personas")

    # seguimiento: lo apuntado no se pierde al regenerar
    ruta_seg = os.path.join(salida, L.SEGUIMIENTO_XLSX)
    ruta_lista = os.path.join(salida, "Lista de llamadas.xlsx")

    def filas_xlsx(ruta):
        w = openpyxl.load_workbook(ruta)
        r = list(w.worksheets[0].iter_rows(values_only=True))
        w.close()
        return [dict(zip(r[0], f)) for f in r[1:]]

    seg = filas_xlsx(ruta_seg)
    ok(sorted(f["NIF"] for f in seg) == ["A00000002", "B00000001"] and all(c in seg[0] for c in L.COLUMNAS_APUNTAR),
       "el seguimiento se crea con una fila por empresa y sus columnas")
    regen = lambda: L.generar(contratos, lic, csv_ruta, salida, "2026-10-10", ahora, xlsx, n=30)  # noqa: E731
    antes = open(ruta_seg, "rb").read()
    regen()
    ok(open(ruta_seg, "rb").read() == antes, "sin empresas nuevas ni notas, el seguimiento no se toca")
    # 1) lo apuntado en la propia lista pasa al seguimiento
    w = openpyxl.load_workbook(ruta_lista)
    ws = w["Llamadas"]
    cab = [c.value for c in ws[1]]
    r1 = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, cab.index("NIF") + 1).value == "B00000001")
    ws.cell(r1, cab.index("Fecha de llamada") + 1, datetime(2026, 11, 5))
    ws.cell(r1, cab.index("Notas") + 1, "llamar por la tarde")
    w.save(ruta_lista)
    # 2) lo apuntado en el seguimiento, con una columna y una empresa añadidas a mano
    w = openpyxl.load_workbook(ruta_seg)
    ws = w.worksheets[0]
    cab = [c.value for c in ws[1]]
    ws.cell(1, len(cab) + 1, "Mi columna")
    ra = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, cab.index("NIF") + 1).value == "A00000002")
    ws.cell(ra, cab.index("Interesado (sí/no)") + 1, "no")
    ws.cell(ra, cab.index("Notas") + 1, "no le interesa ahora")
    ws.cell(ra, len(cab) + 1, "algo mío")
    ws.cell(ws.max_row + 1, cab.index("Razón social") + 1, "EMPRESA APUNTADA A MANO SL")
    w.save(ruta_seg)
    regen()
    seg = {f["NIF"] or f["Razón social"]: f for f in filas_xlsx(ruta_seg)}
    ok(seg["B00000001"]["Notas"] == "llamar por la tarde" and seg["B00000001"]["Fecha de llamada"].day == 5,
       "lo apuntado en la lista pasa al seguimiento")
    ok(seg["A00000002"]["Notas"] == "no le interesa ahora" and seg["A00000002"]["Mi columna"] == "algo mío"
       and "EMPRESA APUNTADA A MANO SL" in seg, "el seguimiento conserva lo suyo: notas, columnas y filas a mano")
    lista = {f["NIF"]: f for f in filas_xlsx(ruta_lista)}
    ok(lista["A00000002"]["Interesado (sí/no)"] == "no" and lista["B00000001"]["Notas"] == "llamar por la tarde",
       "la lista nueva trae rellenado lo del seguimiento")
    ok("no le interesa ahora" not in texto_pdf(pdf_l) and "05/11/2026" in texto_pdf(pdf_l),
       "la lista en PDF trae las columnas de seguimiento que caben (sin notas)")
    ok(os.path.exists(os.path.join(salida, L.SEGUIMIENTO_COPIA)), "antes de cambiar el seguimiento, deja una copia")
    # 3) un cambio en el seguimiento manda sobre la lista; lo de la lista solo rellena huecos
    w = openpyxl.load_workbook(ruta_lista)
    ws = w["Llamadas"]
    cab = [c.value for c in ws[1]]
    r1 = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, cab.index("NIF") + 1).value == "B00000001")
    ws.cell(r1, cab.index("Notas") + 1, "otra cosa")
    w.save(ruta_lista)
    regen()
    seg = {f["NIF"] or f["Razón social"]: f for f in filas_xlsx(ruta_seg)}
    ok(seg["B00000001"]["Notas"] == "llamar por la tarde", "nunca se pisa lo que ya hay en el seguimiento")

    # exclusiones permanentes: por razón social (sin forma social ni tildes) o por CIF
    with open(os.path.join(salida, L.EXCLUIDAS_TXT), "w", encoding="utf-8") as f:
        f.write("# descartadas a mano\nBrillo Competidor   # sin «S.A.»\n")
    ok([e["nif"] for e in regen()] == ["B00000001"], "excluida por razón social: ya no sale")
    with open(os.path.join(salida, L.EXCLUIDAS_TXT), "w", encoding="utf-8") as f:
        f.write("a0000000-2\n")
    ok([e["nif"] for e in regen()] == ["B00000001"], "excluida por CIF: ya no sale")
    ok("A00000002" in {f["NIF"] for f in filas_xlsx(ruta_seg)}, "excluir no borra nada del seguimiento")
    ok(L.norm_razon("LA OPINION DE MURCIA, S.A.U.") == L.norm_razon("La Opinión de Murcia")
       and L.norm_razon("Graficas Alamo, S.l.") == "GRAFICAS ALAMO", "razón social: tildes y forma social no cuentan")
    os.remove(os.path.join(salida, L.EXCLUIDAS_TXT))

    # prueba gratis
    carpeta = os.path.join(d, "clientes en prueba")
    p = PG.alta(carpeta, "cliente@ejemplo.test", sector="Limpieza", municipios=["Villaprueba"],
                nombre="LIMPIEZAS PRUEBA SL", ahora=ahora)
    ok(p["fin_prueba"] == "2026-12-04", "prueba de 30 días")
    for malo in ("no-es-correo", ""):
        try:
            PG.alta(carpeta, malo, sector="Limpieza")
            ok(False, f"correo no válido rechazado ({malo!r})")
        except SystemExit:
            ok(True, f"correo no válido rechazado ({malo!r})")
    rp, rt, nuevas, siguen = PG.resumen(carpeta, p, lic, ahora, contacto={"tel": "", "email": "x@ejemplo.test"})
    ids = sorted(x["id"] for x in nuevas)
    ok(ids == ["L1", "L3"], f"su municipio + organismo regional, ni otro ayuntamiento ni otro sector ({ids})")
    txt = open(rt, encoding="utf-8").read()
    ok(txt.startswith("Asunto: ") and "NUEVAS ESTA SEMANA (2)" in txt and "https://ejemplo.test/1" in txt,
       "texto para pegar en el correo")
    ok(os.path.exists(rp) and "Licitaciones de la semana" in texto_pdf(rp), "resumen en PDF")
    p = PG.leer_perfil(carpeta, "cliente@ejemplo.test")
    rp2, rt2, nuevas2, siguen2 = PG.resumen(carpeta, p, lic + [dict(lic[0], id="L5", titulo="Limpieza de la piscina")],
                                            datetime(2026, 11, 11, 10, 0), contacto={})
    ok([x["id"] for x in nuevas2] == ["L5"] and sorted(x["id"] for x in siguen2) == ["L1", "L3"],
       "la semana siguiente: solo la nueva arriba, las demás en «siguen abiertas»")
    solo = PG.alta(carpeta, "otro@ejemplo.test", cpvs=["9091"], municipios=["Villaprueba"], solo_municipios=True)
    _, _, n3, _ = PG.resumen(carpeta, solo, lic, ahora, contacto={}, marcar=False)
    ok([x["id"] for x in n3] == ["L1"], "por CPV y solo municipios: fuera el organismo regional")
    todos = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs]
    fuera = [f for f in todos if "cliente@ejemplo.test".replace("@", "_").replace(".", "_") in f
             and not f.startswith(carpeta)]
    ok(not fuera, "los datos del cliente solo están en su carpeta")
    src = open(PG.__file__, encoding="utf-8").read() + open(L.__file__, encoding="utf-8").read()
    ok("resend" not in src.lower().replace("no usa resend", "") and "urllib" not in src and "requests" not in src,
       "ni Resend ni conexiones en las dos herramientas")
    PG.baja(carpeta, "cliente@ejemplo.test")
    ok(not os.path.exists(PG.carpeta_cliente(carpeta, "cliente@ejemplo.test")), "baja: su carpeta, borrada")
    ok([c["correo"] for c in PG.clientes(carpeta)] == ["otro@ejemplo.test"], "el otro cliente sigue")
    ok("620" not in src, "ningún teléfono escrito en el código")
    print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'} (ficheros en {d})")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
