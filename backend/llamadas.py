# encoding: utf-8
"""
Lista de llamadas y fichas de llamada para vender por teléfono (HERRAMIENTA LOCAL, 2026-11-04; la web no la usa).

De la lista de clientes potenciales (CSV de sociedades con sede en la provincia, fuera del repositorio) saca las N más
prometedoras y genera, en la carpeta de salida:
  «Lista de llamadas.xlsx»   una fila por empresa, con columnas vacías para apuntar la llamada;
  «Lista de llamadas.pdf»    lo mismo para imprimir (A4 apaisado, blanco y negro);
  «Fichas de llamada.pdf»    media página por empresa: el gancho («el último año ganó X contratos por X €») y 2 o 3
                             licitaciones ABIERTAS ahora en su sector y en la provincia, con su plazo.
y mantiene, también en la carpeta de salida (ficheros locales, nunca en git):
  «excluidas.txt»            CIF o razón social de las que no deben salir nunca (se respeta siempre);
  «Seguimiento de llamadas.xlsx»  lo apuntado, una fila por empresa. Solo se le AÑADEN empresas nuevas y lo apuntado
                             en la lista anterior (en celdas vacías); nunca se borra nada. La lista nueva sale con
                             esas columnas rellenas.

Criterio (lo pidió el titular el 04-11): contratos ganados con ayuntamientos y organismos de la provincia desde el 1 de
enero de 2024 (número e importe, menores incluidos), peso del sector en los contratos menores municipales y, para que
la ficha tenga gancho, que haya licitaciones abiertas que le encajen. SOLO sociedades (NIF de persona jurídica y forma
social); nunca personas físicas. Como mucho MAX_POR_SECTOR por sector, para que la lista no sea toda de lo mismo.
Teléfono y web: solo si constan en el Excel de contactos corporativos revisados a mano (--contactos); si no, en
blanco. Nada de datos de personas.

Uso: python backend/llamadas.py --db COPIA.db --zip place_AAAAMM.zip [--zip ...] --clientes CLIENTES.csv
                                 --salida CARPETA [--contactos CONTACTOS.xlsx] [--n 30] [--hasta AAAA-MM-DD]
"""
import argparse
import collections
import csv
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402

DESDE_POR_DEFECTO = "2024-01-01"
MAX_POR_SECTOR = 6
COLUMNAS_APUNTAR = ("Fecha de llamada", "Con quién hablé", "Correo (si me lo da)", "Interesado (sí/no)",
                    "Volver a llamar el", "Notas")
_RE_TEL = re.compile(r"(?<!\d)(?:\+34[ .]?)?([6789]\d{2}[ .]?\d{2,3}[ .]?\d{2,3}[ .]?\d{0,3})(?!\d)")
_RE_WEB = re.compile(r"(https?://[^\s;,]+|www\.[^\s;,]+)", re.I)


def leer_clientes(ruta):
    """{nif: fila} del CSV de clientes potenciales (separador «;», UTF-8)."""
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return {I.nif_ok(r.get("nif")): r for r in csv.DictReader(f, delimiter=";") if I.nif_ok(r.get("nif"))}


def leer_contactos(ruta):
    """{nif: {"tel", "web", "fuente"}} del Excel de contactos corporativos (columnas NIF, Web, Contacto corporativo,
    Fuente, Fecha de comprobación). Solo teléfonos y webs que estén escritos; nunca se deduce nada."""
    if not ruta or not os.path.exists(ruta):
        return {}
    import openpyxl
    wb = openpyxl.load_workbook(ruta, read_only=True)
    ws = wb.worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    cab = [str(c or "").strip().lower() for c in filas[0]]

    def col(*nombres):
        for i, c in enumerate(cab):
            if any(c.startswith(n) for n in nombres):
                return i
        return None
    i_nif, i_web, i_cont = col("nif"), col("web"), col("contacto")
    i_fuente, i_fecha = col("fuente"), col("fecha")
    res = {}
    for f in filas[1:]:
        nif = I.nif_ok(f[i_nif] if i_nif is not None else "")
        if not nif:
            continue
        web = str(f[i_web] or "").strip() if i_web is not None else ""
        web = web if _RE_WEB.search(web) or re.search(r"\.[a-z]{2,4}(/|$)", web) else ""
        cont = str(f[i_cont] or "") if i_cont is not None else ""
        m = _RE_TEL.search(cont)
        tel = re.sub(r"[ .]", " ", m.group(1)).strip() if m else ""
        fuente = " ".join(str(x) for x in (f[i_fuente] if i_fuente is not None else "",
                                           f[i_fecha] if i_fecha is not None else "") if x).strip()
        if tel or web:
            res[nif] = {"tel": tel, "web": web, "fuente": fuente or "web de la empresa"}
    return res


def _municipio(r):
    o = r["organismo"]
    m = re.match(r"(?i)ayuntamiento de (.+)", o)
    if m:
        return m.group(1).strip()
    if not r.get("municipio"):
        return o
    palabras = (r["municipio"] or "").title().split()
    menores = {"De", "Del", "La", "Las", "Los", "El", "Y"}      # en minúscula salvo al principio
    return " ".join(w.lower() if i and w in menores else w for i, w in enumerate(palabras))


def candidatos(contratos, licitaciones, clientes, hasta):
    """Una entrada por sociedad de la lista de clientes con contratos en el periodo, con su puntuación."""
    # peso de cada sector en los contratos menores de los ayuntamientos
    menores_muni = collections.Counter(r["sector"] for r in contratos if r["tipo"] == "menor"
                                       and r["organismo"].lower().startswith("ayuntamiento") and r["sector"] != "Otros")
    tope_sector = max(menores_muni.values() or [1])
    hace_un_anio = (date.fromisoformat(hasta) - timedelta(days=365)).isoformat()
    por_nif = collections.defaultdict(list)
    for r in contratos:
        if r["nif"] in clientes and r["sociedad"]:
            por_nif[r["nif"]].append(r)
    res = []
    for nif, propios in por_nif.items():
        fila = clientes[nif]
        nombre = collections.Counter(r["nombre"] for r in propios).most_common(1)[0][0]
        if nif[0] not in I.LETRAS_SOCIEDAD or not I.es_sociedad(nif, nombre):
            continue
        try:
            A = I.analizar(contratos, licitaciones, nif=nif)
        except SystemExit:
            continue
        sector = A["sectores"][0]
        anio = [r for r in propios if r["fecha"] >= hace_un_anio]
        munis = collections.Counter(_municipio(r) for r in propios)
        e = dict(nif=nif, nombre=nombre, sector=sector, sectores=A["sectores"], fila=fila,
                 n=len(propios), importe=sum(r["importe"] for r in propios),
                 n_menores=sum(1 for r in propios if r["tipo"] == "menor"),
                 n_anio=len(anio), importe_anio=sum(r["importe"] for r in anio),
                 municipios=munis, abiertas=A["abiertas"], ultimo=max(r["fecha"] for r in propios),
                 peso_sector=menores_muni.get(sector, 0) / tope_sector)
        res.append(e)
    if not res:
        return []
    # puntuación: percentiles de número e importe + peso del sector en menores municipales + que haya licitaciones
    # abiertas que le encajen + actividad reciente
    orden_n = sorted(x["n"] for x in res)
    orden_i = sorted(x["importe"] for x in res)

    def pct(lista, v):
        return sum(1 for x in lista if x <= v) / len(lista)
    reciente = (date.fromisoformat(hasta) - timedelta(days=180)).isoformat()
    for e in res:
        e["puntos"] = round(100 * (0.30 * pct(orden_n, e["n"]) + 0.25 * pct(orden_i, e["importe"])
                                   + 0.20 * e["peso_sector"] + 0.15 * min(len(e["abiertas"]), 3) / 3
                                   + 0.10 * (1 if e["ultimo"] >= reciente else 0)), 1)
    return sorted(res, key=lambda e: (-e["puntos"], -e["importe"]))


def elegir(cands, n=30, max_por_sector=MAX_POR_SECTOR):
    elegidas, por_sector = [], collections.Counter()
    for e in cands:
        if por_sector[e["sector"]] >= max_por_sector:
            continue
        elegidas.append(e)
        por_sector[e["sector"]] += 1
        if len(elegidas) == n:
            break
    return elegidas


MARGEN_DIAS = 3      # en la ficha, solo licitaciones a las que aún le da tiempo a presentarse


def licitaciones_ficha(e, k=3, ahora=None, margen_dias=MARGEN_DIAS):
    """Las 2-3 licitaciones abiertas que mejor le van: con al menos `margen_dias` de plazo, primero las de los
    municipios donde ya gana y luego por plazo. Si ninguna tiene margen, las que haya."""
    munis = {I.norm(m) for m in e["municipios"]}
    corte = ((ahora or datetime.now()) + timedelta(days=margen_dias)).strftime("%Y-%m-%d %H:%M")
    con_margen = [x for x in e["abiertas"] if (x.get("fin_plazo") or "") >= corte]

    def suya(lic):
        o = I.norm(lic.get("organo") or "")
        return any(m and m in o for m in munis)
    return sorted(con_margen or e["abiertas"], key=lambda x: (not suya(x), x.get("fin_plazo") or ""))[:k]


def plazo_txt(lic, ahora):
    f = lic.get("fin_plazo") or ""
    try:
        fin = datetime.strptime(f, "%Y-%m-%d %H:%M")
    except ValueError:
        return "plazo: ver anuncio"
    dias = (fin.date() - ahora.date()).days
    cuando = "hoy" if dias == 0 else "mañana" if dias == 1 else f"quedan {dias} días"
    return f"hasta el {fin:%d/%m/%Y} a las {fin:%H:%M} ({cuando})"


def municipios_txt(e, k=4):
    top = [m for m, _ in e["municipios"].most_common(k)]
    resto = len(e["municipios"]) - len(top)
    return ", ".join(top) + (f" y {resto} más" if resto > 0 else "")


# ───────────────────────────── salidas ─────────────────────────────

def _txt(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    return "" if v is None else str(v)


def escribir_xlsx(ruta, elegidas, contactos, desde, hasta, ahora, seg=None):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Llamadas"
    cab = ["Nº", "Razón social", "NIF", "Sector", "Municipios / organismos donde ha ganado",
           f"Contratos {fecha_c(desde)}–{fecha_c(hasta)}", "De ellos, menores", "Importe (€)",
           "Último año: contratos", "Último año: importe (€)", "Licitaciones abiertas que le encajan", "Teléfono",
           "Web", "Fuente del contacto"] + list(COLUMNAS_APUNTAR)
    ws.append(cab)
    for i, e in enumerate(elegidas, 1):
        c = contactos.get(e["nif"], {})
        ws.append([i, I.nombre_empresa(e["nombre"]), e["nif"], e["sector"], municipios_txt(e, 6), e["n"],
                   e["n_menores"], round(e["importe"], 2), e["n_anio"], round(e["importe_anio"], 2),
                   len(e["abiertas"]), c.get("tel", ""), c.get("web", ""), c.get("fuente", "") if c else ""]
                  + [apuntado(seg or {}, e).get(col) for col in COLUMNAS_APUNTAR])
    fino = Side(style="thin", color="999999")
    for celda in ws[1]:
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="DDDDDD")
        celda.alignment = Alignment(wrap_text=True, vertical="top")
    anchos = [4, 34, 11, 22, 34, 10, 9, 13, 9, 13, 10, 13, 24, 18, 12, 18, 24, 10, 12, 30]
    for j, a in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(j)].width = a
    for fila in ws.iter_rows(min_row=2):
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, vertical="top")
            celda.border = Border(bottom=fino)
        fila[7].number_format = fila[9].number_format = "#,##0"
        for celda in fila[14:]:
            if isinstance(celda.value, (datetime, date)):
                celda.number_format = "DD/MM/YYYY"
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    nota = wb.create_sheet("Cómo se ha hecho")
    for linea in nota_metodo(desde, hasta, ahora):
        nota.append([linea])
    nota.column_dimensions["A"].width = 120
    wb.save(ruta)


def fecha_c(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


def nota_metodo(desde, hasta, ahora):
    return [
        f"Lista generada el {ahora:%d/%m/%Y %H:%M} con datos públicos.",
        f"Contratos: los que la base de Dinero Público tiene adjudicados del {fecha_c(desde)} al {fecha_c(hasta)} por "
        "ayuntamientos y organismos de la Región de Murcia (formales y menores).",
        "Licitaciones abiertas: las de la Plataforma de Contratación del Sector Público (PLACE) en plazo en el momento "
        "de generar la lista, en la Región de Murcia, que encajan con el sector de la empresa.",
        "Puntuación: número de contratos (30 %), importe (25 %), peso del sector en los contratos menores municipales "
        "(20 %), licitaciones abiertas que le encajan (15 %) y contratos en los últimos seis meses (10 %). "
        f"Como mucho {MAX_POR_SECTOR} empresas por sector.",
        "Solo sociedades (NIF de persona jurídica). Ningún dato de personas.",
        "Teléfono y web: solo los que constan en la lista de contactos corporativos revisada a mano el 25-10-2026 "
        "(web de cada empresa). Si no constan, en blanco: búscalos en su web antes de llamar.",
        "Los datos son de quién GANA contratos; no hay datos públicos reutilizables de quién se presenta y pierde.",
    ]


def _estilos():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fuente, negrita = "Helvetica", "Helvetica-Bold"
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.exists(os.path.join(d, "arial.ttf")) and os.path.exists(os.path.join(d, "arialbd.ttf")):
        pdfmetrics.registerFont(TTFont("Arial", os.path.join(d, "arial.ttf")))
        pdfmetrics.registerFont(TTFont("Arial-Bold", os.path.join(d, "arialbd.ttf")))
        fuente, negrita = "Arial", "Arial-Bold"
    gris = colors.Color(.35, .35, .35)
    return {
        "h0": ParagraphStyle("h0", fontName=negrita, fontSize=15, leading=18, spaceAfter=2),
        "h1": ParagraphStyle("h1", fontName=negrita, fontSize=12, leading=14, spaceAfter=1),
        "sub": ParagraphStyle("sub", fontName=fuente, fontSize=8.5, leading=11, textColor=gris, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=fuente, fontSize=9, leading=12, spaceAfter=3),
        "gancho": ParagraphStyle("gancho", fontName=negrita, fontSize=10.5, leading=13.5, spaceAfter=4),
        "td": ParagraphStyle("td", fontName=fuente, fontSize=7, leading=8.6),
        "tdb": ParagraphStyle("tdb", fontName=negrita, fontSize=7, leading=8.6),
        "th": ParagraphStyle("th", fontName=negrita, fontSize=6.6, leading=8),
        "li": ParagraphStyle("li", fontName=fuente, fontSize=8.6, leading=11, leftIndent=10, bulletIndent=0,
                             spaceAfter=2),
        "pc": ParagraphStyle("pc", fontName=fuente, fontSize=7, leading=9, textColor=gris),
    }, colors


def escribir_pdf_lista(ruta, elegidas, contactos, desde, hasta, ahora, seg=None):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st, colors = _estilos()
    P = lambda t, s="td": Paragraph(t, st[s])        # noqa: E731
    E = escape
    doc = SimpleDocTemplate(ruta, pagesize=landscape(A4), leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1 * cm,
                            bottomMargin=1 * cm, title="Lista de llamadas", author="Dinero Público")
    cab = ["Nº", "Empresa / sector", "Municipios donde ha ganado", "Contratos e importe", "Teléfono / web",
           "Fecha", "Con quién hablé", "Correo", "Interesado", "Volver a llamar"]
    filas = [[P(c, "th") for c in cab]]
    for i, e in enumerate(elegidas, 1):
        c = contactos.get(e["nif"], {})
        a = {k: E(_txt(v)) for k, v in apuntado(seg or {}, e).items()}
        filas.append([P(str(i)), P(f"<b>{E(I.nombre_empresa(e['nombre'], 60))}</b><br/>{E(e['nif'])} · "
                                   f"{E(e['sector'])}"),
                      P(E(municipios_txt(e))),
                      P(f"{e['n']} ({e['n_menores']} menores)<br/>{E(I.eur(e['importe']))}<br/>"
                        f"último año: {e['n_anio']} · {E(I.eur(e['importe_anio']))}"),
                      P(E(c.get("tel", "")) + ("<br/>" + E(c.get("web", "")) if c.get("web") else "")),
                      P(a.get("Fecha de llamada", "")), P(a.get("Con quién hablé", "")),
                      P(a.get("Correo (si me lo da)", "")), P(a.get("Interesado (sí/no)") or "sí / no"),
                      P(a.get("Volver a llamar el", ""))])
    anchos = [0.8, 6.0, 4.6, 3.5, 3.6, 1.7, 3.3, 3.2, 1.4, 1.6]
    t = Table(filas, colWidths=[a * cm for a in anchos], repeatRows=1)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.Color(.88, .88, .88)),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5)]))
    historia = [P("Lista de llamadas — Región de Murcia", "h0"),
                P(E(f"Generada el {ahora:%d/%m/%Y %H:%M}. Contratos del {fecha_c(desde)} al {fecha_c(hasta)}. "
                    "Solo sociedades; teléfono y web solo si constan en la web de la empresa (revisado el 25-10)."),
                  "sub"), t, Spacer(1, 6)]
    historia += [P(E(x), "pc") for x in nota_metodo(desde, hasta, ahora)[2:5]]
    doc.build(historia)


def escribir_pdf_fichas(ruta, elegidas, contactos, desde, hasta, ahora, contacto_tel=""):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Table, TableStyle
    st, colors = _estilos()
    P = lambda t, s="p": Paragraph(t, st[s])        # noqa: E731
    E = escape
    alto_ficha = (A4[1] - 2 * cm) / 2 - 0.3 * cm
    ancho = A4[0] - 2.4 * cm
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1 * cm,
                            bottomMargin=1 * cm, title="Fichas de llamada", author="Dinero Público")
    hace_un_anio = (date.fromisoformat(hasta) - timedelta(days=365)).isoformat()
    historia = []
    for i, e in enumerate(elegidas, 1):
        c = contactos.get(e["nif"], {})
        f = e["fila"]
        sede = f.get("municipio_sede") or ""
        sede = "" if sede.startswith("(sin dato") else sede
        partes = [P(f"{i}. {E(I.nombre_empresa(e['nombre'], 70))}", "h1"),
                  P(E(" · ".join(x for x in (e["nif"], e["sector"], f"sede: {sede}" if sede else "",
                                              f"tel. {c['tel']}" if c.get("tel") else "",
                                              c.get("web", "")) if x)), "sub")]
        gancho = (f"«Del {fecha_c(hace_un_anio)} al {fecha_c(hasta)} ganó {e['n_anio']} "
                  f"{'contrato' if e['n_anio'] == 1 else 'contratos'} públicos por {I.eur(e['importe_anio'])} en la "
                  f"Región de Murcia.»") if e["n_anio"] else (
                  f"«Desde {fecha_c(desde)} ha ganado {e['n']} contratos públicos por {I.eur(e['importe'])} en la "
                  "Región de Murcia (ninguno en el último año).»")
        partes.append(P(E(gancho), "gancho"))
        partes.append(P(E(f"Desde el {fecha_c(desde)}: {e['n']} contratos ({e['n_menores']} menores), "
                          f"{I.eur(e['importe'])}. Donde más: {municipios_txt(e)}.")))
        lics = licitaciones_ficha(e, ahora=ahora)
        if lics:
            partes.append(P(f"<b>{'Licitaciones abiertas ahora' if len(lics) > 1 else 'Licitación abierta ahora'} "
                            f"que podría pedir</b> ({len(e['abiertas'])} en total en su sector en la Región):"))
            for x in lics:
                imp = I._f(x.get("presupuesto"))
                partes.append(Paragraph(
                    f"<b>{E(I.bonito(x.get('titulo') or '', 150))}</b><br/>{E(I.organismo_corto(x.get('organo')))}"
                    f"{' · ' + E(I.eur(imp)) + ' sin IVA' if imp else ''} · <b>{E(plazo_txt(x, ahora))}</b><br/>"
                    f"<font size=6.5>Exp. {E(x.get('expediente') or '')} · {E(x.get('url') or '')}</font>",
                    st["li"], bulletText="•"))
        else:
            partes.append(P("<b>Ahora mismo no hay licitaciones abiertas de su sector en la Región.</b> Ofrecer la "
                            "prueba gratis: le llegarán en cuanto salgan."))
        partes.append(P(E("Qué ofrecer: un mes gratis, cada lunes, las licitaciones abiertas de su sector en sus "
                          "municipios. Apuntar su correo y el sector."
                          + (f" Mi teléfono: {contacto_tel}." if contacto_tel else "")), "pc"))
        caja = Table([[KeepInFrame(ancho - 0.6 * cm, alto_ficha - 0.6 * cm, partes, mode="shrink")]],
                     colWidths=[ancho], rowHeights=[alto_ficha])
        caja.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.75, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                  ("TOPPADDING", (0, 0), (-1, -1), 6)]))
        historia.append(caja)
    doc.build(historia)


# ─────────────────── exclusiones y seguimiento (ficheros LOCALES de la carpeta de salida, fuera de git) ───────────────────

EXCLUIDAS_TXT = "excluidas.txt"                 # una razón social o un CIF por línea; lo que va tras «#» es comentario
SEGUIMIENTO_XLSX = "Seguimiento de llamadas.xlsx"   # lo apuntado; se le AÑADEN filas, nunca se borra ni se rehace
SEGUIMIENTO_COPIA = "Seguimiento de llamadas - copia anterior.xlsx"
COLUMNAS_SEGUIMIENTO = ("Razón social", "NIF", "Sector", "Teléfono", "Web", "En la lista desde") + COLUMNAS_APUNTAR
_FORMAS = {"S", "A", "L", "U", "SA", "SL", "SLU", "SAU", "SLL", "SLP", "SC", "SCOOP", "COOP", "CB", "SOCIEDAD",
           "LIMITADA", "ANONIMA", "UNIPERSONAL", "LABORAL", "COOPERATIVA"}


def norm_razon(nombre):
    """Razón social comparable: sin tildes, mayúsculas, sin puntuación y sin la forma social del final
    («La Opinión de Murcia» == «LA OPINION DE MURCIA, S.A.U.»)."""
    t = unicodedata.normalize("NFKD", str(nombre or "").upper())
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace(".", "")
    pal = re.sub(r"[^A-Z0-9]+", " ", t).split()
    while len(pal) > 1 and pal[-1] in _FORMAS:
        pal.pop()
    return " ".join(pal)


def _es_cif(t):
    n = I.nif_ok(t)
    return n if n and sum(ch.isdigit() for ch in n) >= 7 else ""


def claves(nif, nombre):
    """Claves con las que se reconoce a una empresa: su CIF y su razón social normalizada."""
    k = set()
    if _es_cif(nif):
        k.add("N:" + _es_cif(nif))
    if norm_razon(nombre):
        k.add("R:" + norm_razon(nombre))
    return k


def leer_excluidas(ruta):
    """Claves de las empresas que no deben salir nunca en la lista. Sin fichero, ninguna."""
    fuera = set()
    if not ruta or not os.path.exists(ruta):
        return fuera
    with open(ruta, encoding="utf-8-sig") as f:
        for linea in f:
            t = linea.split("#")[0].strip()
            if t:
                fuera |= {"N:" + _es_cif(t)} if _es_cif(t) else {"R:" + norm_razon(t)}
    return fuera


def _cabecera(ws):
    """{nombre de columna en minúsculas: índice (1..)} de la primera fila; «CIF» vale como «NIF»."""
    cab = {}
    for j, c in enumerate(next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ()), 1):
        t = str(c or "").strip().lower()
        if t:
            cab.setdefault("nif" if t == "cif" else t, j)
    return cab


def _vacio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def notas_de_lista(ruta):
    """Lo apuntado a mano en una «Lista de llamadas.xlsx» anterior (para no perderlo al regenerarla):
    [(claves, {columna: valor})]."""
    if not os.path.exists(ruta):
        return []
    import openpyxl
    wb = openpyxl.load_workbook(ruta)
    ws = wb["Llamadas"] if "Llamadas" in wb.sheetnames else wb.worksheets[0]
    cab = _cabecera(ws)
    out = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        val = lambda col: fila[cab[col.lower()] - 1] if col.lower() in cab and cab[col.lower()] <= len(fila) else None  # noqa: E731,E501
        apunt = {c: val(c) for c in COLUMNAS_APUNTAR if not _vacio(val(c))}
        if apunt:
            out.append((claves(val("NIF"), val("Razón social")), apunt))
    wb.close()
    return out


def actualizar_seguimiento(ruta, elegidas, contactos, notas, ahora):
    """Añade al seguimiento las empresas que aún no están y pasa a él lo apuntado en la lista anterior, SOLO en celdas
    vacías. Nunca borra filas, columnas ni valores. Devuelve {clave: {columna: valor}} con lo apuntado de cada empresa.
    Si no hay nada que añadir, no toca el fichero; si lo toca, antes deja una copia («... - copia anterior.xlsx")."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    existe = os.path.exists(ruta)
    if existe:
        wb = openpyxl.load_workbook(ruta)
        ws = wb.worksheets[0]
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Seguimiento"
    cab = _cabecera(ws)
    cambiado = not existe
    for col in COLUMNAS_SEGUIMIENTO:              # columnas que falten, al final (las que haya puesto él, se quedan)
        if col.lower() not in cab:
            j = max(cab.values(), default=0) + 1
            celda = ws.cell(row=1, column=j, value=col)
            celda.font, celda.fill = Font(bold=True), PatternFill("solid", fgColor="DDDDDD")
            celda.alignment = Alignment(wrap_text=True, vertical="top")
            ws.column_dimensions[get_column_letter(j)].width = 34 if col in ("Razón social", "Notas") else 16
            cab[col.lower()] = j
            cambiado = True
    filas = {}                                    # clave -> nº de fila
    for r in range(2, ws.max_row + 1):
        for k in claves(ws.cell(r, cab["nif"]).value, ws.cell(r, cab["razón social"]).value):
            filas.setdefault(k, r)
    hoy = ahora.strftime("%d/%m/%Y")
    for e in elegidas:
        if not any(k in filas for k in claves(e["nif"], e["nombre"])):
            r = ws.max_row + 1 if ws.max_row > 1 or not _vacio(ws.cell(1, 1).value) else 2
            c = contactos.get(e["nif"], {})
            for col, v in (("Razón social", I.nombre_empresa(e["nombre"])), ("NIF", e["nif"]),
                           ("Sector", e["sector"]), ("Teléfono", c.get("tel", "")), ("Web", c.get("web", "")),
                           ("En la lista desde", hoy)):
                ws.cell(r, cab[col.lower()], v)
            for k in claves(e["nif"], e["nombre"]):
                filas.setdefault(k, r)
            cambiado = True
    for ks, apunt in notas:
        r = next((filas[k] for k in sorted(ks) if k in filas), None)
        if r is None:
            continue
        for col, v in apunt.items():
            celda = ws.cell(r, cab[col.lower()])
            if _vacio(celda.value):
                celda.value = v
                if isinstance(v, (datetime, date)):
                    celda.number_format = "DD/MM/YYYY"
                cambiado = True
    seg = {}
    for r in sorted(set(filas.values())):
        apunt = {c: ws.cell(r, cab[c.lower()]).value for c in COLUMNAS_APUNTAR}
        for k in claves(ws.cell(r, cab["nif"]).value, ws.cell(r, cab["razón social"]).value):
            seg.setdefault(k, apunt)
    if cambiado:
        ws.freeze_panes = "C2"
        try:
            if existe:
                import shutil
                shutil.copy2(ruta, os.path.join(os.path.dirname(ruta), SEGUIMIENTO_COPIA))
            wb.save(ruta)
        except PermissionError:
            raise SystemExit(f"No puedo guardar «{os.path.basename(ruta)}»: ciérralo en Excel y vuelve a regenerar. "
                             "No he cambiado nada de la lista.")
    wb.close()
    return seg


def apuntado(seg, e):
    """Lo apuntado de una empresa en el seguimiento ({} si no hay nada)."""
    return next((seg[k] for k in sorted(claves(e["nif"], e["nombre"])) if k in seg), {})


def generar(contratos, licitaciones, clientes_csv, salida, hasta, ahora, contactos_xlsx=None, n=30, desde=None,
            contacto_tel=""):
    """Escribe las tres salidas en `salida` (y añade al seguimiento las empresas nuevas). Devuelve las elegidas."""
    desde = desde or DESDE_POR_DEFECTO
    contratos = [r for r in contratos if desde <= r["fecha"] <= hasta]
    fuera = leer_excluidas(os.path.join(salida, EXCLUIDAS_TXT))
    clientes = {k: v for k, v in leer_clientes(clientes_csv).items() if not claves(k, v.get("nombre")) & fuera}
    contactos = leer_contactos(contactos_xlsx)
    cands = [c for c in candidatos(contratos, licitaciones, clientes, hasta) if not claves(c["nif"], c["nombre"]) & fuera]
    elegidas = elegir(cands, n)
    os.makedirs(salida, exist_ok=True)
    lista_xlsx = os.path.join(salida, "Lista de llamadas.xlsx")
    seg = actualizar_seguimiento(os.path.join(salida, SEGUIMIENTO_XLSX), elegidas, contactos,
                                 notas_de_lista(lista_xlsx), ahora)
    escribir_xlsx(lista_xlsx, elegidas, contactos, desde, hasta, ahora, seg)
    escribir_pdf_lista(os.path.join(salida, "Lista de llamadas.pdf"), elegidas, contactos, desde, hasta, ahora, seg)
    escribir_pdf_fichas(os.path.join(salida, "Fichas de llamada.pdf"), elegidas, contactos, desde, hasta, ahora,
                        contacto_tel)
    return elegidas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--zip", action="append", default=[])
    ap.add_argument("--clientes", required=True)
    ap.add_argument("--contactos")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--desde", default=DESDE_POR_DEFECTO)
    ap.add_argument("--hasta")
    ap.add_argument("--contacto-tel", default=os.environ.get("INFORME_CONTACTO_TEL", ""))
    a = ap.parse_args(argv)
    ahora = datetime.now()
    hasta = a.hasta or date.fromtimestamp(os.path.getmtime(a.db)).isoformat()
    contratos = I.cargar_contratos(a.db, "murcia", a.desde, hasta)
    lic = I.cargar_licitaciones(a.zip, "murcia", ahora) if a.zip else []
    el = generar(contratos, lic, a.clientes, a.salida, hasta, ahora, a.contactos, a.n, a.desde, a.contacto_tel)
    print(f"{len(el)} empresas; {sum(1 for e in el if e['abiertas'])} con licitaciones abiertas; salida en {a.salida}")


if __name__ == "__main__":
    main()
