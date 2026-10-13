# encoding: utf-8
"""
Revisión diaria de privacidad de la web publicada (2026-10-13, encargo de César). La lanza el flujo
privacidad-diaria.yml; no importa app.py ni toca ninguna base: solo lee páginas públicas, como un visitante.

Qué busca:
  1. DNI o NIE completos (sin enmascarar) en cualquier página revisada, en el texto y en los enlaces. Solo cuenta
     un número con su letra de control correcta; lo enmascarado (***4567**) no cuenta.
  2. Nombres de personas físicas donde no deben estar:
       - en /fondos-ue, una fila con NIF de persona (forma de DNI/NIE, entero o enmascarado): ahí no se publican
         personas, solo organizaciones;
       - en el sitemap, direcciones de búsqueda (?q=...), que podrían llevar el nombre de alguien a los buscadores.
  3. Administradores de empresa sin su fuente: todo nombre de administrador debe ir con el enlace al anuncio del
     BORME (y la petición de rectificación). La excepción es el autónomo, que figura como adjudicatario de su
     propio contrato.
  4. Rutas de administración abiertas: /admin/* tiene que seguir pidiendo la clave.

Qué páginas: las fijas (portada, rankings, fondos UE, convocatorias, casos, páginas legales, sitemap), dos búsquedas
por apellidos frecuentes y una muestra de fichas de municipio que ROTA cada día (misma fecha = misma muestra), con
su lista de contratos menores. Va despacio (una petición cada 2,5 s): la web frena las ráfagas.

Salida: un JSON con los hallazgos ({"tipo", "url", "n"}), sin datos personales: de un DNI encontrado solo se guarda
dónde está y cuántos hay. Los registros del flujo son públicos; este script no imprime nunca el dato encontrado.

Uso:  python backend/revision_privacidad.py --salida hallazgos.json [--base https://dinero-publico.com] [--fichas 15]
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIPOS = {
    "dni-nie-sin-enmascarar": "DNI o NIE completo a la vista",
    "persona-fisica-en-fondos-ue": "Persona física (NIF con forma de DNI/NIE) en Fondos UE",
    "sitemap-con-busquedas": "El sitemap incluye direcciones de búsqueda (?q=)",
    "administrador-sin-borme": "Administrador mostrado sin enlace al BORME",
    "admin-abierto": "Ruta de administración accesible sin clave",
    "pagina-con-error": "Página que no se ha podido revisar",
}
_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
_RE_DNI = re.compile(r"(?<![A-Za-z0-9])(\d{8})[ -]?([A-Za-z])(?![A-Za-z0-9])")
_RE_NIE = re.compile(r"(?<![A-Za-z0-9])([XYZxyz])[ -]?(\d{7})[ -]?([A-Za-z])(?![A-Za-z0-9])")
_RE_NIF_PERSONA = re.compile(r"^(?:\d{8}[A-Za-z]|[XYZxyz]\d{7}[A-Za-z]|\*{2,}\d{3,5}\*{1,}[A-Za-z]?)$")
# Un número de expediente o de licitación puede parecer un DNI: lo que sigue a estas palabras no se mira.
_RE_EXPEDIENTE = re.compile(r"(?:Licit|Lizit|Expediente|Exp|BDNS|Ref)\.?\s*[^\s<]{0,40}", re.I)


def dni_nie_completos(texto):
    """Cuántos DNI/NIE con letra de control válida hay en un texto."""
    n = 0
    for m in _RE_DNI.finditer(texto):
        if _LETRAS[int(m.group(1)) % 23] == m.group(2).upper():
            n += 1
    for m in _RE_NIE.finditer(texto):
        numero = int("XYZ".index(m.group(1).upper()) * 10_000_000 + int(m.group(2)))
        if _LETRAS[numero % 23] == m.group(3).upper():
            n += 1
    return n


def _visible(pagina):
    """Texto que ve una persona, más el contenido de los atributos donde puede viajar un dato (enlaces, títulos)."""
    sin_codigo = re.sub(r"<(script|style)\b.*?</\1>", " ", pagina, flags=re.S | re.I)
    atributos = " ".join(urllib.parse.unquote_plus(html.unescape(v)) for v in
                         re.findall(r'\b(?:href|title|alt|value|content|data-[a-z-]+)="([^"]*)"', sin_codigo))
    texto = html.unescape(re.sub(r"<[^>]+>", " ", sin_codigo))
    return _RE_EXPEDIENTE.sub(" ", texto), _RE_EXPEDIENTE.sub(" ", atributos)


def revisar_pagina(url, pagina):
    """Hallazgos de una página HTML: [{"tipo", "url", "n"}]."""
    hallazgos = []
    texto, atributos = _visible(pagina)
    n = dni_nie_completos(texto) + dni_nie_completos(atributos)
    if n:
        hallazgos.append({"tipo": "dni-nie-sin-enmascarar", "url": url, "n": n})

    # Administradores: nombre + cargo y, a continuación, la nota con el enlace al anuncio del BORME.
    sin_fuente = 0
    for m in re.finditer(r'<div class="directivo">(.*?)</div>\s*<div class="cargo">(.*?)</div>(.*?)</td>', pagina, re.S):
        cargo = re.sub(r"<[^>]+>", "", html.unescape(m.group(2))).strip().lower()
        if not cargo.startswith(("autónomo", "autonomo", "autònom", "autonomoa", "autónoma")) and "diario_borme" not in m.group(3):
            sin_fuente += 1
    # Tarjetas "top 1" de EMPRESAS (las mismas clases se usan para cargos públicos con su sueldo, que no son esto).
    for tarjeta in pagina.split('class="top1-card"')[1:]:
        tarjeta = tarjeta[:3000]
        m = re.search(r'<div class="top1-directivo">(.*?)</div>', tarjeta, re.S)
        if 'class="top1-empresa"' not in tarjeta or not m:
            continue
        cuerpo = m.group(1)
        if " — " in re.sub(r"<[^>]+>", "", cuerpo) and "diario_borme" not in cuerpo and "utónom" not in cuerpo:
            sin_fuente += 1
    # Fondos UE: "👤 Nombre — Cargo" bajo la organización beneficiaria.
    for m in re.finditer(r'<div class="lid"[^>]*>👤(.*?)</div>(.{0,400})', pagina, re.S):
        if 'class="fue-' in pagina and "diario_borme" not in m.group(2):
            sin_fuente += 1
    if sin_fuente:
        hallazgos.append({"tipo": "administrador-sin-borme", "url": url, "n": sin_fuente})

    # Fondos UE: ninguna fila con NIF de persona.
    personas = sum(1 for nif in re.findall(r'<div class="fue-nif">([^<]*)</div>', pagina) if _RE_NIF_PERSONA.match(nif.strip()))
    if personas:
        hallazgos.append({"tipo": "persona-fisica-en-fondos-ue", "url": url, "n": personas})
    return hallazgos


def revisar_sitemap(url, xml):
    n = len(re.findall(r"<loc>[^<]*[?&](?:amp;)?q=", xml))
    return [{"tipo": "sitemap-con-busquedas", "url": url, "n": n}] if n else []


class Web:
    def __init__(self, base, pausa=2.5):
        self.base, self.pausa, self.ultima, self.peticiones = base.rstrip("/"), pausa, 0.0, 0

    def pedir(self, ruta, datos=None):
        """(código, texto). Nunca lanza: un fallo de red devuelve (None, "")."""
        espera = self.pausa - (time.time() - self.ultima)
        if espera > 0:
            time.sleep(espera)
        self.ultima = time.time()
        self.peticiones += 1
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     headers={"User-Agent": "DineroPublico-RevisionPrivacidad/1.0 (+https://dinero-publico.com)"})
        for intento in (1, 2, 3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code in (429, 502, 503, 504) and intento < 3:
                    time.sleep(30 * intento)
                    continue
                return e.code, ""
            except Exception:
                if intento < 3:
                    time.sleep(15)
                    continue
                return None, ""


def muestra_de_fichas(sitemap, cuantas, fecha):
    """Fichas de municipio del sitemap (solo la versión en castellano), una muestra distinta cada día."""
    urls = sorted({html.unescape(u) for u in re.findall(r"<loc>([^<]*[?&](?:amp;)?muni=[^<]*)</loc>", sitemap)
                   if not re.search(r"\.com/(gl|ca|eu)/", u)})
    if not urls:
        return []
    paso = max(1, len(urls) // cuantas)
    inicio = (fecha.toordinal() * 7919) % len(urls)
    return [urls[(inicio + i * paso) % len(urls)] for i in range(cuantas)]


def revisar_web(base, n_fichas, fecha=None):
    fecha = fecha or datetime.date.today()
    web, hallazgos = Web(base), []

    def pagina(ruta, revisar=revisar_pagina):
        codigo, cuerpo = web.pedir(ruta)
        if codigo != 200:
            hallazgos.append({"tipo": "pagina-con-error", "url": base + ruta, "n": 1})
            return ""
        hallazgos.extend(revisar(base + ruta, cuerpo))
        return cuerpo

    sitemap = pagina("/sitemap.xml", revisar_sitemap)
    for ruta in ("/", "/rankings", "/fondos-ue", "/fondos-ue?fuente=cordis", "/fondos-ue?fuente=cordis&pag=40",
                 "/fondos-ue?ambito=provincia&pag=3", "/convocatorias", "/convocatorias?tab=subvenciones", "/casos",
                 "/quien-soy", "/aviso-legal", "/metodologia", "/mapa-cobertura", "/?q=garcia", "/?q=martinez+lopez"):
        pagina(ruta)
    for url in muestra_de_fichas(sitemap, n_fichas, fecha):
        ruta = url[len(base):] if url.startswith(base) else "/" + url.split("/", 3)[-1]
        cuerpo = pagina(ruta)
        if "pag_cm=" in cuerpo:                       # la lista de contratos menores tiene más páginas
            pagina(ruta + "&pag_cm=2")

    # Las rutas de administración siguen cerradas.
    for ruta, datos in (("/admin/revision", None), ("/admin/revision/comentarios", None), ("/admin/revision/alertas", None),
                        ("/admin/cache-db", None), ("/admin/alertas-db", b"token="), ("/admin/aviso-comentarios-prueba", b"token=")):
        codigo, cuerpo = web.pedir(ruta, datos)
        cerrado = codigo in (401, 403, 404, 405) or (codigo == 200 and "Acceso restringido" in cuerpo and "<table" not in cuerpo)
        if not cerrado:
            hallazgos.append({"tipo": "admin-abierto" if codigo == 200 else "pagina-con-error", "url": base + ruta, "n": 1})
    return hallazgos, web.peticiones


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="https://dinero-publico.com")
    ap.add_argument("--fichas", type=int, default=15)
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()
    hallazgos, peticiones = revisar_web(args.base, args.fichas)
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump({"fecha": datetime.date.today().isoformat(), "peticiones": peticiones, "hallazgos": hallazgos}, f, ensure_ascii=False)
    print(f"Páginas pedidas: {peticiones}. Hallazgos: {len(hallazgos)}.")
    for h in hallazgos:                              # solo dónde y cuántos; nunca el dato
        print(f"  - {TIPOS.get(h['tipo'], h['tipo'])}: {h['url']} ({h['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
