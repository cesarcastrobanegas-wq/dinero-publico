# encoding: utf-8
"""Prueba (sin red) del «Síguenos» y de la imagen al compartir los casos (18-11-2026):
  - el pie y «Quién soy» enlazan los perfiles (Facebook, X, Instagram, TikTok y YouTube);
  - el JSON-LD de la organización lleva esos mismos perfiles en sameAs y es JSON válido;
  - en catalán sale traducido;
  - cada caso publicado de /casos usa su tarjeta apaisada como og:image (y twitter:image), que se sirve en
    /casos/<slug>/tarjeta-apaisada.png (PNG 1200x630); la vertical sigue en /casos/<slug>/tarjeta.png (1080x1350, para
    Instagram); el resto de páginas, la genérica; un borrador o un slug que no existe, 404 (19-11-2026).

    python backend/prueba_siguenos_og.py      (proceso pesado: importa la web; de uno en uno)
"""
import io
import json
import os
import re
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="siguenos_og_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
    import app
    from PIL import Image
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def get(path, qs=""):
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": qs, "REMOTE_ADDR": "127.0.0.1",
               "SERVER_NAME": "localhost", "SERVER_PORT": "80", "wsgi.url_scheme": "http",
               "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537.36"}
        estado = {}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
        return int(estado["s"][:3]), estado["h"], cuerpo

    perfiles = ["https://www.facebook.com/profile.php?id=61591580504305", "https://x.com/Diner0Public0", "https://www.instagram.com/dineropublic0/",
                "https://www.tiktok.com/@dineropublico.com", "https://www.youtube.com/@dineropublicoes"]

    cod, _, b = get("/quien-soy")
    t = b.decode("utf-8")
    comprobar(cod == 200, f"/quien-soy: {cod}")
    comprobar('id="siguenos"' in t, "«Quién soy» sin el apartado Síguenos")
    for url in perfiles:
        comprobar(t.count(f'href="{url}"') >= 2, f"falta {url} en el pie o en «Quién soy»")
    comprobar("@Diner0Public0" in t and "dineropublic0" in t and "@dineropublico.com" in t and "@dineropublicoes" in t,
              "«Quién soy» no enseña los usuarios")
    comprobar(app.PERFIL_FACEBOOK_URL == perfiles[0], f"PERFIL_FACEBOOK_URL: {app.PERFIL_FACEBOOK_URL}")
    comprobar(len(re.findall(r'href="https?://(?:www\.)?facebook\.com/[^"]*"', t)) == t.count(f'href="{perfiles[0]}"'),
              "hay otro enlace a Facebook que no es el de la Página")
    comprobar("bsky" not in t.lower() and "bluesky" not in t.lower(), "Bluesky no va en «Síguenos» (por ahora)")
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
    try:
        ld = json.loads(m.group(1)) if m else {}
    except ValueError:
        ld = {}
    comprobar(ld.get("@type") == "Organization" and ld.get("sameAs") == [p[2] for p in app._perfiles_redes()]
              and set(perfiles) <= set(ld.get("sameAs", [])), f"JSON-LD: {ld}")
    comprobar(not any("bsky" in u for u in ld.get("sameAs", [])), "Bluesky no va en el JSON-LD (por ahora)")

    cod, _, b = get("/ca/quien-soy")
    comprobar(cod == 200 and "Segueix-nos" in b.decode("utf-8"), f"/ca/quien-soy sin traducir: {cod}")

    cod, _, b = get("/")
    t = b.decode("utf-8")
    comprobar("/static/og-image.png" in re.search(r'property="og:image" content="([^"]+)"', t).group(1),
              "la portada no usa la imagen genérica")

    slug = next(c["slug"] for c in app._CASOS if c["slug"] not in app._CASOS_BORRADOR_POR_SLUG)
    cod, _, b = get(f"/casos/{slug}")
    t = b.decode("utf-8")
    og = re.search(r'property="og:image" content="([^"]+)"', t)
    tw = re.search(r'name="twitter:image" content="([^"]+)"', t)
    esperado = f"{app.SITE_URL}/casos/{slug}/tarjeta-apaisada.png"
    comprobar(cod == 200 and og and og.group(1) == esperado, f"og:image del caso: {og and og.group(1)}")
    comprobar(tw and tw.group(1) == esperado, "twitter:image del caso")
    comprobar('property="og:image:width" content="1200"' in t and 'property="og:image:height" content="630"' in t,
              "medidas de la tarjeta en og:image")

    def forma_de(png):
        try:
            img = Image.open(io.BytesIO(png))
            return (img.format, img.size)
        except Exception:
            return None

    for nombre, medida, limite in (("tarjeta-apaisada", (1200, 630), 250_000), ("tarjeta", (1080, 1350), 400_000)):
        cod, h, png = get(f"/casos/{slug}/{nombre}.png")
        forma = forma_de(png)
        comprobar(cod == 200 and h.get("Content-Type") == "image/png" and forma == ("PNG", medida),
                  f"{nombre} del caso: {cod} {forma}")
        comprobar(len(png) < limite, f"{nombre} de {len(png)} bytes")
        cod2, _, png2 = get(f"/casos/{slug}/{nombre}.png")
        comprobar(cod2 == 200 and png2 == png, f"la {nombre} no se reutiliza")
    comprobar(get(f"/casos/{slug}/tarjeta.png")[2] != get(f"/casos/{slug}/tarjeta-apaisada.png")[2],
              "la vertical y la apaisada son la misma imagen")
    publicados = [c for c in app._CASOS if c["slug"] not in app._CASOS_BORRADOR_POR_SLUG]
    for nombre, medida in (("tarjeta-apaisada", (1200, 630)), ("tarjeta", (1080, 1350))):
        n_ok = 0
        for c in publicados:
            cod, _, png = get(f"/casos/{c['slug']}/{nombre}.png")
            n_ok += cod == 200 and forma_de(png) == ("PNG", medida)
        comprobar(n_ok == len(publicados), f"solo {n_ok} de {len(publicados)} casos con {nombre}")

    cod, _, b = get("/casos")
    comprobar("/static/og-image.png" in re.search(r'property="og:image" content="([^"]+)"', b.decode()).group(1),
              "el índice de /casos no usa la genérica")
    for nombre in ("tarjeta", "tarjeta-apaisada"):
        cod, _, _ = get(f"/casos/no-existe-este-caso/{nombre}.png")
        comprobar(cod == 404, f"{nombre} de un caso inexistente: {cod}")
    cod, _, _ = get(f"/casos/{slug}/tarjeta-otra.png")
    comprobar(cod == 404, f"formato que no existe: {cod}")
    cod, _, _ = get("/casos/../app.py/tarjeta.png")
    comprobar(cod == 404, f"ruta rara: {cod}")
    app._CASOS_BORRADOR_POR_SLUG[slug] = lambda: ""
    app._CASO_TARJETAS.clear()
    for nombre in ("tarjeta", "tarjeta-apaisada"):
        cod, _, _ = get(f"/casos/{slug}/{nombre}.png")
        comprobar(cod == 404, f"{nombre} de un borrador: {cod}")
    comprobar(app._caso_tarjeta_ruta(f"/casos/{slug}") is None, "og:image de un borrador")
    del app._CASOS_BORRADOR_POR_SLUG[slug]

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.stdout.flush()
    os._exit(1 if mal else 0)


if __name__ == "__main__":
    main()
