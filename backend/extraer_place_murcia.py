"""Del ZIP mensual oficial de PLACE, se queda con las entradas (<entry> tal cual, sin tocar) de los contratos formales
cuyo órgano contiene el nombre de algún municipio de la provincia de Murcia (17-10-2026, backfill de formales de
Murcia 2021-2024, ver INFORME formales y producto). Mismo criterio que la web: _entry_to_contratos para sacar el
órgano y el patrón suelto \\b<municipio>\\b que usa buscar_en_zip para Murcia. Es un filtro más ANCHO que el de la
web (no mira el código postal), para no perder nada: el refresco normal de cada municipio vuelve a filtrar después.
La salida es un .atom comprimido con la cabecera del original y las entradas elegidas; lleva adjudicatarios, así que
solo va al repositorio privado. Por pantalla, solo recuentos.
Uso: python extraer_place_murcia.py <zip> <salida.atom.gz>"""
import gzip
import os
import re
import sys
import tempfile
import zipfile


def main():
    zip_path, salida = sys.argv[1:3]
    out = sys.stdout
    tmp = tempfile.mkdtemp(prefix="extraer_murcia_")
    os.environ["DATA_DIR"] = tmp
    os.environ["DINERO_HILOS_EN_POST_FORK"] = "1"
    proxies = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY")}
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    argv = sys.argv[:]
    sys.stdout = open(os.devnull, "w")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as A
    sys.stdout = out
    sys.argv = argv
    for k, v in proxies.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    nombres = sorted({A.normalizar(m) for m in A.MUNICIPIOS_POR_PROVINCIA["murcia"]}, key=len, reverse=True)
    patron = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in nombres) + r")\b")
    total = elegidas = contratos = 0
    cabecera = None
    with zipfile.ZipFile(zip_path) as z, gzip.open(salida, "wt", encoding="utf-8") as g:
        for nombre in z.namelist():
            if not nombre.endswith(".atom"):
                continue
            raw = z.read(nombre)
            if cabecera is None:
                p = raw.find(b"<entry>")
                cabecera = raw[:p].decode("utf-8", "replace") if p > 0 else '<?xml version="1.0" encoding="UTF-8"?>\n<feed>\n'
                g.write(cabecera)
            for e in A._entries_con_estado_todas_bytes(raw):
                total += 1
                try:
                    cs = A._entry_to_contratos(e)
                except Exception:
                    continue
                if any(patron.search(A.normalizar(c.get("organo", ""))) for c in cs):
                    g.write("<entry>" + e + "</entry>\n")
                    elegidas += 1
                    contratos += len(cs)
        g.write("</feed>\n")
    print(f"{os.path.basename(zip_path)}: {total} entradas ADJ/RES/FOR, {elegidas} de órganos de Murcia "
          f"({contratos} contratos)", flush=True)


if __name__ == "__main__":
    main()
