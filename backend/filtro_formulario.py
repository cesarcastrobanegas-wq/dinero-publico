# encoding: utf-8
"""
Formulario del filtro de licitaciones por empresa (BORRADOR, encargo de César del 2026-10-27). Funciones puras: pintar
la página, leer el envío y enseñar una vista previa del resultado. app.py solo pone la ruta /filtro-licitaciones y le
pasa las licitaciones abiertas de la tabla.

- Campos decididos el 27-10: sector (CPV), provincias, trabajadores, tramo de facturación, clasificación (opcional),
  certificados (casillas + "otros"), año de constitución, tipo de contrato, si ha trabajado para la Administración, UTE
  y el correo para enviarle las licitaciones.
- Comprobación con filtro_licitaciones.validar_perfil() más la del correo.
- BORRADOR: no se guarda nada (ni en base de datos ni en registros). Al enviar, se valida y se enseña una vista previa
  con las licitaciones abiertas de ese momento. Guardar los perfiles (fichero propio, como alertas.db) es otro paso.
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
              "empresa. Puedes darte de baja en cualquier momento.")

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
<p class="priv">{_e(PRIVACIDAD)} <a href="/aviso-legal">Aviso legal y privacidad</a></p>
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


def pagina(cuerpo, titulo="Licitaciones para tu empresa"):
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
            f'<title>{_e(titulo)} | Dinero Público</title><style>{CSS}</style></head><body><div class="fl">'
            f'<div class="marca"><a href="/">Dinero Público</a></div><h1>{_e(titulo)}</h1>'
            f'<p class="sub">Cuéntanos cómo es tu empresa y te enviaremos las licitaciones públicas abiertas a las '
            f'que puede presentarse.</p>'
            f'<div class="borrador"><b>BORRADOR.</b> Esta página es una prueba: no guardamos ningún dato. Al enviar, '
            f'solo te enseñamos el resultado de hoy.</div>{cuerpo}</div></body></html>')


def responder(metodo, params, licitaciones_abiertas, ahora=None):
    """HTML de la página. metodo: "GET" o "POST"; params: dict de listas; licitaciones_abiertas: función sin argumentos
    que devuelve las licitaciones (dicts de filtro_licitaciones.desde_fila) solo cuando hacen falta; ahora: hora
    peninsular (los plazos de PLACE van en hora de España y el servidor, en UTC)."""
    if metodo != "POST":
        return pagina(formulario_html())
    if _uno(params, "web"):                                   # campo trampa: las personas no lo ven
        return pagina(formulario_html())
    perfil, _correo, errores = leer_envio(params)
    if errores:
        return pagina(formulario_html(params, errores))
    res = F.filtrar(licitaciones_abiertas(), perfil, ahora)
    return pagina(resultado_html(res) + '<h2>Tus datos</h2>' + formulario_html(params))
