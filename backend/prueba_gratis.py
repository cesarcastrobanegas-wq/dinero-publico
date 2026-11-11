# encoding: utf-8
"""
Prueba gratis A MANO de «Licitaciones para tu empresa» (HERRAMIENTA LOCAL, 2026-11-04; la web no la usa).

El titular da de alta a un cliente en prueba (correo, sector o CPV, municipios) y cada lunes genera su resumen semanal
como PDF y como texto para pegar en un correo, que manda él desde su propio correo. No usa Resend ni la web, no se
conecta a nada (lee los ZIP de PLACE que se le pasen) y no guarda nada fuera de la carpeta local que se le indique
(--carpeta). Cada cliente es una subcarpeta con perfil.json (sus datos y qué licitaciones ya se le enviaron) y los
resúmenes de cada semana. Para borrar a un cliente basta con «baja» (borra su subcarpeta entera).

  alta     --correo X (--sector S | --cpv 9091 ...) [--municipio M ...] [--nombre EMPRESA] [--solo-municipios]
           [--dias 30]
  resumen  (--correo X | --todos) [--zip place_AAAAMM.zip ...]   (sin --zip: los dos últimos de ../llamadas/place;
           lo leído de cada ZIP se guarda en cache_licitaciones.sqlite junto a ellos: segundos en vez de minutos)
  lista
  baja     --correo X

Qué entra en el resumen: licitaciones de PLACE en plazo, de la provincia (Región de Murcia por defecto), que encajan
con el sector (los mismos sectores que el informe de mercado) o con alguno de los CPV dados, y cuyo órgano es el
ayuntamiento de uno de sus municipios o, salvo --solo-municipios, un organismo no municipal de la provincia (Comunidad
Autónoma, Servicio Murciano de Salud, universidades, Estado...). Arriba las NUEVAS (no enviadas antes) y debajo las que
siguen abiertas de semanas anteriores.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402

_RE_CORREO = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[a-z]{2,}$", re.I)
_RX_MUNICIPAL = re.compile(r"\b(ayuntamiento|ajuntament|concello|mancomunidad|junta de gobierno local|alcaldia|"
                           r"pleno|concejalia|entidad local menor|pedania)\b")
DIAS_PRUEBA = 30


def carpeta_cliente(base, correo):
    """Subcarpeta del cliente: el correo sin símbolos raros + una huella corta (dos correos parecidos no chocan)."""
    limpio = re.sub(r"[^a-z0-9]+", "_", correo.lower()).strip("_")[:50]
    return os.path.join(base, f"{limpio}_{hashlib.sha1(correo.lower().encode()).hexdigest()[:6]}")


def leer_perfil(base, correo):
    ruta = os.path.join(carpeta_cliente(base, correo), "perfil.json")
    if not os.path.exists(ruta):
        raise SystemExit(f"No hay ningún cliente en prueba con el correo {correo}.")
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def guardar_perfil(base, perfil):
    d = carpeta_cliente(base, perfil["correo"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "perfil.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(perfil, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "perfil.json"))


def alta(base, correo, sector=None, cpvs=(), municipios=(), nombre="", solo_municipios=False, dias=DIAS_PRUEBA,
         ahora=None):
    ahora = ahora or datetime.now()
    correo = (correo or "").strip()
    if not _RE_CORREO.match(correo):
        raise SystemExit(f"Correo no válido: {correo!r}")
    if sector and sector not in I.NOMBRES_SECTOR:
        raise SystemExit(f"Sector desconocido: {sector}. Sectores: {', '.join(I.NOMBRES_SECTOR)}")
    cpvs = sorted({re.sub(r"\D", "", c) for c in cpvs if re.sub(r"\D", "", c)})
    if not sector and not cpvs:
        raise SystemExit("Hace falta --sector o al menos un --cpv.")
    previo = None
    if os.path.exists(os.path.join(carpeta_cliente(base, correo), "perfil.json")):
        previo = leer_perfil(base, correo)
    perfil = dict(correo=correo, nombre=nombre.strip(), sector=sector or "", cpvs=cpvs,
                  municipios=[m.strip() for m in municipios if m.strip()], solo_municipios=bool(solo_municipios),
                  provincia="murcia",
                  alta=(previo or {}).get("alta") or ahora.strftime("%Y-%m-%d"),
                  fin_prueba=(previo or {}).get("fin_prueba") or (ahora + timedelta(days=dias)).strftime("%Y-%m-%d"),
                  enviadas=(previo or {}).get("enviadas") or {})
    guardar_perfil(base, perfil)
    return perfil


def baja(base, correo):
    d = carpeta_cliente(base, correo)
    if not os.path.isdir(d):
        raise SystemExit(f"No hay ningún cliente en prueba con el correo {correo}.")
    shutil.rmtree(d)


def clientes(base):
    res = []
    for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        ruta = os.path.join(base, n, "perfil.json")
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                res.append(json.load(f))
    return res


def encaja_perfil(lic, perfil):
    """True si la licitación es para este cliente (sector o CPV, y zona)."""
    sector_ok = bool(perfil.get("sector")) and I.encaja(lic, {perfil["sector"]})
    cpvs = [re.sub(r"\D", "", c) for c in (lic.get("cpvs") or [lic.get("cpv") or ""]) if c]
    cpv_ok = any(c.startswith(p) for c in cpvs for p in perfil.get("cpvs") or ())
    if not (sector_ok or cpv_ok):
        return False
    munis = [I.norm(m) for m in perfil.get("municipios") or ()]
    if not munis:
        return True
    organo = I.norm(lic.get("organo") or "")
    if _RX_MUNICIPAL.search(organo.lower()):
        return any(re.search(rf"\b{re.escape(m)}\b", organo) for m in munis)
    return not perfil.get("solo_municipios")


def resumen(base, perfil, licitaciones, ahora=None, contacto=None, marcar=True):
    """Escribe resumen_AAAA-MM-DD.pdf y .txt en la carpeta del cliente. Devuelve (ruta_pdf, ruta_txt, nuevas, siguen)."""
    ahora = ahora or datetime.now()
    suyas = sorted((x for x in licitaciones if encaja_perfil(x, perfil)), key=lambda x: x.get("fin_plazo") or "")
    enviadas = perfil.get("enviadas") or {}
    nuevas = [x for x in suyas if x["id"] not in enviadas]
    siguen = [x for x in suyas if x["id"] in enviadas]
    d = carpeta_cliente(base, perfil["correo"])
    os.makedirs(d, exist_ok=True)
    dia = ahora.strftime("%Y-%m-%d")
    ruta_txt = os.path.join(d, f"resumen_{dia}.txt")
    ruta_pdf = os.path.join(d, f"resumen_{dia}.pdf")
    contacto = contacto if contacto is not None else {"tel": I.CONTACTO_TEL, "email": I.CONTACTO_EMAIL,
                                                      "web": I.CONTACTO_WEB}
    with open(ruta_txt, "w", encoding="utf-8") as f:
        f.write(texto_correo(perfil, nuevas, siguen, ahora, contacto))
    pdf(ruta_pdf, perfil, nuevas, siguen, ahora, contacto)
    if marcar:
        for x in nuevas:
            enviadas[x["id"]] = dia
        perfil["enviadas"] = enviadas
        perfil["ultimo_resumen"] = dia
        guardar_perfil(base, perfil)
    return ruta_pdf, ruta_txt, nuevas, siguen


def _que(perfil):
    partes = [perfil["sector"]] if perfil.get("sector") else []
    if perfil.get("cpvs"):
        partes.append("CPV " + ", ".join(perfil["cpvs"]))
    zona = ", ".join(perfil["municipios"]) if perfil.get("municipios") else "toda la Región de Murcia"
    if perfil.get("municipios") and not perfil.get("solo_municipios"):
        zona += " y organismos regionales y del Estado en la Región"
    return " · ".join(partes), zona


def _linea(x, ahora):
    from llamadas import plazo_txt
    imp = I._f(x.get("presupuesto"))
    return (f"- {I.bonito(x.get('titulo') or '', 160)}\n  {I.organismo_corto(x.get('organo'))}"
            f"{' · ' + I.eur(imp) + ' sin IVA' if imp else ''} · {plazo_txt(x, ahora)}\n"
            f"  Requisitos: {I.requisitos_txt(x)}\n  {x.get('url') or ''}\n")


def _aviso_fin(perfil, ahora):
    fin = perfil.get("fin_prueba") or ""
    if fin and ahora.strftime("%Y-%m-%d") > fin:
        return f"La prueba gratis terminó el {I.fecha_corta(fin)}."
    return f"Prueba gratis hasta el {I.fecha_corta(fin)}." if fin else ""


def texto_correo(perfil, nuevas, siguen, ahora, contacto):
    que, zona = _que(perfil)
    saludo = f"Hola{', ' + I.nombre_empresa(perfil['nombre']) if perfil.get('nombre') else ''}:"
    t = [f"Asunto: Licitaciones de la semana ({ahora:%d/%m/%Y}): {len(nuevas)} nuevas para {que}", "",
         saludo, "",
         f"Estas son las licitaciones públicas abiertas de {que} en {zona}, a {ahora:%d/%m/%Y}.", ""]
    if nuevas:
        t += [f"NUEVAS ESTA SEMANA ({len(nuevas)})", ""] + [_linea(x, ahora) for x in nuevas]
    else:
        t += ["Esta semana no ha salido ninguna nueva.", ""]
    if siguen:
        t += [f"SIGUEN ABIERTAS DE SEMANAS ANTERIORES ({len(siguen)})", ""] + [_linea(x, ahora) for x in siguen]
    t += ["Antes de presentarse, revisa el pliego: requisitos, solvencia y plazo exactos están en el anuncio.", "",
          _aviso_fin(perfil, ahora),
          "Si no quieres recibir más estos correos, contéstame con «baja» y te quito de la lista.", "",
          "Un saludo,", "Dinero Público"]
    t += [x for x in (contacto.get("tel") and f"Tel. {contacto['tel']}", contacto.get("email"), contacto.get("web"))
          if x]
    t.append("")
    t.append("(Datos de la Plataforma de Contratación del Sector Público. Orientativo: no sustituye a leer el anuncio.)")
    return "\n".join(t) + "\n"


def pdf(ruta, perfil, nuevas, siguen, ahora, contacto):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from llamadas import _estilos, plazo_txt
    st, colors = _estilos()
    P = lambda t, s="p": Paragraph(t, st[s])        # noqa: E731
    E = escape
    que, zona = _que(perfil)
    doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.4 * cm, title="Licitaciones de la semana", author="Dinero Público")
    h = [P("Licitaciones de la semana", "h0"),
         P(E(f"{perfil.get('nombre') or perfil['correo']} · {que} · {zona} · {ahora:%d/%m/%Y}"), "sub"),
         P(E(_aviso_fin(perfil, ahora)), "pc"), Spacer(1, 6)]

    def bloque(titulo, lista):
        h.append(P(E(titulo), "h1"))
        for x in lista:
            imp = I._f(x.get("presupuesto"))
            h.append(Paragraph(
                f"<b>{E(I.bonito(x.get('titulo') or '', 200))}</b><br/>{E(I.organismo_corto(x.get('organo')))}"
                f"{' · ' + E(I.eur(imp)) + ' sin IVA' if imp else ''} · <b>{E(plazo_txt(x, ahora))}</b><br/>"
                f"Requisitos: {E(I.requisitos_txt(x))}<br/><font size=7>{E(x.get('url') or '')}</font>",
                st["li"], bulletText="•"))
        h.append(Spacer(1, 4))
    if nuevas:
        bloque(f"Nuevas esta semana ({len(nuevas)})", nuevas)
    else:
        h.append(P("Esta semana no ha salido ninguna nueva.", "h1"))
    if siguen:
        bloque(f"Siguen abiertas de semanas anteriores ({len(siguen)})", siguen)
    h.append(P(E("Antes de presentarse, revisa el pliego: requisitos, solvencia y plazo exactos están en el anuncio. "
                 "Datos de la Plataforma de Contratación del Sector Público; orientativo."), "pc"))
    pie = " · ".join(x for x in (contacto.get("tel") and f"Tel. {contacto['tel']}", contacto.get("email"),
                                 contacto.get("web")) if x)
    if pie:
        h.append(P(E("Dinero Público · " + pie), "pc"))
    doc.build(h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("accion", choices=("alta", "resumen", "lista", "baja"))
    ap.add_argument("--carpeta", required=True, help="carpeta local de los clientes en prueba")
    ap.add_argument("--correo")
    ap.add_argument("--nombre", default="")
    ap.add_argument("--sector")
    ap.add_argument("--cpv", action="append", default=[])
    ap.add_argument("--municipio", action="append", default=[])
    ap.add_argument("--solo-municipios", action="store_true")
    ap.add_argument("--dias", type=int, default=DIAS_PRUEBA)
    ap.add_argument("--zip", action="append", default=[])
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--contacto-tel", default=I.CONTACTO_TEL)
    a = ap.parse_args(argv)
    os.makedirs(a.carpeta, exist_ok=True)
    if a.accion == "alta":
        p = alta(a.carpeta, a.correo, a.sector, a.cpv, a.municipio, a.nombre, a.solo_municipios, a.dias)
        que, zona = _que(p)
        print(f"Alta: {p['correo']} · {que} · {zona} · prueba hasta el {I.fecha_corta(p['fin_prueba'])}")
    elif a.accion == "baja":
        baja(a.carpeta, a.correo)
        print(f"Baja: {a.correo} (su carpeta, borrada)")
    elif a.accion == "lista":
        for p in clientes(a.carpeta):
            que, zona = _que(p)
            print(f"{p['correo']} · {que} · {zona} · alta {p['alta']} · fin {p['fin_prueba']} · "
                  f"último resumen {p.get('ultimo_resumen', '-')}")
    else:
        if not a.zip:    # por defecto, los dos últimos ZIP que haya en <carpeta>/../llamadas/place
            import glob
            place = os.path.join(os.path.dirname(os.path.abspath(a.carpeta)), "llamadas", "place")
            a.zip = sorted(glob.glob(os.path.join(place, "place_*.zip")))[-2:]
        if not a.zip:
            ap.error("resumen necesita al menos un --zip de PLACE (o los ZIP en ...\\llamadas\\place)")
        objetivo = clientes(a.carpeta) if a.todos else [leer_perfil(a.carpeta, a.correo or "")]
        ahora = datetime.now()
        lic = I.cargar_licitaciones(a.zip, "murcia", ahora)
        contacto = {"tel": a.contacto_tel, "email": I.CONTACTO_EMAIL, "web": I.CONTACTO_WEB}
        for p in objetivo:
            rp, rt, nuevas, siguen = resumen(a.carpeta, p, lic, ahora, contacto)
            print(f"{p['correo']}: {len(nuevas)} nuevas, {len(siguen)} siguen abiertas -> {rp} y {rt}")


if __name__ == "__main__":
    main()
