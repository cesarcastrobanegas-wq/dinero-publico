# encoding: utf-8
"""
Página de precios (/precios, 2026-11-04, BORRADOR OCULTO). La web (app.py) solo la sirve con PRECIOS_VISIBLE=1;
sin ella, /precios y /gl/precios, /ca/precios, /eu/precios dan 404. Encendida tampoco la enlaza ninguna página, no va
al sitemap y lleva <meta name="robots" content="noindex">: César decide cuándo enlazarla.

Nada de precios en el código: cada uno sale de una variable de entorno y, si no está, el plan dice «Consultar».
  PRECIO_ALERTAS, PRECIO_FILTRO, PRECIO_INFORME          el importe tal cual se enseña («9», «9,90 €», «desde 49 €»).
                                                         Un número suelto lleva « €» detrás.
  PRECIO_ALERTAS_PERIODO, PRECIO_FILTRO_PERIODO,         «/mes», «/año» o «por informe» (también mes, año, anio,
  PRECIO_INFORME_PERIODO                                 informe). Por defecto /mes, /mes y por informe.
  PRECIOS_NOTA_IVA                                       la nota bajo los planes. Sin la variable: «IVA no incluido».
                                                         Puesta y vacía: sin nota.
  PRECIOS_CONTACTO                                       dirección para el botón «Escríbenos» (mailto). Sin ella (o si
                                                         no es un correo válido), el botón es el texto «Próximamente».
Ningún formulario de pago: el botón solo abre el correo.
Textos solo en castellano (también bajo /gl/, /ca/ y /eu/, donde la cabecera y el pie sí salen traducidos).
"""
import html
import re

_RE_CORREO = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")
_RE_NUMERO = re.compile(r"\d{1,6}(?:[.,]\d{1,2})?")
_PERIODOS = {"/mes": "/mes", "mes": "/mes", "/año": "/año", "año": "/año", "anio": "/año", "/anio": "/año",
             "por informe": "por informe", "informe": "por informe", "/informe": "por informe"}
NOTA_IVA_DEFECTO = "IVA no incluido"


def _e(texto):
    return html.escape(str(texto), quote=True)


# (clave, variable del precio, periodo por defecto, título, resumen, puntos). Las descripciones cuentan lo que hacen
# hoy alertas.py (nivel «pago»: 10 alertas, aviso diario), filtro_licitaciones.py + filtro_formulario.py (correo
# semanal en tres grupos) y el informe PDF de mercado (filtro_licitaciones_informe.py y su borrador de venta).
PLANES = (
    ("alertas", "PRECIO_ALERTAS", "/mes", "Alertas básicas",
     "Avisos por correo de lo nuevo que se publica en lo que te interesa.",
     ("Hasta 10 alertas (la versión gratuita tiene 1).",
      "Aviso diario en lugar del resumen semanal: te escribimos el día en que aparece algo nuevo.",
      "Contratos nuevos de un ayuntamiento, licitaciones abiertas y subvenciones abiertas, con los mismos filtros "
      "de Convocatorias abiertas (provincia, sector, tipo, importe...).",
      "Solo tu correo: sin nombre, teléfono ni IP. Baja en un clic desde cada correo.")),
    ("filtro", "PRECIO_FILTRO", "/mes", "Filtro de licitaciones",
     "Cada lunes, las licitaciones nuevas que encajan con el perfil de tu empresa.",
     ("Rellenas una vez el perfil: sectores, provincias, plantilla, facturación, clasificación y certificados.",
      "Cada licitación llega en uno de tres grupos: «Puede optar», «Revisa el pliego» o «Solo en UTE o en un "
      "lote», con el motivo explicado en lenguaje llano.",
      "Si una semana no hay nada nuevo que encaje, no te escribimos.",
      "Puedes ver en cualquier momento tus licitaciones abiertas desde el enlace del correo.")),
    ("informe", "PRECIO_INFORME", "por informe", "Informe a medida",
     "Un informe en PDF del mercado público de una empresa o de un sector en una provincia.",
     ("Licitaciones abiertas que encajan.",
      "Contratos ganados por la empresa y por sus competidores.",
      "Organismos que más contratan en ese sector y provincia.",
      "Con los datos oficiales que ya publica Dinero Público y sus fuentes enlazadas.")),
)


def _precio(entorno, variable):
    """Texto del precio ya escapado, o None si la variable no está o está vacía."""
    crudo = (entorno.get(variable) or "").strip()
    if not crudo:
        return None
    crudo = crudo[:40]
    if _RE_NUMERO.fullmatch(crudo):
        crudo += " €"
    return _e(crudo)


def _periodo(entorno, variable, defecto):
    valor = (entorno.get(variable) or "").strip().lower()
    return _PERIODOS.get(valor, defecto)


def nota_iva(entorno):
    if "PRECIOS_NOTA_IVA" not in entorno:
        return NOTA_IVA_DEFECTO
    return (entorno.get("PRECIOS_NOTA_IVA") or "").strip()[:200]


def contacto(entorno):
    correo = (entorno.get("PRECIOS_CONTACTO") or "").strip()
    return correo if len(correo) <= 120 and _RE_CORREO.fullmatch(correo) else ""


def planes(entorno):
    """[{clave, titulo, resumen, puntos, precio (html escapado o None), periodo}] con la configuración de `entorno`."""
    out = []
    for clave, var, defecto, titulo, resumen, puntos in PLANES:
        precio = _precio(entorno, var)
        out.append({"clave": clave, "titulo": titulo, "resumen": resumen, "puntos": puntos, "precio": precio,
                    "periodo": _periodo(entorno, var + "_PERIODO", defecto) if precio else ""})
    return out


CSS = """<style>
.precios-planes{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:22px 0 10px}
.precio-plan{border:1px solid var(--border);border-radius:8px;padding:18px 18px 16px;background:var(--surface);display:flex;flex-direction:column}
.precio-plan h2{margin:0 0 6px!important}
.precio-plan .precio{font-size:24px;font-weight:700;color:var(--accent);margin:6px 0 2px;font-family:'Space Grotesk',sans-serif}
.precio-plan .precio small{font-size:13px;font-weight:500;color:var(--dim)}
.precio-plan .resumen{font-size:13px;color:var(--dim);margin-bottom:8px!important;line-height:1.5}
.precio-plan ul{font-size:13px;line-height:1.5;flex:1}
.precio-plan .proximamente{display:inline-block;margin-top:8px;padding:9px 18px;border:1px dashed var(--border);border-radius:6px;color:var(--dim);font-size:13px}
.precios-nota{font-size:13px;color:var(--dim)}
</style>"""


def cuerpo_html(entorno):
    """El contenido de la página (dentro de .static-page). `entorno`: os.environ o un dict en las pruebas."""
    correo = contacto(entorno)
    tarjetas = []
    for p in planes(entorno):
        if p["precio"]:
            precio = f'<div class="precio">{p["precio"]} <small>{_e(p["periodo"])}</small></div>'
        else:
            precio = '<div class="precio">Consultar</div>'
        puntos = "".join(f"<li>{_e(x)}</li>" for x in p["puntos"])
        if correo:
            asunto = "Plan " + p["titulo"]
            boton = (f'<a class="contact-btn" href="mailto:{_e(correo)}?subject={_e(asunto.replace(" ", "%20"))}">'
                     f'Escríbenos</a>')
        else:
            boton = '<span class="proximamente">Próximamente</span>'
        tarjetas.append(f'<div class="precio-plan" id="plan-{p["clave"]}"><h2>{_e(p["titulo"])}</h2>{precio}'
                        f'<p class="resumen">{_e(p["resumen"])}</p><ul>{puntos}</ul><div>{boton}</div></div>')
    nota = nota_iva(entorno)
    return (f'<h1>Precios</h1>'
            f'<p>Consultar Dinero Público es y seguirá siendo gratis. Estos son los servicios de pago para quien '
            f'necesita que los datos le lleguen solos o un análisis a medida.</p>'
            f'<div class="precios-planes">{"".join(tarjetas)}</div>'
            + (f'<p class="precios-nota">{_e(nota)}</p>' if nota else ""))
