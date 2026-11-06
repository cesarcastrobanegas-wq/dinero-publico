# encoding: utf-8
"""
Informe en PDF para un socio: las licitaciones abiertas que encajan con su perfil (resultado de
filtro_licitaciones.filtrar). Encargo de César del 2026-10-27: como lo recibiría un socio de la Cámara.

- Pensado para imprimir en BLANCO Y NEGRO: los grupos se distinguen por símbolo + MAYÚSCULAS + negrita, nunca solo por
  color (no se usa ningún color).
- Máximo MAX_PAGINAS páginas: si no caben todas las fichas, se muestran las que cierran antes de cada grupo y se dice
  cuántas quedan fuera.
- Portada, resumen, una ficha por licitación o lote (por fin de plazo dentro de cada grupo) y aviso final.

Uso: informe_pdf(ruta, perfil_texto, resultados, fecha, muestra=True)
  perfil_texto: [(etiqueta, valor)] con los datos del perfil en lenguaje llano (los arma quien llama).
Fuente: Arial del sistema (lleva tildes, € y los símbolos ● ▲ ■); si no está, Helvetica sin símbolos.
"""
import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

try:
    from . import filtro_licitaciones as F
    from . import licitaciones_place as LIC
except ImportError:
    import filtro_licitaciones as F
    import licitaciones_place as LIC

# los nombres viven en el motor (el formulario de la web los usa y producción no tiene reportlab)
NOMBRE_PROVINCIA, NOMBRE_COMUNIDAD, TIPO_TXT = F.NOMBRE_PROVINCIA, F.NOMBRE_COMUNIDAD, F.TIPO_TXT
lugar_txt, perfil_texto, _agrupar_lotes = F.lugar_txt, F.perfil_texto, F.agrupar_lotes
MAX_PAGINAS = 10
MAX_FICHAS = 40                      # punto de partida; se baja de 5 en 5 hasta caber en MAX_PAGINAS
CUOTAS = ((F.PUEDE, 20), (F.REVISA, 12), (F.UTE, 8))
NEGRO, GRIS = colors.black, colors.Color(0.35, 0.35, 0.35)

GRUPO_TXT = {
    F.PUEDE: ("●", "PUEDE OPTAR", "Cumple lo que se puede comprobar en el anuncio. Revise igualmente el pliego."),
    F.REVISA: ("▲", "REVISA EL PLIEGO", "Encaja con su empresa, pero algo depende de lo que diga el pliego."),
    F.UTE: ("■", "SOLO EN UTE O EN UN LOTE", "Su empresa sola no llega; podría presentarse junto a otra (UTE)."),
}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_FUENTE, _FUENTE_B, _FUENTE_I = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
_SIMBOLOS = False


def _registrar_fuentes():
    global _FUENTE, _FUENTE_B, _FUENTE_I, _SIMBOLOS
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    rutas = {"Arial": "arial.ttf", "Arial-Bold": "arialbd.ttf", "Arial-Italic": "ariali.ttf"}
    if all(os.path.exists(os.path.join(d, f)) for f in rutas.values()):
        for n, f in rutas.items():
            pdfmetrics.registerFont(TTFont(n, os.path.join(d, f)))
        _FUENTE, _FUENTE_B, _FUENTE_I, _SIMBOLOS = "Arial", "Arial-Bold", "Arial-Italic", True


def fecha_larga(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def plazo_txt(fin):
    """"2026-11-05 12:00" -> "jueves 5 de noviembre de 2026, a las 12:00"."""
    try:
        d = datetime.strptime(fin, "%Y-%m-%d %H:%M")
    except ValueError:
        return fin
    return f"{DIAS[d.weekday()]} {fecha_larga(d)}, a las {d:%H:%M}"


def plazo_corto(fin):
    """"2026-11-05 12:00" -> "JUEVES 5-11-2026, 12:00 H" (cabe en una línea de la cabecera de la ficha)."""
    try:
        d = datetime.strptime(fin, "%Y-%m-%d %H:%M")
    except ValueError:
        return fin
    return f"{DIAS[d.weekday()].upper()} {d.day}-{d.month}-{d.year}, {d:%H:%M} H"


def duracion_txt(m):
    if m < 1:
        return f"{max(1, round(m * 30.4))} días"
    if m >= 24 and not m % 12:
        return f"{int(m // 12)} años"
    return f"{int(m) if m == int(m) else str(m).replace('.', ',')} meses"


def _estilos():
    base = dict(fontName=_FUENTE, fontSize=9, leading=11.5, textColor=NEGRO)
    return {
        "normal": ParagraphStyle("n", **base),
        "pequeno": ParagraphStyle("p", **{**base, "fontSize": 7, "leading": 8.5, "textColor": GRIS}),
        "titulo_ficha": ParagraphStyle("tf", **{**base, "fontName": _FUENTE_B, "fontSize": 10, "leading": 12.5}),
        "etiqueta": ParagraphStyle("e", **{**base, "fontName": _FUENTE_B, "fontSize": 9}),
        "motivo": ParagraphStyle("m", **{**base, "leftIndent": 10, "bulletIndent": 0, "fontSize": 8.8,
                                         "leading": 11}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": _FUENTE_B, "fontSize": 22, "leading": 27}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": _FUENTE_B, "fontSize": 14, "leading": 18, "spaceBefore": 4,
                                      "spaceAfter": 6}),
        "portada": ParagraphStyle("pt", **{**base, "fontName": _FUENTE_B, "fontSize": 28, "leading": 34,
                                           "alignment": TA_CENTER}),
        "centro": ParagraphStyle("c", **{**base, "alignment": TA_CENTER, "fontSize": 11, "leading": 15}),
        "grupo": ParagraphStyle("g", **{**base, "fontName": _FUENTE_B, "fontSize": 13, "leading": 16}),
    }


def _e(t):
    return escape(str(t or ""))


def _simbolo(grupo):
    s, nombre, _ = GRUPO_TXT[grupo]
    return f"{s} {nombre}" if _SIMBOLOS else f"[{nombre}]"


def _ficha(r, est):
    filas = []
    cab = (f'<font name="{_FUENTE_B}">{_e(_simbolo(r["grupo"]))}</font>')
    cierra = f'<font name="{_FUENTE_B}">CIERRA: {_e(plazo_corto(r["fin_plazo"]))}</font>'
    color_cab = colors.white if r["grupo"] == F.PUEDE else NEGRO     # PUEDE: cabecera en negativo
    filas.append([Paragraph(cab, ParagraphStyle("i", parent=est["etiqueta"], textColor=color_cab)),
                  Paragraph(cierra, ParagraphStyle("d", parent=est["etiqueta"], alignment=2, textColor=color_cab))])
    cuerpo = []
    if r["sumario"]:
        cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">&gt;&gt; PROCEDIMIENTO SUMARIO: '
                                'NO PIDEN DEMOSTRAR SOLVENCIA</font>', est["normal"]))
    cuerpo.append(Paragraph(_e(r["titulo"]), est["titulo_ficha"]))
    juntos = r.get("lotes_juntos") or []
    if len(juntos) > 1:
        cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">{len(juntos)} LOTES CON EL MISMO RESULTADO:</font>',
                                est["normal"]))
        for lid, tit, imp in juntos:
            cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">Lote {_e(lid)}:</font> {_e(tit)} '
                                    f'({_e(F.eur(imp))} sin IVA)', est["motivo"], bulletText="·"))
    elif r["lote"]:
        cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">LOTE {_e(r["lote"])}:</font> {_e(r["titulo_lote"])}',
                                est["normal"]))
    cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">Organismo:</font> {_e(r["organo"])}', est["normal"]))
    if len(juntos) > 1:
        datos = [f'<font name="{_FUENTE_B}">Importe:</font> el de cada lote']
    else:
        datos = [f'<font name="{_FUENTE_B}">Importe{" del lote" if r["lote"] else ""}:</font> '
                 f'{_e(F.eur(r["importe"]))} sin IVA']
    if r["lote"] and r.get("valor_estimado_contrato"):
        datos.append(f'contrato completo: {_e(F.eur(r["valor_estimado_contrato"]))}')
    if TIPO_TXT.get(r["tipo"]):
        datos.append(f'contrato de {TIPO_TXT[r["tipo"]]}')
    if r.get("duracion_meses"):
        datos.append(f'duración: {duracion_txt(r["duracion_meses"])}')
    datos.append(f'lugar: {_e(lugar_txt(r["provincia"]))}')
    cuerpo.append(Paragraph(" · ".join(datos), est["normal"]))
    cuerpo.append(Paragraph(f'<font name="{_FUENTE_B}">Por qué:</font>', est["normal"]))
    for m in r["motivos"]:
        cuerpo.append(Paragraph(_e(m), est["motivo"], bulletText="–"))
    if r.get("url"):
        cuerpo.append(Paragraph(f'Anuncio oficial: <a href="{_e(r["url"])}">{_e(r["url"])}</a>', est["pequeno"]))
    filas.append([cuerpo, ""])
    t = Table(filas, colWidths=[7 * cm, 10 * cm])
    estilo = [("BOX", (0, 0), (-1, -1), 0.8, NEGRO), ("LINEBELOW", (0, 0), (-1, 0), 0.5, NEGRO),
              ("SPAN", (0, 1), (1, 1)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if r["grupo"] == F.PUEDE:          # en B/N: la cabecera de PUEDE va en negativo (texto blanco sobre negro)
        estilo += [("BACKGROUND", (0, 0), (-1, 0), NEGRO), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    elif r["grupo"] == F.REVISA:       # REVISA: gris claro (se distingue también en fotocopia)
        estilo += [("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85))]
    t.setStyle(TableStyle(estilo))
    return [t, Spacer(1, 6)]      # quien llama lo envuelve en KeepTogether (anidarlos deja páginas a medias)


def _seleccion(resultados, total):
    """{grupo: fichas a mostrar}: las que cierran antes, con cuotas por grupo; lo que sobra de una pasa a las demás."""
    disponibles = {g: resultados.get(g, []) for g, _ in CUOTAS}
    n = {g: min(len(disponibles[g]), round(c * total / MAX_FICHAS)) for g, c in CUOTAS}
    sobra = total - sum(n.values())
    for g, _ in CUOTAS:
        extra = min(sobra, len(disponibles[g]) - n[g])
        n[g] += extra
        sobra -= extra
    return {g: sorted(disponibles[g], key=lambda r: r["fin_plazo"])[:n[g]] for g, _ in CUOTAS}


def _construir(destino, perfil_texto, resultados, fecha, total_fichas, muestra):
    est = _estilos()
    fichas = {g: _agrupar_lotes(resultados.get(g, [])) for g, _ in CUOTAS}
    sel = _seleccion(fichas, total_fichas)
    rotulo = "Informe de muestra · perfil inventado" if muestra else "Informe de licitaciones"

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FUENTE, 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawString(2 * cm, 1.2 * cm, f"Dinero Público · {rotulo} · {fecha_larga(fecha)}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    h = []
    # --- portada
    h += [Spacer(1, 3.2 * cm), Paragraph("DINERO PÚBLICO", est["centro"]), Spacer(1, 0.6 * cm),
          Paragraph("Licitaciones públicas abiertas<br/>para su empresa", est["portada"]), Spacer(1, 0.8 * cm)]
    if muestra:
        aviso = Table([[Paragraph(f'<font name="{_FUENTE_B}" size="13">INFORME DE MUESTRA · PERFIL INVENTADO</font>'
                                  '<br/>Los datos de la empresa son ficticios: no corresponde a ninguna empresa real. '
                                  'Las licitaciones sí son reales y estaban abiertas en la fecha del informe.',
                                  est["centro"])]], colWidths=[15 * cm])
        aviso.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 2, NEGRO), ("TOPPADDING", (0, 0), (-1, -1), 10),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        h += [aviso, Spacer(1, 0.6 * cm)]
    h += [Paragraph(f"Fecha del informe: {fecha_larga(fecha)}", est["centro"]), Spacer(1, 1 * cm),
          Paragraph("DATOS DEL PERFIL", est["h2"])]
    tabla = Table([[Paragraph(f'<font name="{_FUENTE_B}">{_e(k)}</font>', est["normal"]), Paragraph(_e(v), est["normal"])]
                   for k, v in perfil_texto], colWidths=[5 * cm, 12 * cm])
    tabla.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, NEGRO), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    h += [tabla, PageBreak()]

    # --- resumen
    h += [Paragraph("RESUMEN", est["h1"]), Spacer(1, 0.3 * cm),
          Paragraph("Hemos revisado todas las licitaciones con el plazo abierto en la Plataforma de Contratación del "
                    "Sector Público y nos hemos quedado con las de su sector, sus provincias y su tipo de contrato. "
                    "Cada una, y cada lote por separado, va en uno de estos tres grupos:", est["normal"]),
          Spacer(1, 0.4 * cm)]
    filas = []
    for g, _ in CUOTAS:
        lst = resultados.get(g, [])
        sumarios = sum(1 for r in lst if r["sumario"])
        lotes = sum(1 for r in lst if r["lote"])
        extra = []
        if sumarios:
            extra.append(f"{sumarios} por procedimiento sumario")
        if lotes:
            extra.append(f"{lotes} son lotes de un contrato mayor")
        filas.append([Paragraph(f'<font name="{_FUENTE_B}" size="12">{_e(_simbolo(g))}</font><br/>'
                                f'{_e(GRUPO_TXT[g][2])}', est["normal"]),
                      Paragraph(f'<font name="{_FUENTE_B}" size="20">{len(lst)}</font>'
                                + (f'<br/><font size="8">{_e("; ".join(extra))}</font>' if extra else ""),
                                ParagraphStyle("num", parent=est["normal"], alignment=TA_CENTER, leading=16))])
    t = Table(filas, colWidths=[12 * cm, 5 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, NEGRO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    h += [t, Spacer(1, 0.5 * cm)]
    mostradas = sum(len(v) for v in sel.values())
    totales = sum(len(fichas[g]) for g, _ in CUOTAS)
    if mostradas < totales:
        h.append(Paragraph(f'<font name="{_FUENTE_B}">En este informe van {mostradas} de las {totales} fichas</font>: '
                           "las que cierran antes en cada grupo, para que no pase de "
                           f"{MAX_PAGINAS} páginas. El resto se puede ver en la web.", est["normal"]))
        h.append(Spacer(1, 0.3 * cm))
    descartadas = len(resultados.get(F.DESCARTADA, []))
    if descartadas:
        h.append(Paragraph(f"No incluimos {descartadas} más de su sector y zona que, por tamaño o requisitos, "
                           "su empresa no podría hacer ni siquiera junto a otra.", est["normal"]))
        h.append(Spacer(1, 0.3 * cm))
    h += [Paragraph("CÓMO LEER LAS FICHAS", est["h2"]),
          Paragraph("· Cada ficha empieza con su grupo y la fecha y hora en que se cierra el plazo. Las de cada grupo "
                    "van de la que cierra antes a la que cierra después.", est["normal"]),
          Paragraph("· «Procedimiento sumario» son contratos pequeños (menos de 60.000 €, o 80.000 € en obras) en los "
                    "que no piden demostrar solvencia: son los más fáciles para empezar.", est["normal"]),
          Paragraph("· «Por qué» explica en qué nos basamos. Cuando el anuncio no da la cifra de facturación que "
                    "piden, la calculamos con la regla general de la ley (vez y media el importe anual del "
                    "contrato) y lo indicamos.", est["normal"]),
          Paragraph("· Los importes son sin IVA. Si es un lote, se da el importe del lote y el del contrato completo.",
                    est["normal"]),
          PageBreak()]

    # --- fichas
    for g, _ in CUOTAS:
        if not sel[g]:
            continue
        cab = Table([[Paragraph(f'{_e(_simbolo(g))}  ({len(sel[g])}'
                                + (f' de {len(fichas[g])}' if len(sel[g]) < len(fichas[g]) else "") + " fichas)",
                                ParagraphStyle("gb", parent=est["grupo"], textColor=colors.white))]],
                    colWidths=[17 * cm])
        cab.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NEGRO), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        h += [KeepTogether([cab, Spacer(1, 4), Paragraph(_e(GRUPO_TXT[g][2]), est["normal"]), Spacer(1, 6)]
                           + _ficha(sel[g][0], est))]
        h += [KeepTogether(_ficha(r, est)) for r in sel[g][1:]]
        h.append(Spacer(1, 0.3 * cm))

    # --- aviso final
    aviso = [Paragraph("AVISO IMPORTANTE", est["h2"]),
             Paragraph("Este informe es <b>orientativo</b>. Lo hemos preparado a partir de los anuncios publicados en "
                       "la Plataforma de Contratación del Sector Público, que no siempre traen todos los requisitos. "
                       "<b>Antes de presentarse, compruebe siempre el pliego oficial</b> (pliego de cláusulas "
                       "administrativas y pliego técnico), que es el que manda: requisitos de solvencia, "
                       "clasificación, certificados, plazos y forma de presentar la oferta.", est["normal"]),
             Spacer(1, 4),
             Paragraph("Los importes de facturación marcados como «cálculo nuestro» son una estimación con la regla "
                       "general de la Ley de Contratos del Sector Público; el pliego puede pedir menos (o, en casos "
                       "justificados, otra cosa). Las fechas y horas de cierre son las del anuncio en el momento de "
                       "preparar el informe y pueden cambiar.", est["normal"]),
             Spacer(1, 4),
             Paragraph(f"Fuente: Plataforma de Contratación del Sector Público (datos abiertos). Informe preparado "
                       f"por Dinero Público el {fecha_larga(fecha)}.", est["pequeno"])]
    caja = Table([[aviso]], colWidths=[17 * cm])
    caja.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 2, NEGRO), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    h += [Spacer(1, 0.4 * cm), KeepTogether([caja])]

    doc = SimpleDocTemplate(destino, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title=rotulo, author="Dinero Público")
    doc.build(h, onFirstPage=pie, onLaterPages=pie)
    return doc.page, mostradas, totales


def informe_pdf(ruta, perfil_texto, resultados, fecha=None, muestra=True):
    """Escribe el PDF en `ruta`. Devuelve (páginas, fichas mostradas, fichas totales)."""
    _registrar_fuentes()
    fecha = fecha or datetime.now()
    total = MAX_FICHAS
    while True:
        buf = io.BytesIO()
        paginas, mostradas, totales = _construir(buf, perfil_texto, resultados, fecha, total, muestra)
        if paginas <= MAX_PAGINAS or total <= 5:
            break
        total -= 5
    with open(ruta, "wb") as f:
        f.write(buf.getvalue())
    return paginas, mostradas, totales
