# encoding: utf-8
"""
Lista de comprobación de cada licitación y enlace a la guía «Cómo presentarse a una licitación» (12-11-2026, encargo
de César antes del lanzamiento B2B).

- La guía es la página GUIA_RUTA, en los 4 idiomas (backend/guia_licitaciones/<idioma>.html, la sirve app.py).
- La lista de comprobación sale de lo que dice el anuncio (filtro_licitaciones.datos_comprobacion): procedimiento, si es
  SARA, clasificación y certificados que pide, plazo con hora, enlace al anuncio y a los pliegos. Lo que el anuncio no
  dice se dice así («el anuncio no lo dice»), y lo que depende del pliego, también: aquí no se supone nada.
- La usan la ficha del embudo (/licitaciones/filtro), la del formulario, el correo semanal y el PDF. Las alertas
  diarias solo llevan el enlace a la guía.
- Los textos van en castellano, como el resto del filtro (que de momento solo existe en castellano).
"""
import html
import os
from datetime import datetime

try:
    from . import filtro_licitaciones as F
    from . import licitaciones_place as LP
except ImportError:
    import filtro_licitaciones as F
    import licitaciones_place as LP

# Para los enlaces absolutos del correo y del PDF (mismo valor por defecto que SITE_URL en app.py)
SITIO = os.environ.get("SITE_URL", "https://dinero-publico.com")
GUIA_RUTA = "/licitaciones/como-presentarse"
GUIA_TEXTO = "Cómo presentarse a una licitación, paso a paso"


def guia_url(base=""):
    return (base or "").rstrip("/") + GUIA_RUTA


def _fecha_hora(fin):
    try:
        d = datetime.strptime(fin, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None, None
    return d.strftime("%d/%m/%Y"), d.strftime("%H:%M")


def lineas(c):
    """[(etiqueta, texto, [(texto_enlace, url), ...])] de la lista de comprobación. `c`: datos_comprobacion()."""
    c = c or {}
    res = []
    # Procedimiento
    proc = c.get("procedimiento") or ""
    if c.get("sumario"):
        txt = ("Abierto simplificado de importe sumario: la ley permite tramitarlo con un solo sobre, sin acreditar "
               "solvencia y sin garantía definitiva (art. 159.6 LCSP). Compruebe en el PCAP que lo usa.")
    elif proc == F.PROCEDIMIENTO_SIMPLIFICADO:
        txt = ("Abierto simplificado: hay que estar inscrito en el ROLECE o en el registro de la comunidad autónoma "
               "(art. 159.4 LCSP) y no hay garantía provisional.")
    elif proc in LP.PROCEDIMIENTOS:
        txt = LP.PROCEDIMIENTOS[proc] + "."
    else:
        txt = "El anuncio no lo dice."
    res.append(("Procedimiento", txt, []))
    # SARA
    sara = c.get("sara")
    res.append(("Normas europeas (SARA)",
                "Sí: se publica también en el Diario Oficial de la UE y los plazos mínimos son más largos."
                if sara is True else "No." if sara is False else "El anuncio no lo dice.", []))
    # Clasificación
    if c.get("clas"):
        txt = "Pide: " + "; ".join(F.clas_llano(x) for x in c["clas"]) + "."
    elif c.get("obra_clasificacion") and not c.get("sumario"):
        txt = ("Obra de 500.000 € o más: la ley exige clasificación de contratista (art. 77 LCSP). El anuncio no "
               "dice el grupo: está en el PCAP.")
    else:
        txt = "El anuncio no la pide. Compruébelo en el PCAP."
    res.append(("Clasificación", txt, []))
    # Certificados
    if c.get("cert"):
        txt = "Pide: " + ", ".join(sorted({F.cert_llano(x) for x in c["cert"]})) + "."
    else:
        txt = "El anuncio no pide ninguno. Compruébelo en el PCAP."
    res.append(("Certificados", txt, []))
    # Plazo
    dia, hora = _fecha_hora(c.get("fin_plazo"))
    if not dia:
        txt = "El anuncio no da la fecha de cierre: mírela en la publicación oficial."
    elif c.get("plazo_sin_hora"):
        txt = f"Cierra el {dia}. El anuncio no da la hora: mírela en el PCAP. Después no se admiten ofertas."
    else:
        txt = f"Cierra el {dia} a las {hora} (hora del anuncio). Después no se admiten ofertas."
    res.append(("Plazo", txt, []))
    # Anuncio y pliegos
    if (c.get("url") or "").startswith("https://"):
        res.append(("Anuncio oficial", "", [("Ver el anuncio", c["url"])]))
    else:
        res.append(("Anuncio oficial", "No tenemos el enlace: búsquelo en la Plataforma de Contratación.", []))
    pl = c.get("pliegos") or {}
    enlaces = [(t, pl[k]) for k, t in (("pcap", "Pliego administrativo (PCAP)"), ("ppt", "Pliego técnico (PPT)"))
               if (pl.get(k) or "").startswith("https://")]
    res.append(("Pliegos", "" if enlaces else "No vienen enlazados en el anuncio: búsquelos en la página del anuncio.",
                enlaces))
    return res


def _e(t):
    return html.escape(str(t or ""), quote=True)


def lista_html(c, base="", estilo_enlace=""):
    """<div> con la lista de comprobación y el enlace a la guía (web y correo; estilos en línea para el correo)."""
    st = f' style="{estilo_enlace}"' if estilo_enlace else ""
    filas = []
    for etiqueta, txt, enlaces in lineas(c):
        partes = ([_e(txt)] if txt else []) + [
            f'<a href="{_e(u)}" target="_blank" rel="noopener noreferrer"{st}>{_e(t)}</a>' for t, u in enlaces]
        filas.append(f"<li><b>{_e(etiqueta)}:</b> {' · '.join(partes)}</li>")
    return (f'<div class="comprobar"><div class="comprobar-tit"><b>Lista de comprobación</b></div>'
            f'<ul>{"".join(filas)}</ul>'
            f'<div class="comprobar-guia"><a href="{_e(guia_url(base))}"{st}>{_e(GUIA_TEXTO)} →</a></div></div>')


def lista_texto(c, base=""):
    """Líneas de texto plano (versión de texto del correo)."""
    txt = ["Lista de comprobación:"]
    for etiqueta, t, enlaces in lineas(c):
        partes = ([t] if t else []) + [f"{a}: {u}" for a, u in enlaces]
        txt.append(f"  - {etiqueta}: " + " · ".join(partes))
    txt.append(f"  {GUIA_TEXTO}: {guia_url(base)}")
    return txt
