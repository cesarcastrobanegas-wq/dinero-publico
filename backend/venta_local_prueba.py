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
import time
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
    # contratos variados de otras empresas (para que «limpieza» sea una palabra que distingue una actividad)
    import sqlite3
    db = sqlite3.connect(ruta_db)
    objetos = [("Suministro de ordenadores portátiles", "30213000"), ("Reparación de alumbrado público", "50232100"),
               ("Actuación musical en las fiestas", "92312000"), ("Pavimentación de aceras", "45233222"),
               ("Curso de formación de monitores", "80500000"), ("Transporte en autobús de escolares", "60130000"),
               ("Seguro de responsabilidad civil", "66516000"), ("Impresión de carteles de las fiestas", "22462000"),
               ("Poda de arbolado", "77211400"), ("Vigilancia de instalaciones deportivas", "79713000")]
    for k in range(700):
        obj, cpv = objetos[k % len(objetos)]
        db.execute("INSERT INTO contratos_menors_locales (id, municipio, organisme, adjudicatari, import_num, "
                   "data_adjudicacio, descripcio, codi_cpv, provincia, fuente, nif) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (f"v{k}", "villaprueba", "Ayuntamiento de Villaprueba", f"VARIADA {k % len(objetos)} SL",
                    1000 + k, f"2025-{1 + k % 12:02d}-0{1 + k % 9}", obj, cpv, "murcia", "propia",
                    f"B9{k % len(objetos):07d}"))
    db.commit()
    db.close()
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
                provincia="murcia", expediente="E-4"),
           # de su sector por CPV (9092) pero sin nada que ver con lo que gana: no debe salir en su ficha
           dict(id="L6", titulo="Desinsectación de buques y submarinos de la Armada", organo="Intendencia de Cartagena",
                fin_plazo="2026-11-22 14:00", presupuesto="80000", cpvs=["90922000"], cpv="90922000", req={},
                provincia="murcia", expediente="E-6")]
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
    ok("L6" not in [x["id"] for x in e1["abiertas"]] and I.encaja(lic[4], {"Limpieza"}),
       "la de su sector por CPV pero ajena a lo que gana (los «submarinos») no entra en su ficha")
    ok(all(2 <= len(L.licitaciones_ficha(e, ahora=ahora)) <= 3 for e in el), "cada ficha lleva 2 o 3 licitaciones")
    sin_bastantes = dict(el[0], abiertas=el[0]["abiertas"][:1])
    ok(L.elegir([sin_bastantes], ahora=ahora) == [], "una empresa con menos de 2 licitaciones que le encajen no entra")
    ok(L.raices("Iluminación de Navidad en la pedanía de Espinardo", frozenset()) >= {"NAVIDA"}
       and "AUDITO" not in L.raices("Obras en el auditorio"), "raíces: «Navidad» cuenta, «auditorio» no es auditoría")
    ok(L.nombre_informe_sector("Eventos, cultura y espectáculos") == "Sector - Eventos cultura y espectaculos.pdf",
       "nombre del informe por sector, sin tildes ni comas")
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
    rp, rt, nuevas, siguen = PG.resumen(carpeta, p, lic[:4], ahora, contacto={"tel": "", "email": "x@ejemplo.test"})
    ids = sorted(x["id"] for x in nuevas)
    ok(ids == ["L1", "L3"], f"su municipio + organismo regional, ni otro ayuntamiento ni otro sector ({ids})")
    txt = open(rt, encoding="utf-8").read()
    ok(txt.startswith("Asunto: ") and "NUEVAS ESTA SEMANA (2)" in txt and "https://ejemplo.test/1" in txt,
       "texto para pegar en el correo")
    ok(os.path.exists(rp) and "Licitaciones de la semana" in texto_pdf(rp), "resumen en PDF")
    p = PG.leer_perfil(carpeta, "cliente@ejemplo.test")
    rp2, rt2, nuevas2, siguen2 = PG.resumen(carpeta, p, lic[:4] + [dict(lic[0], id="L5", titulo="Limpieza de la piscina")],
                                            datetime(2026, 11, 11, 10, 0), contacto={})
    ok([x["id"] for x in nuevas2] == ["L5"] and sorted(x["id"] for x in siguen2) == ["L1", "L3"],
       "la semana siguiente: solo la nueva arriba, las demás en «siguen abiertas»")
    solo = PG.alta(carpeta, "otro@ejemplo.test", cpvs=["9091"], municipios=["Villaprueba"], solo_municipios=True)
    _, _, n3, _ = PG.resumen(carpeta, solo, lic[:4], ahora, contacto={}, marcar=False)
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

    # caché de los ZIP: solo se relee un ZIP si cambia (o si cambia el lector)
    lecturas = []
    reales = I._leer_zip, I._huella_lector

    def leer_falso(ruta):
        lecturas.append(ruta)
        return {"A": dict(id="A", actualizado="2026-11-01", estado="PUB", provincia="murcia", fin_plazo="2026-12-01 14:00",
                          titulo="Limpieza", cpvs=["90911200"], cpv="90911200", req={"clas": ["U-1"]}),
                "B": dict(id="B", actualizado="2026-11-01", estado="PUB", provincia="madrid", fin_plazo="2026-12-01 14:00"),
                "C": dict(id="C", actualizado="2026-11-02", estado="BORRADA")}
    I._leer_zip = leer_falso
    try:
        zp = os.path.join(d, "place", "place_202611.zip")
        os.makedirs(os.path.dirname(zp))
        with open(zp, "wb") as f:
            f.write(b"zip de prueba")
        sin = I.cargar_licitaciones([zp], "murcia", ahora, cache=False)
        a1 = I.cargar_licitaciones([zp], "murcia", ahora)
        a2 = I.cargar_licitaciones([zp], "murcia", ahora)
        ok(len(lecturas) == 2 and a1 == a2 == sin and [x["id"] for x in a1] == ["A"],
           "caché: la segunda vez no relee el ZIP y da lo mismo que sin caché")
        ok(os.path.exists(os.path.join(d, "place", I.CACHE_LICITACIONES)), "la caché queda junto a los ZIP")
        os.utime(zp, (time.time() + 60, time.time() + 60))
        I.cargar_licitaciones([zp], "murcia", ahora)
        ok(len(lecturas) == 3, "si el ZIP cambia (fecha o tamaño), se vuelve a leer")
        I._huella_lector = lambda: "otro-lector"
        I.cargar_licitaciones([zp], "murcia", ahora)
        ok(len(lecturas) == 4, "si cambia el código que lee los ZIP, se vuelve a leer")
        # un ZIP posterior con la misma licitación en otra provincia manda, igual que sin caché
        zp2 = os.path.join(d, "place", "place_202612.zip")
        with open(zp2, "wb") as f:
            f.write(b"otro zip")
        I._leer_zip = lambda r: ({"A": dict(id="A", actualizado="2026-11-05", estado="PUB", provincia="madrid")}
                                 if r == zp2 else leer_falso(r))
        ok(I.cargar_licitaciones([zp, zp2], "murcia", ahora) == I.cargar_licitaciones([zp, zp2], "murcia", ahora,
                                                                                   cache=False) == [],
           "caché: la versión más nueva manda aunque sea de otra provincia")
    finally:
        I._leer_zip, I._huella_lector = reales

    # hoja para dejar en las visitas: una página, precios y contacto
    import hoja_visita as H
    hojas = H.generar_hojas(contratos, lic, d, "2024-10-10", "2026-10-10", ahora,
                            {"tel": "600 000 000", "email": "contacto@ejemplo.test", "web": "ejemplo.test"},
                            ["Limpieza", "Transporte"])
    ruta_h = hojas[0][1]
    th = texto_pdf(ruta_h)
    ok(paginas(ruta_h) == 1 and hojas[0][2], "hoja de visita: una página y con ejemplo real")
    ok(all(t in th for t in ("Licitaciones para tu empresa", "15 €", "150 €", "25 €", "250 €", "sin IVA",
                             "primer mes, gratis", "600 000 000", "contacto@ejemplo.test")),
       "hoja de visita: qué es, precios, IVA, mes gratis y contacto")
    ok(("Limpieza de colegios" in th or "limpieza del polideportivo" in th) and "Armada" not in th
       and "Servicio Murciano" not in th, "hoja de visita: el ejemplo es de un ayuntamiento y habla del sector")
    ok(not hojas[1][2] and paginas(hojas[1][1]) == 1, "sector sin licitaciones abiertas: hoja sin ejemplo")
    ok(H.PRECIOS == (("Semanal", H.PRECIOS[0][1], 15, 150), ("Diario", H.PRECIOS[1][1], 25, 250)),
       "precios: 15/150 semanal y 25/250 diario")

    # correo para después de la llamada: uno por empresa, con 2 licitaciones de su ficha y el informe a adjuntar
    import correo_llamada as C
    carpeta_c = os.path.join(salida, C.CARPETA_CORREOS)
    os.makedirs(carpeta_c, exist_ok=True)
    for nombre in ("99 - DE UNA LISTA VIEJA.txt", "mis notas.txt"):
        with open(os.path.join(carpeta_c, nombre), "w", encoding="utf-8") as f:
            f.write("x")
    rutas_c = C.escribir(salida, el, ahora, "Firma De Prueba", "600 000 000", os.path.join(d, "por sector"))
    ok(len(rutas_c) == len(el) and sorted(os.listdir(carpeta_c)) == sorted(
        [os.path.basename(r) for r in rutas_c] + ["mis notas.txt"]),
       "un .txt por empresa; se quita el de una lista vieja y no se toca otro fichero de la carpeta")
    tc = open(rutas_c[0], encoding="utf-8-sig").read()
    lics_c = L.licitaciones_ficha(el[0], k=2, ahora=ahora)
    asunto_c = next(x for x in tc.splitlines() if x.startswith("Asunto: "))
    ok("LIMPIEZAS PRUEBA" in asunto_c.upper() and "Licitaciones para tu empresa" in asunto_c, "asunto con su nombre")
    ok("me pidió por teléfono" in tc and "SOLO PARA DESPUÉS DE LA LLAMADA" in tc and "No lo mandes" in tc,
       "dice que lo pidió por teléfono y avisa de no mandarlo a quien no lo pidió")
    ok(len(lics_c) == 2 and all(I.bonito(x["titulo"], 200) in tc and x["url"] in tc for x in lics_c),
       "menciona 2 licitaciones abiertas de su ficha, con enlace")
    ok("ADJUNTAR: " + os.path.join(d, "por sector", L.nombre_informe_sector(el[0]["sector"])) in tc,
       "indica qué PDF del sector adjuntar")
    ok("mes gratis" in tc and "qué municipios y qué actividad" in tc, "ofrece el mes gratis y pregunta qué vigilar")
    ok(tc.rstrip().endswith("Firma De Prueba\nDinero Público\n600 000 000\ncontacto@dinero-publico.com"), "firma")
    ok("quedan" not in tc, "sin «quedan N días» (el correo se manda más tarde): la fecha del plazo")

    # copia de la base: descarga reanudable, huella, sin tocar nada si algo va mal (servidor simulado, sin red)
    import bajar_copia_base as B
    import hashlib
    import io
    import urllib.error
    bdir = os.path.join(d, "base")
    os.makedirs(bdir)
    with open(os.path.join(bdir, "cache_produccion.db"), "wb") as f:
        f.write(b"vieja")
    nueva_db = os.path.join(d, "servidor.db")
    db = sqlite3.connect(nueva_db)
    db.execute("CREATE TABLE municipios (municipio TEXT, provincia TEXT, data TEXT)")
    db.execute("CREATE TABLE contratos_menors_locales (provincia TEXT)")
    db.execute("INSERT INTO municipios VALUES ('x', 'murcia', '{}')")
    db.execute("INSERT INTO contratos_menors_locales VALUES ('murcia')")
    db.commit()
    db.close()
    datos = open(nueva_db, "rb").read()
    sha = hashlib.sha256(datos).hexdigest()
    pedidas = []

    class Resp(io.BytesIO):
        def __init__(self, cuerpo, status, cortar=False):
            super().__init__(cuerpo)
            self.status, self.cortar = status, cortar
            self.headers = {"X-Cache-Db-Sha256": sha, "Content-Length": str(len(cuerpo))}

        def read(self, n=-1):
            if self.cortar and self.tell() >= len(self.getvalue()) // 2:
                raise ConnectionResetError("corte simulado")
            return super().read(min(n, 512) if n and n > 0 else n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen_falso(req, timeout=None):
        cab = {k.lower(): v for k, v in req.header_items()}
        pedidas.append(cab)
        if cab.get("x-admin-token") != "buen-token":
            raise urllib.error.HTTPError(req.full_url, 403, "No autorizado", {}, None)
        if "range" in cab:
            ini = int(cab["range"][6:-1])
            return Resp(datos[ini:], 206)
        return Resp(datos, 200, cortar=len(pedidas) == 1)      # la primera descarga se corta a medias
    real_urlopen, real_sleep = B.urllib.request.urlopen, B.time.sleep
    B.urllib.request.urlopen, B.time.sleep = urlopen_falso, lambda s: None
    try:
        try:
            B.main(["--base", bdir, "--token", "token-malo"])
            ok(False, "token malo: se para")
        except SystemExit as ex:
            ok("403" in str(ex) and open(os.path.join(bdir, "cache_produccion.db"), "rb").read() == b"vieja",
               "token malo: se para sin tocar la copia que había")
        pedidas.clear()
        B.main(["--base", bdir, "--token", "buen-token"])
        ok(any("range" in p for p in pedidas), "corte a medias: reanuda donde se quedó (Range)")
        ok(open(os.path.join(bdir, "cache_produccion.db"), "rb").read() == datos,
           "copia nueva en su sitio y con la huella del servidor")
        viejas = [x for x in os.listdir(bdir) if x.startswith("cache_produccion_") and x.endswith(".db")]
        ok(len(viejas) == 1 and open(os.path.join(bdir, viejas[0]), "rb").read() == b"vieja",
           "la copia anterior se guarda con su fecha, no se borra")
        ok(not [x for x in os.listdir(bdir) if x.endswith((".part", ".sha256"))], "no quedan restos de la descarga")
        try:
            B.main(["--base", bdir, "--token", "TU_TOKEN_AQUI"])
            ok(False, "TU_TOKEN_AQUI sin cambiar: se para")
        except SystemExit:
            ok(True, "TU_TOKEN_AQUI sin cambiar: se para sin conectarse")
    finally:
        B.urllib.request.urlopen, B.time.sleep = real_urlopen, real_sleep
    src2 = "".join(open(m.__file__, encoding="utf-8").read() for m in (H, B, C))
    ok("620" not in src2 and "buen-token" not in src2 and "Firma De Prueba" not in src2,
       "ni teléfono, ni token, ni la firma escritos en el código nuevo (llegan como parámetros)")
    print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'} (ficheros en {d})")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
