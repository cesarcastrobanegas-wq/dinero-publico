# encoding: utf-8
"""
Formulario del filtro de licitaciones por empresa (BORRADOR, encargo de César del 2026-10-27). Funciones puras: pintar
la página, leer el envío y enseñar una vista previa del resultado. app.py solo pone la ruta /filtro-licitaciones y le
pasa las licitaciones abiertas de la tabla.

- Campos decididos el 27-10: sector (CPV), provincias, trabajadores, tramo de facturación, clasificación (opcional),
  certificados (casillas + "otros"), año de constitución, tipo de contrato, si ha trabajado para la Administración, UTE
  y el correo para enviarle las licitaciones.
- Comprobación con filtro_licitaciones.validar_perfil() más la del correo.
- BORRADOR, apagado salvo FILTRO_FORMULARIO=1. Al enviar, se valida, se enseña una vista previa con las licitaciones
  abiertas de ese momento y app.py guarda el perfil SIN CONFIRMAR en socios.db (ver socios.py) y manda el correo de
  confirmación (doble confirmación, como las alertas). Sin confirmar, a los 7 días se borra.
- Aquí están también las páginas de confirmar, baja y "mis licitaciones" y los textos de los correos (funciones puras:
  los enlaces firmados los pone app.py). Todos los correos llevan el enlace de baja, que BORRA el perfil.
- Página sin publicidad, analítica ni recursos de terceros, y noindex (como las de las alertas): lleva datos de empresa.
- Responsable de los datos: Dinero Público (decisión de César, 2026-10-27).
"""
import html
import re

try:
    from . import filtro_licitaciones as F
    from . import licitaciones_place as LIC
except ImportError:
    import filtro_licitaciones as F
    import licitaciones_place as LIC

RUTA = "/filtro-licitaciones"
MAX_FICHAS_VISTA = 10                    # por grupo, en la vista previa
_RE_CORREO = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")
TIPOS_FORM = (("obras", "Obras"), ("servicios", "Servicios"), ("suministros", "Suministros"))
PRIVACIDAD = ("Responsable: Dinero Público. Usamos estos datos solo para enviarte las licitaciones que encajan con tu "
              "empresa. Guardamos el correo y los datos de la empresa de este formulario; nada más. Te pediremos "
              "confirmar el correo: sin confirmar, lo borramos a los 7 días. Si no usas el servicio en un año, te "
              "avisaremos un mes antes y, si no nos dices que lo mantengamos, lo borraremos. Puedes darte de baja en "
              "cualquier momento con el enlace de cada correo.")
ANCLA_AVISO_LEGAL = "/aviso-legal#filtro-licitaciones"

CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#f5f6f8;color:#1c2333;margin:0;
line-height:1.45;font-size:16px}
.fl{max-width:760px;margin:0 auto;padding:16px}
.marca{font-weight:700;color:#1b2f5c;margin-bottom:12px}.marca a{text-decoration:none;color:inherit}
h1{font-size:1.45rem;margin:.2em 0 .3em}
.sub{color:#4a5468;margin:0 0 14px}
.borrador{background:#fff4d6;border:1px solid #e0b84a;border-radius:8px;padding:10px 12px;margin:0 0 16px;font-size:.92rem}
fieldset{background:#fff;border:1px solid #d9dde5;border-radius:10px;margin:0 0 14px;padding:12px 14px 14px}
legend{font-weight:700;padding:0 6px;font-size:1.02rem}
.ayuda{color:#5b6477;font-size:.88rem;margin:2px 0 8px}
.rejilla{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:2px 12px}
.rejilla label,.opc label{display:flex;gap:8px;align-items:flex-start;padding:5px 0;cursor:pointer}
.rejilla input,.opc input{margin-top:3px;width:18px;height:18px;flex:none}
.ccaa{margin:8px 0 2px;font-weight:600;font-size:.9rem;color:#33405a;border-top:1px solid #eef0f4;padding-top:6px}
.campo{margin:6px 0 10px}.campo label{display:block;font-weight:600;margin-bottom:4px}
input[type=text],input[type=email],input[type=number],select{width:100%;font-size:16px;padding:10px;
border:1px solid #b9c0cc;border-radius:8px;background:#fff}
.opc{display:flex;gap:18px;flex-wrap:wrap}
.errores{background:#fde8e8;border:1px solid #d9534f;border-radius:8px;padding:10px 14px;margin:0 0 14px}
.errores ul{margin:6px 0 0 18px;padding:0}
button{width:100%;font-size:1.05rem;font-weight:700;padding:14px;border:0;border-radius:10px;background:#1b2f5c;
color:#fff;cursor:pointer}
.priv{font-size:.86rem;color:#4a5468;margin:10px 0 0}
.resumen{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:0 0 14px}
.cifra{background:#fff;border:2px solid #1c2333;border-radius:10px;padding:10px 12px}
.cifra b{display:block;font-size:1.6rem}
.grupo{margin:18px 0 8px;padding:8px 12px;background:#1c2333;color:#fff;border-radius:8px;font-weight:700}
.ficha{background:#fff;border:1px solid #c6ccd6;border-radius:10px;padding:10px 12px;margin:0 0 10px}
.ficha .cab{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-weight:700;font-size:.9rem}
.ficha h3{font-size:1rem;margin:6px 0 4px}
.ficha ul{margin:4px 0 6px 18px;padding:0}.ficha li{margin:2px 0}
.ficha .dato{font-size:.92rem;color:#3a4356}
.sumario{display:inline-block;border:1px solid #1c2333;border-radius:4px;padding:0 6px;font-size:.8rem;font-weight:700}
.trampa{position:absolute;left:-9999px}
.caja{background:#fff;border:1px solid #d9dde5;border-radius:10px;padding:12px 14px;margin:0 0 14px}
.caja.ok{border:2px solid #1c2333}
.perfil{width:100%;border-collapse:collapse;font-size:.92rem}.perfil th,.perfil td{text-align:left;vertical-align:top;
padding:5px 6px;border-top:1px solid #eef0f4}.perfil th{width:42%;color:#33405a}
button.sec{background:#fff;color:#1b2f5c;border:2px solid #1b2f5c}
a{color:#1b4fb3}
"""


def _e(t):
    return html.escape(str(t if t is not None else ""), quote=True)


def _lista(params, nombre):
    return [v.strip() for v in params.get(nombre, []) if v.strip()]


def _uno(params, nombre):
    v = params.get(nombre, [""])
    return (v[0] if v else "").strip()


def _codigos(txt, patron):
    return [c for c in re.split(r"[\s,;]+", (txt or "").upper()) if c and re.fullmatch(patron, c)]


def leer_envio(params):
    """(perfil, correo, errores) a partir de los campos del formulario (dict de listas, como parse_qs)."""
    errores = []
    correo = _uno(params, "correo")
    if not (len(correo) <= 120 and _RE_CORREO.fullmatch(correo)):
        errores.append("correo: escribe una dirección de correo válida")
    cpvs = [c for c in _lista(params, "sector") if c in LIC.CPV_DIVISIONES]
    cpv_txt = _uno(params, "cpv")
    cpvs_extra = _codigos(cpv_txt, r"\d{2,8}")
    if cpv_txt and len(cpvs_extra) != len([c for c in re.split(r"[\s,;]+", cpv_txt) if c]):
        errores.append("códigos CPV: solo números de 2 a 8 cifras, separados por comas")
    trab_txt = _uno(params, "trabajadores")
    trabajadores = int(trab_txt) if trab_txt.isdigit() and 0 < int(trab_txt) <= 1_000_000 else None
    if trabajadores is None:
        errores.append("personas en plantilla: escribe un número (1 o más)")
    anio_txt = _uno(params, "anio")
    anio = int(anio_txt) if anio_txt.isdigit() else None
    if anio_txt and anio is None:
        errores.append("año de constitución: escribe el año con cuatro cifras")
    otros = [re.sub(r"\s+", "", c) for c in re.split(r"[,;]+", _uno(params, "cert_otros").upper()) if c.strip()]
    exp = _uno(params, "experiencia")
    ute = _uno(params, "ute")
    if ute not in ("si", "no"):
        errores.append("UTE: indica si irías junto a otra empresa")
    perfil = {
        "cpvs": list(dict.fromkeys(cpvs + cpvs_extra)),
        "provincias": [p for p in _lista(params, "provincia") if p in F.NOMBRE_PROVINCIA],
        "incluir_sin_provincia": _uno(params, "nacional") == "1",
        "trabajadores": trabajadores,
        "facturacion": _uno(params, "facturacion"),
        "clasificacion": [c for c in re.split(r"[\s,;]+", _uno(params, "clasificacion").upper()) if c],
        "certificados": [c for c in _lista(params, "cert") if c in F.CERTIFICADOS] + otros,
        "anio_constitucion": anio,
        "tipos": [t for t in _lista(params, "tipo") if t in LIC.TIPOS_FILTRO],
        "experiencia_publica": {"si": True, "no": False}.get(exp),
        "ute": ute == "si",
    }
    errores += F.validar_perfil(perfil)
    return perfil, correo, errores


def _casilla(nombre, valor, texto, marcadas):
    return (f'<label><input type="checkbox" name="{nombre}" value="{_e(valor)}"'
            f'{" checked" if valor in marcadas else ""}> <span>{_e(texto)}</span></label>')


def _radio(nombre, valor, texto, actual):
    return (f'<label><input type="radio" name="{nombre}" value="{valor}"'
            f'{" checked" if actual == valor else ""}> <span>{texto}</span></label>')


def _provincias_html(marcadas):
    por_ccaa = {}
    for p in F.NOMBRE_PROVINCIA:
        ccaa = LIC.NUTS_COMUNIDAD.get(F._NUTS2_PROVINCIA.get(p, ""), "")
        por_ccaa.setdefault(F.NOMBRE_COMUNIDAD.get(ccaa, "Otras"), []).append(p)
    partes = []
    for ccaa in sorted(por_ccaa, key=lambda c: c.replace("Á", "A")):
        partes.append(f'<div class="ccaa">{_e(ccaa)}</div><div class="rejilla">'
                      + "".join(_casilla("provincia", p, F.NOMBRE_PROVINCIA[p], marcadas)
                                for p in sorted(por_ccaa[ccaa], key=lambda x: F.NOMBRE_PROVINCIA[x]))
                      + "</div>")
    return "".join(partes)


def formulario_html(v=None, errores=()):
    """El formulario, relleno con lo enviado (v: dict de listas) si vuelve con errores."""
    v = v or {}
    u = lambda k: _uno(v, k)                                         # noqa: E731
    lst = lambda k: set(_lista(v, k))                                # noqa: E731
    err = ""
    if errores:
        err = ('<div class="errores" role="alert"><b>Revisa estos datos:</b><ul>'
               + "".join(f"<li>{_e(x)}</li>" for x in errores) + "</ul></div>")
    sectores = sorted(LIC.CPV_DIVISIONES.items(), key=lambda kv: kv[1])
    tramos = "".join(f'<option value="{_e(k)}"{" selected" if u("facturacion") == k else ""}>{_e(t)}</option>'
                     for k, t in F.TRAMOS_TEXTO.items())
    nacional = u("nacional") == "1" or not v
    return f"""{err}<form method="POST" action="{RUTA}" novalidate>
<fieldset><legend>1. Sector</legend>
<p class="ayuda">Marca los sectores de tu empresa (puedes marcar varios).</p>
<div class="rejilla">{"".join(_casilla("sector", k, n, lst("sector")) for k, n in sectores)}</div>
<div class="campo" style="margin-top:10px"><label for="cpv">Códigos CPV más concretos (opcional)</label>
<p class="ayuda">Si los conoces, por ejemplo 90910000 (limpieza). Separados por comas.</p>
<input type="text" id="cpv" name="cpv" inputmode="numeric" maxlength="200" value="{_e(u("cpv"))}"></div>
</fieldset>
<fieldset><legend>2. Provincias</legend>
<p class="ayuda">Dónde puedes trabajar.</p>
{_provincias_html(lst("provincia"))}
<div class="opc" style="margin-top:8px"><label><input type="checkbox" name="nacional" value="1"{" checked" if nacional else ""}>
<span>Incluir también las de ámbito nacional (sin provincia concreta)</span></label></div>
</fieldset>
<fieldset><legend>3. Tipo de contrato</legend>
<p class="ayuda">Si no marcas ninguno, te mostramos todos.</p>
<div class="opc">{"".join(_casilla("tipo", k, t, lst("tipo")) for k, t in TIPOS_FORM)}</div>
</fieldset>
<fieldset><legend>4. Tamaño de la empresa</legend>
<div class="campo"><label for="trabajadores">Personas en plantilla</label>
<input type="number" id="trabajadores" name="trabajadores" min="1" inputmode="numeric" value="{_e(u("trabajadores"))}"></div>
<div class="campo"><label for="facturacion">Facturación anual</label>
<select id="facturacion" name="facturacion"><option value="">Elige un tramo</option>{tramos}</select></div>
<div class="campo"><label for="anio">Año de constitución</label>
<p class="ayuda">Si tu empresa tiene menos de 5 años, en muchos contratos no te pueden pedir experiencia previa.</p>
<input type="number" id="anio" name="anio" min="1850" max="2100" inputmode="numeric" value="{_e(u("anio"))}"></div>
</fieldset>
<fieldset><legend>5. Clasificación y certificados</legend>
<div class="campo"><label for="clasificacion">Clasificación de contratista (si la tienes)</label>
<p class="ayuda">Grupo, subgrupo y categoría, como en tu certificado del Registro de Licitadores. Por ejemplo: C2-4, G6-3.</p>
<input type="text" id="clasificacion" name="clasificacion" maxlength="200" autocapitalize="characters"
 value="{_e(u("clasificacion"))}"></div>
<p class="ayuda" style="margin-top:12px"><b>Certificados</b></p>
<div class="rejilla">{"".join(_casilla("cert", c, F.cert_llano(c), lst("cert")) for c in F.CERTIFICADOS)}</div>
<div class="campo"><label for="cert_otros">Otros certificados</label>
<input type="text" id="cert_otros" name="cert_otros" maxlength="200" placeholder="Por ejemplo: ISO 27001"
 value="{_e(u("cert_otros"))}"></div>
</fieldset>
<fieldset><legend>6. Experiencia y UTE</legend>
<p class="ayuda" style="margin-bottom:2px"><b>¿Has trabajado ya para alguna Administración?</b></p>
<div class="opc">{_radio("experiencia", "si", "Sí", u("experiencia"))}{_radio("experiencia", "no", "No", u("experiencia"))}</div>
<p class="ayuda" style="margin:10px 0 2px"><b>¿Irías en UTE, junto a otra empresa, a un contrato grande?</b></p>
<div class="opc">{_radio("ute", "si", "Sí", u("ute"))}{_radio("ute", "no", "No", u("ute"))}</div>
</fieldset>
<fieldset><legend>7. Dónde te enviamos las licitaciones</legend>
<div class="campo"><label for="correo">Correo electrónico</label>
<input type="email" id="correo" name="correo" maxlength="120" autocomplete="email" value="{_e(u("correo"))}"></div>
<input type="text" name="web" value="" tabindex="-1" autocomplete="off" aria-hidden="true" class="trampa">
</fieldset>
<button type="submit">Ver mis licitaciones</button>
<p class="priv">{_e(PRIVACIDAD)} <a href="{ANCLA_AVISO_LEGAL}">Protección de datos</a></p>
</form>"""


def _fecha(fin):
    """"2026-10-30 10:00" -> "30-10-2026, 10:00"."""
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d) (\d\d:\d\d)", fin or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}, {m.group(4)}" if m else (fin or "")


def _ficha_html(r):
    s, nombre, _ = _GRUPO[r["grupo"]]
    lote = (f'<div class="dato"><b>Lote {_e(r["lote"])}:</b> {_e(r["titulo_lote"])}</div>' if r["lote"] else "")
    datos = [f'<b>Importe{" del lote" if r["lote"] else ""}:</b> {_e(F.eur(r["importe"]))} sin IVA']
    if F.TIPO_TXT.get(r["tipo"]):
        datos.append(f'contrato de {_e(F.TIPO_TXT[r["tipo"]])}')
    datos.append(f'lugar: {_e(F.lugar_txt(r["provincia"]))}')
    enlace = f'<a href="{_e(r["url"])}" rel="noopener" target="_blank">Ver el anuncio oficial</a>' if r.get("url") else ""
    sumario = '<span class="sumario">PROCEDIMIENTO SUMARIO</span> ' if r["sumario"] else ""
    return (f'<div class="ficha"><div class="cab"><span>{s} {nombre}</span><span>Cierra: {_e(_fecha(r["fin_plazo"]))}</span></div>'
            f'<h3>{sumario}{_e(r["titulo"])}</h3>{lote}<div class="dato"><b>Organismo:</b> {_e(r["organo"])}</div>'
            f'<div class="dato">{" · ".join(datos)}</div><ul>{"".join(f"<li>{_e(m)}</li>" for m in r["motivos"])}</ul>'
            f'{enlace}</div>')


_GRUPO = {
    F.PUEDE: ("●", "PUEDE OPTAR", "Cumple lo que se puede comprobar en el anuncio."),
    F.REVISA: ("▲", "REVISA EL PLIEGO", "Encaja, pero algo depende de lo que diga el pliego."),
    F.UTE: ("■", "SOLO EN UTE O EN UN LOTE", "Tu empresa sola no llega; podría ir junto a otra (UTE)."),
}


def resultado_html(res):
    """Vista previa: cuántas hay en cada grupo y las MAX_FICHAS_VISTA primeras de cada uno, por fin de plazo."""
    cifras = "".join(f'<div class="cifra">{s} <b>{len(res.get(g, []))}</b>{n}</div>' for g, (s, n, _) in _GRUPO.items())
    partes = [f'<h2>Lo que encaja con tu empresa hoy</h2><div class="resumen">{cifras}</div>']
    for g, (s, n, ayuda) in _GRUPO.items():
        lst = sorted(res.get(g, []), key=lambda r: r["fin_plazo"])
        if not lst:
            continue
        mas = f" (las {MAX_FICHAS_VISTA} que cierran antes)" if len(lst) > MAX_FICHAS_VISTA else ""
        partes.append(f'<div class="grupo">{s} {n}: {len(lst)}{mas}</div><p class="ayuda">{_e(ayuda)}</p>')
        partes += [_ficha_html(r) for r in lst[:MAX_FICHAS_VISTA]]
    partes.append('<p class="ayuda">Orientativo: compruebe siempre el pliego oficial antes de presentarse.</p>')
    return "".join(partes)


SUB_FORMULARIO = ("Cuéntanos cómo es tu empresa y te enviaremos las licitaciones públicas abiertas a las que puede "
                  "presentarse.")


def pagina(cuerpo, titulo="Licitaciones para tu empresa", sub=SUB_FORMULARIO, autoenviar=False):
    """Página sin publicidad, analítica ni recursos de terceros. `autoenviar`: el formulario id="auto" se envía solo,
    para que confirmar o darse de baja sea un clic; un programa de correo que solo abre el enlace para revisarlo no
    ejecuta nada y no confirma ni borra nada (como en las alertas)."""
    script = '<script>var f=document.getElementById("auto");if(f){f.submit();}</script>' if autoenviar else ""
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
            f'<title>{_e(titulo)} | Dinero Público</title><style>{CSS}</style></head><body><div class="fl">'
            f'<div class="marca"><a href="/">Dinero Público</a></div><h1>{_e(titulo)}</h1>'
            + (f'<p class="sub">{_e(sub)}</p>' if sub else "")
            + f'<div class="borrador"><b>BORRADOR.</b> Esta página está en pruebas.</div>{cuerpo}</div>{script}'
            f'</body></html>')


REVISA_CORREO = ('<div class="caja ok"><b>Revisa tu correo.</b> Si la dirección es correcta, te acabamos de enviar un '
                 'mensaje con un enlace: púlsalo para confirmar y empezar a recibir las licitaciones. Si ya estabas '
                 'dado de alta, el enlace sirve para confirmar los datos nuevos.<br><span class="ayuda">Si no lo ves en '
                 'unos minutos, mira en la carpeta de correo no deseado. Sin confirmar no te enviaremos nada más y lo '
                 'borramos a los 7 días.</span></div>')


def responder(metodo, params, licitaciones_abiertas, ahora=None, guardar=None):
    """HTML de la página. metodo: "GET" o "POST"; params: dict de listas; licitaciones_abiertas: función sin argumentos
    que devuelve las licitaciones (dicts de filtro_licitaciones.desde_fila) solo cuando hacen falta; ahora: hora
    peninsular (los plazos de PLACE van en hora de España y el servidor, en UTC); guardar(correo, perfil): guarda el
    perfil sin confirmar y manda el correo de confirmación. La página dice lo mismo pase lo que pase al guardar (ya
    dado de alta, correo reciente...): así no se puede averiguar desde fuera si una dirección está dada de alta."""
    if metodo != "POST":
        return pagina(formulario_html())
    if _uno(params, "web"):                                   # campo trampa: las personas no lo ven
        return pagina(formulario_html())
    perfil, correo, errores = leer_envio(params)
    if errores:
        return pagina(formulario_html(params, errores))
    if guardar:
        guardar(correo, perfil)
    res = F.filtrar(licitaciones_abiertas(), perfil, ahora)
    return pagina((REVISA_CORREO if guardar else "") + resultado_html(res) + '<h2>Tus datos</h2>' + formulario_html(params))


# ── páginas de los enlaces del correo (confirmar, baja, mis licitaciones) ──────────────────────────────────────────
def perfil_html(perfil, ahora=None):
    filas = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in F.perfil_texto(perfil, ahora))
    return f'<table class="perfil">{filas}</table>'


def _campos_ocultos(campos):
    return "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">' for k, v in campos.items())


def enlace_no_valido_html():
    return pagina('<div class="caja">Este enlace no es válido o ha caducado: puede que ya te hayas dado de baja o que '
                  'la solicitud se haya borrado (las que no se confirman se borran a los 7 días). Puedes volver a '
                  f'<a href="{RUTA}">rellenar el formulario</a>.</div>', titulo="Enlace no válido", sub="")


def confirmar_pedir_html(campos):
    """Página del enlace de confirmación: un formulario que se envía solo (POST)."""
    return pagina(f'<div class="caja"><form method="POST" action="{RUTA}/confirmar" id="auto">{_campos_ocultos(campos)}'
                  '<button type="submit">Confirmar mi correo</button></form></div>',
                  titulo="Confirmar", sub="", autoenviar=True)


def confirmado_html(perfil, enlace_ver, enlace_baja, era_cambio=False, ya_estaba=False, ahora=None):
    if ya_estaba:
        cab = "Ya estaba confirmado. No hace falta hacer nada más."
    elif era_cambio:
        cab = "Listo: hemos guardado los datos nuevos de tu empresa."
    else:
        cab = ("Listo: ya estás dado de alta. Cada lunes te enviaremos por correo las licitaciones nuevas que encajan "
               "con tu empresa (si esa semana no hay ninguna, no te escribiremos).")
    return pagina(f'<div class="caja ok"><b>{_e(cab)}</b></div>'
                  f'<div class="caja"><b>Estos son los datos que tenemos de tu empresa</b>{perfil_html(perfil, ahora)}</div>'
                  f'<p><a href="{_e(enlace_ver)}">Ver ahora mis licitaciones</a></p>'
                  f'<p class="ayuda">En cada correo tendrás un enlace para darte de baja; al pulsarlo borramos tus datos. '
                  f'También puedes hacerlo ahora: <a href="{_e(enlace_baja)}">darme de baja y borrar mis datos</a>.</p>',
                  titulo="Correo confirmado", sub="")


def baja_pedir_html(campos):
    """Página del enlace de baja: un formulario que se envía solo (POST) y borra el perfil."""
    return pagina(f'<div class="caja"><form method="POST" action="{RUTA}/baja" id="auto">{_campos_ocultos(campos)}'
                  '<button type="submit">Darme de baja y borrar mis datos</button></form></div>',
                  titulo="Darte de baja", sub="", autoenviar=True)


def baja_hecha_html():
    return pagina('<div class="caja ok"><b>Te has dado de baja.</b> Hemos borrado tu correo y los datos de tu empresa. '
                  'No recibirás más mensajes.</div><p><a href="/">Volver al inicio</a></p>', titulo="Baja hecha", sub="")


def mis_licitaciones_html(perfil, res, campos_baja, ahora=None):
    return pagina(resultado_html(res)
                  + f'<div class="caja"><b>Los datos de tu empresa</b>{perfil_html(perfil, ahora)}'
                  f'<p class="ayuda">¿Ha cambiado algo? Vuelve a <a href="{RUTA}">rellenar el formulario</a> con el mismo '
                  f'correo: te pediremos confirmar el cambio.</p></div>'
                  f'<form method="POST" action="{RUTA}/baja">{_campos_ocultos(campos_baja)}'
                  '<button type="submit" class="sec">Darme de baja y borrar mis datos</button></form>',
                  titulo="Tus licitaciones", sub="Las licitaciones abiertas hoy que encajan con tu empresa.")


# ── correos (texto y HTML; app.py pone remitente, destinatario y cabeceras de baja) ─────────────────────────────────
def _pie_baja(enlace_baja):
    txt = ["", "--", "Recibes este correo porque se pidió en dinero-publico.com el envío de licitaciones para esta "
           "dirección.", f"Darte de baja y borrar tus datos con un clic: {enlace_baja}"]
    html_ = (f'<p style="font-size:12px;color:#6b7280;border-top:1px solid #e5e7eb;padding-top:12px;margin-top:24px">'
             f'Recibes este correo porque se pidió en dinero-publico.com el envío de licitaciones para esta dirección.<br>'
             f'<a href="{_e(enlace_baja)}" style="color:#6b7280">Darme de baja y borrar mis datos</a></p>')
    return txt, html_


def correo_html(cuerpo, pie):
    return (f'<div style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.5;'
            f'color:#1c2333;max-width:600px;margin:0 auto;padding:16px">'
            f'<div style="font-weight:700;color:#1b2f5c;font-size:17px;margin-bottom:14px">Dinero Público</div>'
            f'{cuerpo}{pie}</div>')


def correo_confirmacion(perfil, enlace_confirmar, enlace_baja, es_cambio=False, ahora=None):
    """(asunto, texto, html) del correo de confirmación. Lleva el enlace de baja como todos: si no lo pidió quien
    recibe el correo, puede borrar sus datos en el acto sin esperar a los 7 días."""
    datos = F.perfil_texto(perfil, ahora)
    if es_cambio:
        asunto = "Confirma los datos nuevos de tu empresa en Dinero Público"
        intro = "Has pedido cambiar los datos de tu empresa para recibir licitaciones de Dinero Público. Los datos nuevos son:"
        boton = "Confirmar los datos nuevos"
        no_tu = "Si no has sido tú, no hagas nada: sin confirmar no cambia nada y la petición se descarta en 7 días."
    else:
        asunto = "Confirma tu correo para recibir licitaciones de Dinero Público"
        intro = ("Has pedido recibir por correo las licitaciones públicas abiertas que encajan con tu empresa. "
                 "Estos son los datos que nos has dado:")
        boton = "Confirmar mi correo"
        no_tu = ("Si no has sido tú, no hagas nada: sin confirmar no te enviaremos nada más y lo borramos en 7 días. "
                 "Si prefieres borrarlo ya, usa el enlace de baja de abajo.")
    pie_txt, pie_html = _pie_baja(enlace_baja)
    lineas = [intro, ""] + [f"  {k}: {v}" for k, v in datos] + [
        "", f"Para confirmarlo, pulsa este enlace: {enlace_confirmar}", "", no_tu] + pie_txt
    tabla = "".join(f'<tr><td style="padding:3px 10px 3px 0;color:#4b5563;vertical-align:top">{_e(k)}</td>'
                    f'<td style="padding:3px 0;vertical-align:top">{_e(v)}</td></tr>' for k, v in datos)
    cuerpo = (f'<p>{_e(intro)}</p><table style="font-size:14px;border-collapse:collapse">{tabla}</table>'
              f'<p style="margin:18px 0"><a href="{_e(enlace_confirmar)}" style="background:#1b2f5c;color:#ffffff;'
              f'text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:600;display:inline-block">'
              f'{_e(boton)}</a></p><p style="font-size:13px;color:#6b7280">{_e(no_tu)}</p>')
    return asunto, "\n".join(lineas) + "\n", correo_html(cuerpo, pie_html)


# ── correo semanal y aviso de inactividad (2026-10-28) ──────────────────────────────────────────────────────────────
MAX_FICHAS_CORREO = 20
# Hueco reservado a cada grupo (decisión de César del 28-10, como en el PDF); el que sobra de uno pasa a los demás.
CUOTAS_CORREO = ((F.PUEDE, 12), (F.REVISA, 5), (F.UTE, 3))
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
_ORDEN_CORREO = (F.PUEDE, F.REVISA, F.UTE)
_NOMBRE_LLANO = {F.PUEDE: "Puede optar", F.REVISA: "Revisa el pliego", F.UTE: "Solo en UTE o en un lote"}
# Sin depender del color: símbolo + MAYÚSCULAS + negrita; además, cabecera en negativo / gris / con borde.
_CAB_CORREO = {
    F.PUEDE: "background:#1c2333;color:#ffffff;border:2px solid #1c2333",
    F.REVISA: "background:#e5e7eb;color:#1c2333;border:2px solid #1c2333",
    F.UTE: "background:#ffffff;color:#1c2333;border:2px dashed #1c2333",
}


def _fecha_larga(d):
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def fichas_correo(res):
    """[(grupo, fichas)] en el orden del correo (Puede optar, Revisa el pliego, Solo en UTE), con los lotes iguales
    juntos y por fin de plazo dentro de cada grupo; y el total de fichas."""
    grupos = [(g, F.agrupar_lotes(res.get(g, []))) for g in _ORDEN_CORREO]
    return [(g, f) for g, f in grupos if f], sum(len(f) for _, f in grupos)


def reparto_correo(grupos):
    """{grupo: fichas que van en el correo}: el hueco de CUOTAS_CORREO de cada grupo y, si un grupo tiene menos, lo que
    sobra pasa a los demás (en el orden del correo), hasta MAX_FICHAS_CORREO."""
    hay = dict((g, len(f)) for g, f in grupos)
    n = {g: min(hay.get(g, 0), c) for g, c in CUOTAS_CORREO}
    sobra = MAX_FICHAS_CORREO - sum(n.values())
    for g, _ in CUOTAS_CORREO:
        extra = min(sobra, hay.get(g, 0) - n[g])
        n[g] += extra
        sobra -= extra
    return n


def _ficha_correo(r):
    s, nombre, _ = _GRUPO[r["grupo"]]
    juntos = r.get("lotes_juntos") or []
    lineas_lote = []
    if len(juntos) > 1:
        lineas_lote = [f"{len(juntos)} lotes con el mismo resultado:"] + [
            f"  Lote {lid}: {tit} ({F.eur(imp)} sin IVA)" for lid, tit, imp in juntos]
    elif r["lote"]:
        lineas_lote = [f"Lote {r['lote']}: {r['titulo_lote']}"]
    importe = (f"Importe{' del lote' if r['lote'] and len(juntos) <= 1 else ''}: {F.eur(r['importe'])} sin IVA"
               if len(juntos) <= 1 else "")
    datos = " · ".join(x for x in (importe, f"contrato de {F.TIPO_TXT[r['tipo']]}" if F.TIPO_TXT.get(r["tipo"]) else "",
                                    f"lugar: {F.lugar_txt(r['provincia'])}") if x)
    txt = [f"{s} {nombre} · CIERRA: {_fecha(r['fin_plazo'])}",
           ("PROCEDIMIENTO SUMARIO · " if r["sumario"] else "") + r["titulo"]] + lineas_lote + [
        f"Organismo: {r['organo']}", datos] + [f"  - {m}" for m in r["motivos"]] + (
        [f"Anuncio oficial: {r['url']}"] if r.get("url") else [])
    titulo = (f'<a href="{_e(r["url"])}" style="color:#1c2333;text-decoration:underline">{_e(r["titulo"])}</a>'
              if r.get("url") else _e(r["titulo"]))
    sumario = ('<div style="font-weight:700;font-size:13px;margin:0 0 4px">&gt;&gt; PROCEDIMIENTO SUMARIO</div>'
               if r["sumario"] else "")
    lote_html = ""
    if len(juntos) > 1:
        lote_html = (f'<div style="font-size:14px;margin:4px 0"><b>{len(juntos)} lotes con el mismo resultado:</b><ul '
                     f'style="margin:2px 0 0 18px;padding:0">' + "".join(
                         f"<li>Lote {_e(lid)}: {_e(tit)} ({_e(F.eur(imp))} sin IVA)</li>" for lid, tit, imp in juntos)
                     + "</ul></div>")
    elif r["lote"]:
        lote_html = f'<div style="font-size:14px;margin:4px 0"><b>Lote {_e(r["lote"])}:</b> {_e(r["titulo_lote"])}</div>'
    html_ = (f'<div style="border:1px solid #9aa3b2;border-radius:8px;padding:10px 12px;margin:0 0 12px">'
             f'<div style="font-size:13px;font-weight:700;margin:0 0 6px">{s} {nombre} · CIERRA: {_e(_fecha(r["fin_plazo"]))}</div>'
             f'{sumario}<div style="font-size:16px;font-weight:700;line-height:1.35;margin:0 0 4px">{titulo}</div>{lote_html}'
             f'<div style="font-size:14px;color:#374151"><b>Organismo:</b> {_e(r["organo"])}</div>'
             f'<div style="font-size:14px;color:#374151">{_e(datos)}</div>'
             f'<ul style="margin:6px 0 0 18px;padding:0;font-size:14px">'
             + "".join(f'<li style="margin:2px 0">{_e(m)}</li>' for m in r["motivos"]) + "</ul></div>")
    return txt, html_


def correo_semanal(res, enlace_ver, enlace_baja, ahora):
    """(asunto, texto, html, fichas_en_el_correo, fichas_total) del correo semanal con las licitaciones NUEVAS (res:
    salida de filtrar() solo con las nuevas). Primero «Puede optar», después «Revisa el pliego» y al final «Solo en UTE
    o en un lote»; como mucho MAX_FICHAS_CORREO fichas repartidas con reparto_correo() (las que cierran antes de cada
    grupo) y el resto en «mis licitaciones». None si no hay ninguna: entonces no se envía nada."""
    grupos, total = fichas_correo(res)
    if not total:
        return None
    cifras = [(g, len(f)) for g, f in grupos]
    resumen = " · ".join(f"{_GRUPO[g][0]} {_NOMBRE_LLANO[g]}: {n}" for g, n in cifras)
    intro = ("Esta semana hay 1 licitación nueva que encaja con tu empresa." if total == 1 else
             f"Esta semana hay {total} licitaciones nuevas que encajan con tu empresa.")
    cabe = MAX_FICHAS_CORREO
    reparto = reparto_correo(grupos)
    mas = (f"En este correo van {cabe}, las que cierran antes de cada grupo. Las {total - cabe} restantes están en "
           f"«Mis licitaciones»." if total > cabe else "")
    lineas = [intro, resumen, ""] + ([mas, ""] if mas else [])
    cuerpo = (f'<p style="margin:0 0 8px">{_e(intro)}</p>'
              f'<p style="margin:0 0 12px;font-weight:700">{_e(resumen)}</p>'
              + (f'<p style="margin:0 0 12px;font-size:14px">{_e(mas)}</p>' if mas else ""))
    for g, fichas in grupos:
        s, nombre, ayuda = _GRUPO[g]
        van = fichas[:reparto[g]]
        cab = f"{s} {nombre}: {len(fichas)}" + (f" (en este correo, {len(van)})" if len(van) < len(fichas) else "")
        lineas += ["=" * 60, cab, ayuda, "=" * 60, ""]
        cuerpo += (f'<div style="{_CAB_CORREO[g]};border-radius:6px;padding:8px 10px;margin:18px 0 6px;font-weight:700;'
                   f'font-size:15px">{_e(cab)}</div><p style="margin:0 0 10px;font-size:13px">{_e(ayuda)}</p>')
        for r in van:
            t, h = _ficha_correo(r)
            lineas += t + [""]
            cuerpo += h
    boton = "Ver todas mis licitaciones"
    lineas += [f"{boton}: {enlace_ver}", "",
               "Orientativo: comprueba siempre el pliego oficial antes de presentarte. Los datos vienen de la "
               "Plataforma de Contratación del Sector Público."]
    cuerpo += (f'<p style="margin:18px 0"><a href="{_e(enlace_ver)}" style="background:#1b2f5c;color:#ffffff;'
               f'text-decoration:none;padding:12px 18px;border-radius:6px;font-weight:700;display:inline-block">'
               f'{_e(boton)}</a></p><p style="font-size:13px;color:#4b5563">Orientativo: comprueba siempre el pliego '
               f'oficial antes de presentarte. Los datos vienen de la Plataforma de Contratación del Sector Público.</p>')
    pie_txt, pie_html = _pie_baja(enlace_baja)
    asunto = (f"{total} licitación nueva para tu empresa" if total == 1 else f"{total} licitaciones nuevas para tu empresa") \
        + f" · semana del {_fecha_larga(ahora)}"
    return asunto, "\n".join(lineas + pie_txt) + "\n", correo_html(cuerpo, pie_html), min(total, cabe), total


def correo_sigues(enlace_mantener, enlace_baja, fecha_borrado):
    """(asunto, texto, html) del aviso «¿Sigues interesado?», un mes antes de borrar un perfil sin uso."""
    asunto = "¿Sigues interesado en recibir licitaciones? Pulsa para mantener tu perfil"
    intro = ("Hace casi un año que no usas tu perfil de licitaciones de Dinero Público (no has abierto tus licitaciones "
             "desde los correos). Para no guardar datos que ya no hacen falta, borramos los perfiles que no se usan.")
    pide = "Si quieres seguir recibiendo las licitaciones que encajan con tu empresa, pulsa aquí para mantener tu perfil:"
    plazo = (f"Si no lo pulsas antes del {_fecha_larga(fecha_borrado)}, borraremos tu correo y los datos de tu empresa, "
             f"y no te escribiremos más. No tienes que hacer nada más.")
    boton = "Sí, mantener mi perfil"
    pie_txt, pie_html = _pie_baja(enlace_baja)
    lineas = [intro, "", pide, enlace_mantener, "", plazo] + pie_txt
    cuerpo = (f"<p>{_e(intro)}</p><p>{_e(pide)}</p>"
              f'<p style="margin:18px 0"><a href="{_e(enlace_mantener)}" style="background:#1b2f5c;color:#ffffff;'
              f'text-decoration:none;padding:12px 18px;border-radius:6px;font-weight:700;display:inline-block">'
              f'{_e(boton)}</a></p><p>{_e(plazo)}</p>')
    return asunto, "\n".join(lineas) + "\n", correo_html(cuerpo, pie_html)


def mantener_pedir_html(campos):
    """Página del enlace «mantener mi perfil»: un formulario que se envía solo (POST)."""
    return pagina(f'<div class="caja"><form method="POST" action="{RUTA}/mantener" id="auto">{_campos_ocultos(campos)}'
                  '<button type="submit">Sí, mantener mi perfil</button></form></div>',
                  titulo="Mantener mi perfil", sub="", autoenviar=True)


def mantenido_html(enlace_ver, enlace_baja):
    return pagina('<div class="caja ok"><b>Listo: mantenemos tu perfil.</b> Seguirás recibiendo cada lunes las '
                  'licitaciones nuevas que encajan con tu empresa.</div>'
                  f'<p><a href="{_e(enlace_ver)}">Ver ahora mis licitaciones</a></p>'
                  f'<p class="ayuda">Si prefieres no recibir nada más: <a href="{_e(enlace_baja)}">darme de baja y '
                  f'borrar mis datos</a>.</p>', titulo="Perfil mantenido", sub="")
