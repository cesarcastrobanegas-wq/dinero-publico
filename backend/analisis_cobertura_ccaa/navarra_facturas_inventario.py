"""Inventario de las "Relaciones trimestrales de facturas" del Portal de Contratación de Navarra (entidades cuyo
nombre contiene "Ayuntamiento"): entidad, año, título, UID y, con --cabeceras, nombre de fichero y tamaño.

Solo inventario (2026-10-02): sirve para decidir qué documentos traen adjudicatario + importe + objeto antes de
construir nada. Va por curl: `requests` con Python 3.14 recibe un corte en el saludo TLS de hacienda.navarra.es.

Uso:  python navarra_facturas_inventario.py salida.json [--cabeceras]"""
import json
import re
import subprocess
import sys
import time
import urllib.parse

from bs4 import BeautifulSoup

BASE = "https://hacienda.navarra.es/sicpportal/"
URL = BASE + "mtoBuscadorFacturasTrimestrales.aspx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
JAR = "nav_inventario_cookies.txt"


def curl(url, data=None, extra=()):
    cmd = ["curl", "-s", "-m", "90", "-A", UA, "-b", JAR, "-c", JAR, "-L", *extra, url]
    if data is not None:
        cmd += ["-H", "Content-Type: application/x-www-form-urlencoded; charset=iso-8859-15", "--data-binary", data]
    return subprocess.run(cmd, capture_output=True).stdout


def ocultos(soup):
    return {i.get("name"): i.get("value", "") for i in soup.find_all("input", type="hidden") if i.get("name")}


def codificar(d):
    return "&".join(f"{k}={urllib.parse.quote(str(v).encode('iso-8859-15', errors='replace'))}" for k, v in d.items())


def filas(soup):
    t = soup.find("table", id="tblFacturasTrimestrales")
    out = []
    for tr in (t.find_all("tr") if t else []):
        a = tr.find("a", href=re.compile(r"mtoGenerarDocumentoFacturaTrimestral"))
        if not a:
            continue
        tds = tr.find_all("td")
        out.append({"entidad": tds[2].get_text(" ", strip=True), "anio": tds[3].get_text(strip=True),
                    "titulo": a.get_text(" ", strip=True), "uid": a["href"].split("UID=")[1]})
    return out


def main():
    salida = sys.argv[1]
    s = BeautifulSoup(curl(URL).decode("iso-8859-15", "replace"), "html.parser")
    p = ocultos(s)
    p.update({"txtEntidad": "Ayuntamiento", "btnEnviar": "Buscar"})
    s = BeautifulSoup(curl(URL, codificar(p)).decode("iso-8859-15", "replace"), "html.parser")
    docs, vistos, pagina = [], set(), 1
    while True:
        nuevas = [f for f in filas(s) if f["uid"] not in vistos]
        if not nuevas:
            break
        for f in nuevas:
            vistos.add(f["uid"])
            docs.append(f)
        print(f"pagina {pagina}: {len(nuevas)} documentos ({len(docs)} en total)", flush=True)
        if not s.find("input", attrs={"name": "btnSiguiente"}):
            break
        p = ocultos(s)
        p.update({"txtEntidad": "Ayuntamiento", "btnSiguiente.x": "5", "btnSiguiente.y": "5"})
        time.sleep(0.8)
        s = BeautifulSoup(curl(URL, codificar(p)).decode("iso-8859-15", "replace"), "html.parser")
        pagina += 1
    if "--cabeceras" in sys.argv:
        for i, d in enumerate(docs, 1):
            cab = curl(BASE + "mtoGenerarDocumentoFacturaTrimestral.aspx?UID=" + d["uid"],
                       extra=("-I",)).decode("iso-8859-15", "replace")
            m = re.search(r'filename="?([^"\r\n]+)"?', cab)
            n = re.search(r"Content-Length:\s*(\d+)", cab)
            d["fichero"] = m.group(1) if m else ""
            d["bytes"] = int(n.group(1)) if n else None
            if i % 50 == 0:
                print(f"cabeceras {i}/{len(docs)}", flush=True)
                json.dump(docs, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            time.sleep(0.4)
    json.dump(docs, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(docs)} documentos -> {salida}")


if __name__ == "__main__":
    main()
