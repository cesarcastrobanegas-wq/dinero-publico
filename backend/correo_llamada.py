# encoding: utf-8
"""
Correo para DESPUÉS de la llamada (HERRAMIENTA LOCAL, 2026-11-05; la web no la usa y no envía nada).

Para cada empresa de la lista de llamadas, un .txt en <salida>/correos con el asunto y un texto corto: que la
información la PIDIÓ por teléfono, qué es «Licitaciones para tu empresa», 2 licitaciones abiertas de su ficha, qué
informe de su sector adjuntar, el mes gratis y la pregunta de qué municipios y qué actividad quiere vigilar.

Solo se usa cuando la empresa ha pedido la información en la llamada y ha dado su correo: nada de publicidad a quien no
la ha pedido. El titular lo copia y lo pega en su correo; este código no manda nada.
La firma (nombre) y el teléfono NO se escriben aquí (el repositorio es público): llegan como parámetros.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402
import llamadas as L  # noqa: E402

CARPETA_CORREOS = "correos"
PRODUCTO = "Licitaciones para tu empresa"
CORREO_CONTACTO = "contacto@dinero-publico.com"
_RE_NUESTRO = re.compile(r"^\d{2} - .+\.txt$")      # solo se borran los .txt con este nombre (los que escribe esto)


def nombre_fichero(i, nombre):
    return f"{i:02d} - {L._para_fichero(I.nombre_empresa(nombre, 60))}.txt"


def fecha_plazo(lic):
    f = lic.get("fin_plazo") or ""
    return f"plazo hasta el {f[8:10]}/{f[5:7]}/{f[:4]}" if len(f) >= 10 else "plazo: ver el anuncio"


def texto(e, ahora, firma="", contacto_tel="", carpeta_informes="", k=2):
    """Devuelve (asunto, cuerpo, informe_a_adjuntar, licitaciones) de una empresa elegida por llamadas.elegir."""
    nombre = I.nombre_empresa(e["nombre"], 80)
    lics = L.licitaciones_ficha(e, k=k, ahora=ahora)
    informe = L.nombre_informe_sector(e["sector"])
    asunto = f"{PRODUCTO}: la información que me pidió ({nombre})"
    lineas = ["Buenos días:", "",
              f"Como me pidió por teléfono, le envío la información de «{PRODUCTO}».", "",
              "Es un servicio de Dinero Público: le enviamos por correo, cada semana o cada día, las licitaciones "
              "públicas abiertas que encajan con su actividad y con los municipios que usted elija.",
              "Revisamos lo que publican los ayuntamientos y demás organismos y solo le llega lo que le puede "
              "interesar, con el importe, el plazo y el enlace al anuncio.",
              "Así no se le escapa ninguna y no tiene que buscarlas.", ""]
    if lics:
        lineas.append("Por ejemplo, ahora mismo están abiertas estas dos:" if len(lics) > 1 else
                      "Por ejemplo, ahora mismo está abierta esta:")
        for x in lics:
            imp = I._f(x.get("presupuesto"))
            lineas += ["", f"  - {I.bonito(x.get('titulo') or '', 200)}",
                       f"    {I.organismo_corto(x.get('organo'))}"
                       + (f" · {I.eur(imp)} sin IVA" if imp else "") + f" · {fecha_plazo(x)}"]
            if x.get("url"):
                lineas.append(f"    {x['url']}")
        lineas.append("")
    lineas += [f"Le adjunto un informe de muestra de su sector ({e['sector']}) en la Región de Murcia.", "",
               "Le ofrezco un mes gratis, sin compromiso. Para preparárselo, ¿me dice qué municipios y qué actividad "
               "quiere que vigilemos?", "",
               "Un saludo,", ""]
    lineas += [x for x in (firma, "Dinero Público", contacto_tel, CORREO_CONTACTO) if x]
    return asunto, "\n".join(lineas), os.path.join(carpeta_informes, informe) if carpeta_informes else informe, lics


def escribir(salida, elegidas, ahora, firma="", contacto_tel="", carpeta_informes=""):
    """Un .txt por empresa en <salida>/correos (los de una lista anterior se quitan). Devuelve las rutas."""
    carpeta = os.path.join(salida, CARPETA_CORREOS)
    os.makedirs(carpeta, exist_ok=True)
    rutas = []
    for i, e in enumerate(elegidas, 1):
        asunto, cuerpo, informe, lics = texto(e, ahora, firma, contacto_tel, carpeta_informes)
        cabecera = [
            "SOLO PARA DESPUÉS DE LA LLAMADA: úsalo únicamente si te ha PEDIDO la información y te ha dado su correo.",
            "No lo mandes a quien no lo haya pedido.",
            f"Preparado el {ahora:%d/%m/%Y}. Antes de enviarlo, comprueba que el plazo de las licitaciones no ha "
            "terminado.",
            f"ADJUNTAR: {informe}",
            "Copia desde «Asunto» hacia abajo. Lo de encima de la raya no va en el correo.",
            "=" * 100, "",
            f"Asunto: {asunto}", "",
        ]
        ruta = os.path.join(carpeta, nombre_fichero(i, e["nombre"]))
        with open(ruta, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(cabecera) + cuerpo + "\n")
        rutas.append(ruta)
    hechos = {os.path.basename(r) for r in rutas}
    for viejo in os.listdir(carpeta):
        if _RE_NUESTRO.match(viejo) and viejo not in hechos:
            try:
                os.remove(os.path.join(carpeta, viejo))
            except OSError:
                print(f"  (no he podido quitar {viejo}: ¿está abierto?)", flush=True)
    return rutas
