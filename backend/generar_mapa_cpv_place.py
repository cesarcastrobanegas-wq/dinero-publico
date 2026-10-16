"""Mapa {enlace del contrato en PLACE: CPV principal} de los ZIP mensuales oficiales, para poner el CPV a los contratos
formales ya guardados (17-10-2026, preparado en la rama wip/cpv-formales; ver INFORME noche 17-10). Solo enlaces y
códigos CPV: ningún adjudicatario, NIF ni importe. Mismo enlace y mismo CPV que _entry_to_contratos de app.py (el
<link href> de la entrada y el ItemClassificationCode del ProcurementProject principal).
Uso: python generar_mapa_cpv_place.py <zip> [<zip> ...] --salida mapa_cpv_place.json.gz"""
import gzip
import json
import re
import sys
import zipfile

RE_ENTRY = re.compile(rb"<entry>(.*?)</entry>", re.S)
RE_LINK = re.compile(rb'<link\b[^>]+href=["\']([^"\']+)["\']')
RE_PP = re.compile(rb"<(?:[A-Za-z0-9_-]+:)?ProcurementProject(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?ProcurementProject>", re.S | re.I)
RE_CPV = re.compile(rb"<cbc:ItemClassificationCode[^>]*>\s*(\d{8})")


def main():
    args = sys.argv[1:]
    salida = args[args.index("--salida") + 1]
    zips = [a for a in args if a.endswith(".zip")]
    mapa = {}
    try:
        with gzip.open(salida, "rt", encoding="utf-8") as f:
            mapa = json.load(f)
    except (OSError, ValueError):
        pass
    for zp in zips:
        nuevos = 0
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if not n.endswith(".atom"):
                    continue
                for e in RE_ENTRY.findall(z.read(n)):
                    l, pp = RE_LINK.search(e), RE_PP.search(e)
                    c = RE_CPV.search(pp.group(1)) if pp else None
                    if l and c:
                        url = l.group(1).decode("utf-8", "replace")
                        if url not in mapa:
                            nuevos += 1
                        mapa[url] = c.group(1).decode()
        print(f"{zp}: {nuevos} enlaces nuevos, {len(mapa)} en total", flush=True)
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        json.dump(mapa, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
