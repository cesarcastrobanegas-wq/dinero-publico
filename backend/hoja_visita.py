# encoding: utf-8
"""
Hoja para dejar en las visitas: «Licitaciones para tu empresa» en UNA página A4, blanco y negro (HERRAMIENTA LOCAL,
2026-11-05; la web no la usa).

Qué es el servicio, un ejemplo REAL del sector (una licitación abierta hoy en la Región, con al menos 3 días de plazo,
mejor de un ayuntamiento), el tamaño del sector en la Región, los precios y el contacto. Se genera para cualquier
sector de informe_mercado.SECTORES. El teléfono NO se escribe aquí (el repositorio es público): --contacto-tel.

Uso: python backend/hoja_visita.py --base CARPETA (--sector "Limpieza" ... | --todos) [--contacto-tel "TELÉFONO"]
     (lee <base>/cache_produccion.db y los ZIP de <base>/llamadas/place; escribe en <base>/hojas para visitas)
"""
import argparse
import glob
import os
import re
import sys
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402
import llamadas as L  # noqa: E402

PRODUCTO = "Licitaciones para tu empresa"
# Precios que fijó el titular el 05-11-2026 (sin IVA). Cambiarlos aquí si cambian.
PRECIOS = (("Semanal", "un correo a la semana con las licitaciones nuevas", 15, 150),
           ("Diario", "un correo cada día con las licitaciones nuevas", 25, 250))
MESES_GRATIS = 1
CARPETA_HOJAS = "hojas para visitas"
_RX_AYTO = re.compile(r"\b(ayuntamiento|ajuntament|mancomunidad|junta de gobierno local)\b", re.I)


def ejemplo(abiertas, ahora, sector=None, margen_dias=L.MARGEN_DIAS):
    """La licitación abierta que mejor sirve de ejemplo: con margen de plazo, que su título hable de la actividad
    del sector (sus palabras clave), mejor de un ayuntamiento y con importe razonable para una pyme (5.000 a
    300.000 €)."""
    corte = (ahora + timedelta(days=margen_dias)).strftime("%Y-%m-%d %H:%M")
    con_margen = [x for x in abiertas if (x.get("fin_plazo") or "") >= corte]
    rx = dict(I._POR_PALABRAS).get(sector)

    def clave(x):
        imp = I._f(x.get("presupuesto"))
        habla = bool(rx.search(I.norm(x.get("titulo")))) if rx else bool(I.sector_por_texto(x.get("titulo")))
        return (not habla, not _RX_AYTO.search(x.get("organo") or ""), not (5000 <= imp <= 300000),
                x.get("fin_plazo") or "")
    return min(con_margen, key=clave) if con_margen else None


def hoja_pdf(ruta, sector, A, desde, hasta, ahora, contacto):
    """Escribe la hoja de un sector. A = informe_mercado.analizar(...) del sector. Devuelve el nº de páginas (1)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    st, colors = L._estilos()
    fuente = st["p"].fontName
    negrita = st["h0"].fontName
    st = dict(st, titulo=ParagraphStyle("titulo", fontName=negrita, fontSize=28, leading=33, spaceAfter=6),
              lema=ParagraphStyle("lema", fontName=fuente, fontSize=13.5, leading=18, spaceAfter=16),
              h2=ParagraphStyle("h2", fontName=negrita, fontSize=13.5, leading=17, spaceAfter=4),
              p2=ParagraphStyle("p2", fontName=fuente, fontSize=11.5, leading=15.5, spaceAfter=5),
              li2=ParagraphStyle("li2", fontName=fuente, fontSize=11.5, leading=15.5, leftIndent=13, bulletIndent=0,
                                 spaceAfter=5),
              precio=ParagraphStyle("precio", fontName=negrita, fontSize=15, leading=19),
              grande=ParagraphStyle("grande", fontName=negrita, fontSize=17, leading=23, spaceAfter=3))
    P = lambda t, s="p2": Paragraph(t, st[s])        # noqa: E731
    E = escape
    ancho = A4[0] - 3.2 * cm
    gris = colors.Color(.92, .92, .92)
    h = [P(E(PRODUCTO), "titulo"),
         P(E(f"Las licitaciones públicas de {sector.lower()}, en tu correo. Región de Murcia."), "lema")]
    h += [P("<b>Qué es</b>", "h2"),
          Paragraph(E("Te mandamos por correo las licitaciones públicas abiertas de tu sector en los municipios que "
                      "elijas, para que no se te pase ninguna."), st["li2"], bulletText="•"),
          Paragraph(E("Con lo esencial de cada una: quién la convoca, importe, hasta cuándo puedes presentarte, "
                      "requisitos y el enlace al anuncio oficial."), st["li2"], bulletText="•"),
          Paragraph(E("Datos públicos de la Plataforma de Contratación del Sector Público. Sin buscar perfil por "
                      "perfil."), st["li2"], bulletText="•"), Spacer(1, 12)]
    x = ejemplo(A["abiertas"], ahora, sector)
    if x:
        imp = I._f(x.get("presupuesto"))
        caja = [P(E(f"Ejemplo real de esta semana (abierta el {ahora:%d/%m/%Y})"), "h2"),
                P(f"<b>{E(I.bonito(x.get('titulo') or '', 220))}</b>"),
                P(E(" · ".join(t for t in (I.organismo_corto(x.get("organo")),
                                           f"{I.eur(imp)} sin IVA" if imp else "",
                                           L.plazo_txt(x, ahora)) if t))),
                P(E(f"Requisitos: {I.requisitos_txt(x)}"), "p"),
                P(f"<font size=8>{E(x.get('url') or '')}</font>", "p")]
        t = Table([[caja]], colWidths=[ancho])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, colors.black), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        h += [t, Spacer(1, 14)]
    otras = len(A["abiertas"]) - (1 if x else 0)
    h += [P(f"<b>{E(sector)} en la Región de Murcia</b>", "h2"),
          P(E(f"Del {I.fecha_corta(desde)} al {I.fecha_corta(hasta)}, ayuntamientos y organismos de la Región "
              f"adjudicaron {I.num(len(A['contratos']))} contratos de este sector por {I.eur(A['importe'])} "
              f"({I.num(A['n_menores'])} de ellos, contratos menores) a {I.num(len(A['ranking']))} empresas."
              + (f" Hoy hay {otras} {'licitación abierta' if otras == 1 else 'licitaciones abiertas'} más."
                 if otras > 0 else ""))), Spacer(1, 14)]
    filas = [[P("<b>Plan</b>", "p"), P("<b>Al mes</b>", "p"), P("<b>Al año</b>", "p")]]
    for nombre, que, mes, anio in PRECIOS:
        filas.append([P(f"<b>{E(nombre)}</b><br/><font size=8.5>{E(que)}</font>", "p2"),
                      P(f"{mes} €", "precio"), P(f"{anio} €", "precio")])
    tp = Table(filas, colWidths=[ancho * .56, ancho * .22, ancho * .22])
    tp.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .6, colors.black), ("BACKGROUND", (0, 0), (-1, 0), gris),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    h += [P("<b>Precios</b>", "h2"), tp,
          P(E(f"Precios sin IVA. {'El primer mes' if MESES_GRATIS == 1 else f'Los primeros {MESES_GRATIS} meses'}"
              f", gratis."), "p2"), Spacer(1, 16)]
    lineas = [P(E(f"Pruébalo {'un mes' if MESES_GRATIS == 1 else f'{MESES_GRATIS} meses'} gratis"), "grande")]
    if contacto.get("tel"):
        lineas.append(P(E(f"Teléfono: {contacto['tel']}"), "precio"))
    if contacto.get("email"):
        lineas.append(P(E(f"Correo: {contacto['email']}"), "precio"))
    if contacto.get("web"):
        lineas.append(P(E(contacto["web"]), "p2"))
    tc = Table([[lineas]], colWidths=[ancho])
    tc.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.5, colors.black), ("BACKGROUND", (0, 0), (-1, -1), gris),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    h += [tc, Spacer(1, 14),
          P(E("Dinero Público. Información orientativa sacada de datos públicos: antes de presentarse a una "
              "licitación hay que leer su pliego."), "pc")]
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.2 * cm, title=f"{PRODUCTO} - {sector}", author="Dinero Público")
    marco = KeepInFrame(ancho, A4[1] - 2.7 * cm, h, mode="shrink")     # siempre UNA página
    doc.build([marco])
    return 1


def generar_hojas(contratos, licitaciones, base, desde, hasta, ahora, contacto, sectores):
    """Una hoja por sector en <base>/hojas para visitas. Devuelve [(sector, ruta o None si no hay ejemplo)]."""
    carpeta = os.path.join(base, CARPETA_HOJAS)
    os.makedirs(carpeta, exist_ok=True)
    del_periodo = [r for r in contratos if desde <= r["fecha"] <= hasta]
    res = []
    for s in sectores:
        A = I.analizar(del_periodo, licitaciones, sector=s)
        ruta = os.path.join(carpeta, L.nombre_hoja_visita(s))
        hoja_pdf(ruta, s, A, desde, hasta, ahora, contacto)
        res.append((s, ruta, ejemplo(A["abiertas"], ahora, s) is not None))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--sector", action="append", default=[])
    ap.add_argument("--todos", action="store_true", help="todos los sectores")
    ap.add_argument("--contacto-tel", default=I.CONTACTO_TEL)
    a = ap.parse_args(argv)
    sectores = I.NOMBRES_SECTOR if a.todos else a.sector
    for s in sectores:
        if s not in I.NOMBRES_SECTOR:
            ap.error(f"Sector desconocido: {s}. Sectores: {', '.join(I.NOMBRES_SECTOR)}")
    if not sectores:
        ap.error("Indica --sector o --todos")
    db = os.path.join(a.base, "cache_produccion.db")
    hasta = date.fromtimestamp(os.path.getmtime(db)).isoformat()
    desde = f"{int(hasta[:4]) - 2}{hasta[4:]}"
    ahora = datetime.now()
    zips = sorted(glob.glob(os.path.join(a.base, "llamadas", "place", "place_*.zip")))[-2:]
    lic = I.cargar_licitaciones(zips, "murcia", ahora)
    contratos = I.cargar_contratos(db, "murcia", desde, hasta)
    contacto = {"tel": a.contacto_tel, "email": I.CONTACTO_EMAIL, "web": I.CONTACTO_WEB}
    for s, ruta, con_ejemplo in generar_hojas(contratos, lic, a.base, desde, hasta, ahora, contacto, sectores):
        print(f"{ruta}{'' if con_ejemplo else '  (hoy no hay ninguna abierta con margen: sale sin ejemplo)'}")


if __name__ == "__main__":
    main()
