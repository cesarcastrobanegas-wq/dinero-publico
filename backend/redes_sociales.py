# encoding: utf-8
"""Bot de redes sociales de Dinero Público (09-11-2026, encargo de César): publica en X, en la Página de Facebook y
en Instagram los casos nuevos de /casos y un «ejemplo de uso» al día.

Este módulo no sabe nada de la web ni de la base: recibe los datos ya elegidos y devuelve textos, la tarjeta en PNG
y el resultado de cada publicación. La conexión (`http`, una sesión de requests o un sustituto en las pruebas) se le
pasa desde fuera, así que todo se prueba sin red. La web (app.py, bloque «REDES SOCIALES») decide qué se publica,
lo guarda en la tabla redes_publicaciones y lo enseña en /admin/redes.

Claves: solo en variables de entorno de Render (ver CLAVES). Nunca se escriben en un registro ni en un mensaje de
error (_sin_secretos).
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
import urllib.parse

REDES = ("x", "facebook", "instagram")
NOMBRE_RED = {"x": "X", "facebook": "Facebook", "instagram": "Instagram"}
# Variables de entorno que necesita cada red (todas). Instagram publica con el mismo token de la Página de Facebook
# a la que está vinculada la cuenta profesional; IG_PAGE_TOKEN lo sustituye si se quiere uno aparte.
CLAVES = {
    "x": ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"),
    "facebook": ("FB_PAGE_ID", "FB_PAGE_TOKEN"),
    "instagram": ("IG_USER_ID", "FB_PAGE_TOKEN"),
}
GRAPH_VERSION_DEFECTO = "v23.0"
X_TWEETS = "https://api.x.com/2/tweets"
X_MEDIA = "https://api.x.com/2/media/upload"
X_MAX = 280
X_LARGO_ENLACE = 23            # X cuenta cualquier enlace como 23 caracteres
ETIQUETAS_IG = "#DineroPúblico #transparencia #contratación"

ANCHO, ALTO = 1080, 1350
NAVY = (0x1B, 0x2A, 0x4A)
FONDO = (0xF5, 0xF6, 0xF8)
ACENTO = {"caso": (0xB4, 0x23, 0x18), "licitaciones": (0x0D, 0x7A, 0x3F), "indice": (0x1D, 0x4E, 0xD8),
          "destacado": (0x92, 0x40, 0x0E), "fondos": (0x00, 0x33, 0x99)}
DIR_FUENTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fuentes")


class ErrorRed(Exception):
    """Fallo de una red al publicar (el mensaje ya va sin claves)."""


# ─── Configuración ──────────────────────────────────────────────────────────────────────────────────────────────────

def activas(env=None):
    return (env if env is not None else os.environ).get("REDES_ACTIVAS", "0").strip() == "1"


def ensayo(env=None):
    """Modo ensayo (por defecto): todo espera a que César lo apruebe en /admin/redes. REDES_ENSAYO=0 lo quita."""
    return (env if env is not None else os.environ).get("REDES_ENSAYO", "1").strip() != "0"


def redes_configuradas(env=None):
    """Las redes que tienen todas sus claves (y no están apagadas con REDES_SOLO)."""
    env = env if env is not None else os.environ
    solo = {r.strip() for r in env.get("REDES_SOLO", "").split(",") if r.strip()}
    return [r for r in REDES if all(env.get(k, "").strip() for k in CLAVES[r]) and (not solo or r in solo)]


def _graph(env):
    v = env.get("REDES_GRAPH_VERSION", "").strip() or GRAPH_VERSION_DEFECTO
    return f"https://graph.facebook.com/{v}"


def _sin_secretos(texto, env):
    """El texto sin ninguna de las claves de las redes (por si una API las repite en un error)."""
    texto = str(texto)[:400]
    for r in CLAVES.values():
        for k in r + ("IG_PAGE_TOKEN",):
            v = env.get(k, "")
            if v and len(v) >= 6:
                texto = texto.replace(v, "***")
    return re.sub(r"(access_token=)[^&\s\"']+", r"\1***", texto)


# ─── Seguridad del texto ────────────────────────────────────────────────────────────────────────────────────────────

_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
_RE_DNI = re.compile(r"(?<![0-9A-Za-z])(?:(\d{8})[ .-]?([A-Za-z])|([XYZxyz])[ .-]?(\d{7})[ .-]?([A-Za-z]))(?![0-9A-Za-z])")


def tiene_dni(texto):
    """True si el texto lleva un DNI o NIE con la letra de control correcta."""
    for m in _RE_DNI.finditer(texto or ""):
        if m.group(1):
            if _LETRAS[int(m.group(1)) % 23] == m.group(2).upper():
                return True
        elif _LETRAS[("XYZ".index(m.group(3).upper()) * 10 ** 7 + int(m.group(4))) % 23] == m.group(5).upper():
            return True
    return False


def dos_frases(texto, maximo=260):
    """Las dos primeras frases del texto, cortadas por palabra entera si pasan de `maximo`."""
    texto = re.sub(r"\s+", " ", texto or "").strip()
    frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9«])", texto)
    corto = " ".join(frases[:2])
    if len(corto) > maximo:
        corto = corto[:maximo].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return corto


# ─── Textos de cada red ─────────────────────────────────────────────────────────────────────────────────────────────

def textos(titulo, frase, url):
    """{red: texto}. X: 280 caracteres contando el enlace como 23 (se recorta la frase). Instagram no deja pinchar
    enlaces en el texto: va la dirección escrita y las etiquetas."""
    titulo, frase = titulo.strip(), frase.strip()
    hueco = X_MAX - X_LARGO_ENLACE - len(titulo) - 4
    frase_x = frase if len(frase) <= hueco else (frase[:max(0, hueco - 1)].rsplit(" ", 1)[0].rstrip(",;:") + "…")
    x = f"{titulo}\n\n{frase_x}\n\n{url}" if frase_x and hueco > 20 else f"{titulo[:X_MAX - X_LARGO_ENLACE - 2]}\n\n{url}"
    sin_esquema = re.sub(r"^https?://", "", url)
    return {"x": x, "facebook": f"{titulo}\n\n{frase}\n\n{url}",
            "instagram": f"{titulo}\n\n{frase}\n\nEnlace: {sin_esquema}\n\n{ETIQUETAS_IG}"}


def largo_x(texto):
    """Largo del texto como lo cuenta X (enlaces = 23)."""
    return len(re.sub(r"https?://\S+", "x" * X_LARGO_ENLACE, texto))


def componer(entrada, site_url):
    """De una entrada {tipo, tema, titulo, frase, ruta, etiqueta, cifra} a lo que se guarda: textos de cada red y
    datos de la tarjeta. Lanza ValueError si algún texto lleva un DNI/NIE o falta algo."""
    for k in ("tipo", "tema", "titulo", "frase", "ruta"):
        if not entrada.get(k):
            raise ValueError(f"falta «{k}»")
    if not entrada["ruta"].startswith("/"):
        raise ValueError("la ruta tiene que ser de la web")
    url = site_url.rstrip("/") + entrada["ruta"]
    tx = textos(entrada["titulo"], entrada["frase"], url)
    tarjeta = {"tipo": entrada["tipo"], "etiqueta": entrada.get("etiqueta", ""), "cifra": entrada.get("cifra", ""),
               "titulo": entrada.get("titulo_tarjeta") or entrada["titulo"], "frase": entrada["frase"],
               "pie": re.sub(r"^https?://", "", url)}
    todo = " ".join(list(tx.values()) + [str(v) for v in tarjeta.values()])
    if tiene_dni(todo):
        raise ValueError("lleva un DNI/NIE: no se publica")
    return {"tipo": entrada["tipo"], "tema": entrada["tema"], "titulo": entrada["titulo"], "url": url,
            "textos": tx, "tarjeta": tarjeta}


# ─── Tarjeta 1080x1350 ──────────────────────────────────────────────────────────────────────────────────────────────

def _fuente(peso, tam):
    from PIL import ImageFont
    nombre = "SpaceGrotesk-Bold.ttf" if peso == "bold" else "SpaceGrotesk-Medium.ttf"
    return ImageFont.truetype(os.path.join(DIR_FUENTES, nombre), tam)


def _partir(draw, texto, fuente, ancho, max_lineas):
    palabras, lineas, actual = texto.split(), [], ""
    for p in palabras:
        prueba = (actual + " " + p).strip()
        if draw.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        ultima = lineas[-1]
        while ultima and draw.textlength(ultima + "…", font=fuente) > ancho:
            ultima = ultima.rsplit(" ", 1)[0] if " " in ultima else ultima[:-1]
        lineas[-1] = ultima + "…"
    return lineas


def dibujar_tarjeta(t):
    """PNG de 1080x1350 (4:5, el formato vertical de Instagram) con el logotipo (Space Grotesk, #1B2A4A)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (ANCHO, ALTO), FONDO)
    d = ImageDraw.Draw(img)
    acento = ACENTO.get(t.get("tipo"), NAVY)
    m = 84
    # logotipo: «D|inero / P|úblico», D y P en 700, el resto en 500, con la barra en medio
    fi, fr = _fuente("bold", 64), _fuente("medium", 64)
    x0, y0 = m, 80
    ancho_ini = max(d.textlength("D", font=fi), d.textlength("P", font=fi))
    d.text((x0, y0), "D", font=fi, fill=NAVY)
    d.text((x0, y0 + 74), "P", font=fi, fill=NAVY)
    d.rectangle((x0 + ancho_ini + 12, y0 + 10, x0 + ancho_ini + 17, y0 + 140), fill=NAVY)
    d.text((x0 + ancho_ini + 30, y0), "inero", font=fr, fill=NAVY)
    d.text((x0 + ancho_ini + 30, y0 + 74), "úblico", font=fr, fill=NAVY)
    # franja de color del tipo
    d.rectangle((0, 0, ANCHO, 16), fill=acento)
    y = 330
    if t.get("etiqueta"):
        d.text((m, y), t["etiqueta"].upper(), font=_fuente("bold", 40), fill=acento)
        y += 76
    if t.get("cifra"):
        tam = 190
        fc = _fuente("bold", tam)
        while d.textlength(str(t["cifra"]), font=fc) > ANCHO - 2 * m and tam > 80:
            tam -= 10
            fc = _fuente("bold", tam)
        d.text((m, y), str(t["cifra"]), font=fc, fill=NAVY)
        y += int(tam * 1.15)
    limite = ALTO - 200                       # hasta el pie
    ft = _fuente("medium", 60 if t.get("cifra") else 74)
    alto_linea = int(ft.size * 1.22)
    for linea in _partir(d, t.get("titulo", ""), ft, ANCHO - 2 * m, max(2, min(5, (limite - y) // alto_linea))):
        d.text((m, y), linea, font=ft, fill=NAVY)
        y += alto_linea
    # la frase, más pequeña, si cabe
    ff = _fuente("medium", 40)
    alto_f = int(ff.size * 1.35)
    y += 30
    if t.get("frase") and limite - y >= 2 * alto_f:
        for linea in _partir(d, t["frase"], ff, ANCHO - 2 * m, (limite - y) // alto_f):
            d.text((m, y), linea, font=ff, fill=(0x4A, 0x55, 0x6E))
            y += alto_f
    # pie: la dirección exacta de la página, en una o dos líneas, cortando por «/», «?» o «&»
    d.rectangle((0, ALTO - 150, ANCHO, ALTO), fill=NAVY)
    pie = t.get("pie", "dinero-publico.com")
    fp = _fuente("medium", 36)
    if d.textlength(pie, font=fp) <= ANCHO - 2 * m:
        d.text((m, ALTO - 98), pie, font=fp, fill=(255, 255, 255))
    else:
        fp = _fuente("medium", 32)
        trozos = re.split(r"(?=[/?&])", pie)
        l1 = ""
        while trozos and d.textlength(l1 + trozos[0], font=fp) <= ANCHO - 2 * m:
            l1 += trozos.pop(0)
        l2 = "".join(trozos)
        while d.textlength(l2, font=fp) > ANCHO - 2 * m:
            l2 = l2[:-2].rstrip() + "…" if not l2.endswith("…") else l2[:-2] + "…"
        d.text((m, ALTO - 122), l1, font=fp, fill=(255, 255, 255))
        d.text((m, ALTO - 78), l2, font=fp, fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ─── Publicadores ───────────────────────────────────────────────────────────────────────────────────────────────────

def _pct(s):
    return urllib.parse.quote(str(s), safe="~-._")


def oauth1_cabecera(metodo, url, env, nonce=None, ts=None):
    """Cabecera Authorization OAuth 1.0a (HMAC-SHA1) de X. El cuerpo JSON o multipart no entra en la firma."""
    oauth = {"oauth_consumer_key": env["X_API_KEY"], "oauth_nonce": nonce or secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(ts or int(time.time())),
             "oauth_token": env["X_ACCESS_TOKEN"], "oauth_version": "1.0"}
    partes = urllib.parse.urlsplit(url)
    params = dict(urllib.parse.parse_qsl(partes.query), **oauth)
    base_url = f"{partes.scheme}://{partes.netloc}{partes.path}"
    cadena = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
    base = "&".join((metodo.upper(), _pct(base_url), _pct(cadena)))
    llave = f"{_pct(env['X_API_SECRET'])}&{_pct(env['X_ACCESS_SECRET'])}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(llave.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def _json(resp, red, env, que):
    try:
        datos = resp.json()
    except ValueError:
        datos = {}
    if resp.status_code >= 300:
        detalle = datos.get("error", {}).get("message") if isinstance(datos.get("error"), dict) else None
        detalle = detalle or datos.get("detail") or datos.get("title") or getattr(resp, "text", "")[:200]
        raise ErrorRed(_sin_secretos(f"{NOMBRE_RED[red]}: {que} → HTTP {resp.status_code}: {detalle}", env))
    return datos


def publicar_x(http, env, texto, png):
    """Sube la tarjeta (API v2 de medios) y publica el texto con ella (API v2). Devuelve el id del post."""
    r = http.post(X_MEDIA, headers={"Authorization": oauth1_cabecera("POST", X_MEDIA, env)},
                  files={"media": ("tarjeta.png", png, "image/png")}, data={"media_category": "tweet_image"},
                  timeout=60)
    datos = _json(r, "x", env, "subir la imagen")
    media_id = (datos.get("data") or {}).get("id") or datos.get("media_id_string")
    if not media_id:
        raise ErrorRed("X: subir la imagen → la respuesta no trae el id")
    r = http.post(X_TWEETS, headers={"Authorization": oauth1_cabecera("POST", X_TWEETS, env),
                                     "Content-Type": "application/json"},
                  data=json.dumps({"text": texto, "media": {"media_ids": [str(media_id)]}}), timeout=30)
    pid = (_json(r, "x", env, "publicar").get("data") or {}).get("id")
    if not pid:
        raise ErrorRed("X: publicar → la respuesta no trae el id")
    return str(pid)


def publicar_facebook(http, env, texto, url_imagen):
    """Foto con texto en la Página (Graph API, /{page-id}/photos con la dirección pública de la tarjeta)."""
    r = http.post(f"{_graph(env)}/{env['FB_PAGE_ID']}/photos",
                  data={"url": url_imagen, "caption": texto, "access_token": env["FB_PAGE_TOKEN"]}, timeout=60)
    datos = _json(r, "facebook", env, "publicar la foto")
    pid = datos.get("post_id") or datos.get("id")
    if not pid:
        raise ErrorRed("Facebook: publicar la foto → la respuesta no trae el id")
    return str(pid)


def publicar_instagram(http, env, texto, url_imagen, esperar=time.sleep, intentos=10):
    """Instagram (Graph API): crea el contenedor con la imagen pública, espera a que esté listo y lo publica."""
    token = env.get("IG_PAGE_TOKEN") or env["FB_PAGE_TOKEN"]
    base = f"{_graph(env)}/{env['IG_USER_ID']}"
    r = http.post(f"{base}/media", data={"image_url": url_imagen, "caption": texto, "access_token": token}, timeout=60)
    contenedor = _json(r, "instagram", env, "crear el contenedor").get("id")
    if not contenedor:
        raise ErrorRed("Instagram: crear el contenedor → la respuesta no trae el id")
    for _ in range(intentos):
        r = http.get(f"{_graph(env)}/{contenedor}", params={"fields": "status_code", "access_token": token},
                     timeout=30)
        estado = _json(r, "instagram", env, "estado del contenedor").get("status_code")
        if estado == "FINISHED":
            break
        if estado in ("ERROR", "EXPIRED"):
            raise ErrorRed(f"Instagram: el contenedor quedó en {estado}")
        esperar(3)
    else:
        raise ErrorRed("Instagram: el contenedor no estuvo listo a tiempo")
    r = http.post(f"{base}/media_publish", data={"creation_id": contenedor, "access_token": token}, timeout=60)
    pid = _json(r, "instagram", env, "publicar").get("id")
    if not pid:
        raise ErrorRed("Instagram: publicar → la respuesta no trae el id")
    return str(pid)


def publicar(red, http, env, texto, url_imagen, png, esperar=time.sleep):
    """Publica en una red. Devuelve el id; lanza ErrorRed (sin claves en el mensaje) si falla."""
    try:
        if red == "x":
            return publicar_x(http, env, texto, png)
        if red == "facebook":
            return publicar_facebook(http, env, texto, url_imagen)
        if red == "instagram":
            return publicar_instagram(http, env, texto, url_imagen, esperar=esperar)
    except ErrorRed:
        raise
    except Exception as e:                                     # red caída, tiempo agotado...
        raise ErrorRed(_sin_secretos(f"{NOMBRE_RED.get(red, red)}: {type(e).__name__}: {e}", env))
    raise ErrorRed(f"red desconocida: {red}")
