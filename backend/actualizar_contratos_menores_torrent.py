# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Torrent (~85.000 hab., Comunitat Valenciana), encontrado siguiendo el
punto de la instrucción de César de retomar Comunitat Valenciana por población más allá de Valencia/Alicante.

Fuente OFICIAL: "Perfil del contratante > Datos" (torrent.es/perfil-del-contratante/datos/), sección
"Contratos menores": informes trimestrales en XLSX desde 2019, publicados por el propio Ayuntamiento. La página
es una SPA/Elementor que no expone los enlaces en un fetch simple (probado, curl no encuentra nada) -- se
encontraron navegando la página con Playwright.

**Los enlaces NO siguen un patrón de URL predecible** (mezcla de `wp-content/uploads/<año>/<mes>/...xlsx` con
nombres de fichero inconsistentes, y una carpeta legacy `torrentPublic/docroot/repositorio/...` para 2019-2022):
se han recogido a mano navegando esa página; si aparece un trimestre nuevo hay que localizar su URL igual y
añadirlo a FICHEROS.

**Las columnas cambian de nombre entre eras** (verificado descargando un fichero de 2021 y uno de 2025):
- Hasta ~2022: Expediente | Objeto Contrato | Procedimiento | Tipo Contrato | Duración | Importe Lic. sin imp. |
  Núm. licitadores | Doc. adjudicatario (NIF) | Adjudicatario | Fecha Adjudicación
- Desde ~2023: Nº Expte | Expediente | Objeto contrato | Tipo contrato | Duración | Importe adj. Sin impuest |
  Nº licitadores | Adjudicatario | Fecha adjudicación (SIN columna de NIF)
Se leen SIEMPRE por nombre de columna (normalizado sin tildes/mayúsculas), nunca por posición, buscando qué
cabecera coincide mejor con cada campo. El importe es SIEMPRE "sin impuestos" (sin IVA) en ambas eras -- se
marca en _FUENTES_CM_SIN_IVA en app.py. Cuando no hay columna de NIF (2023 en adelante) se deja vacío.

Uso (desde backend/):
    python actualizar_contratos_menores_torrent.py

Genera contratos_menores_torrent.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_torrent).
"""
import gzip
import json
import os
import re
import time
import unicodedata
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_torrent.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"

# (año, trimestre) -> URL exacta del XLSX (recogidas a mano navegando torrent.es/perfil-del-contratante/datos/
# con un navegador real, ver docstring del módulo)
FICHEROS = {
    (2021, 3): "https://www.torrent.es/torrentPublic/docroot/repositorio/Serveis%20admin/Perfil%20del%20"
               "contractant/Indicadors/70_Contratos%20menores/2021/Contractes_menors_2021_3T.xlsx",
    (2021, 4): "https://www.torrent.es/torrentPublic/docroot/repositorio/Serveis%20admin/Perfil%20del%20"
               "contractant/Indicadors/70_Contratos%20menores/2021/Contractes_menors_2021_4T.xlsx",
    (2022, 1): "https://www.torrent.es/torrentPublic/docroot/repositorio/Serveis%20admin/Perfil%20del%20"
               "contractant/Indicadors/70_Contratos%20menores/2022/Contractes_menors_2022_1T.xlsx",
    (2022, 2): "https://torrent.es/wp-content/uploads/2022/10/CNTR-contratos-menores-2T-2022.xlsx",
    (2022, 3): "https://torrent.es/wp-content/uploads/2022/11/CNTR-contratos-menores-3T-2022.xlsx",
    (2022, 4): "https://torrent.es/wp-content/uploads/2023/02/CNTR-contratos-menores-4T-2022.xlsx",
    (2023, 1): "https://torrent.es/wp-content/uploads/2023/04/CNTR-contratos-menores-1T-2023.xlsx",
    (2023, 2): "https://torrent.es/wp-content/uploads/2023/07/2o-trimestre-2023.xlsx",
    (2023, 3): "https://torrent.es/wp-content/uploads/2023/10/3o-trimestre-2023.xlsx",
    (2023, 4): "https://torrent.es/wp-content/uploads/2024/01/Contratos-menores-4-trim-2023.xlsx",
    (2024, 1): "https://torrent.es/wp-content/uploads/2024/04/CNTR-contratos-menores-1T-2024.xlsx",
    (2024, 2): "https://torrent.es/wp-content/uploads/2024/07/CONT-Contratos-menores-2T-2024.xlsx",
    (2024, 3): "https://torrent.es/wp-content/uploads/2024/10/CONT-Contratos-menores-3T-2024.xlsx",
    (2024, 4): "https://torrent.es/wp-content/uploads/2025/01/CONT-Contratos-menores-4T-2024.xlsx",
    (2025, 1): "https://torrent.es/wp-content/uploads/2025/04/1-trimestre-2025.xlsx",
    (2025, 2): "https://torrent.es/wp-content/uploads/2025/07/2-trimestre-2025.xlsx",
    (2025, 3): "https://torrent.es/wp-content/uploads/2025/10/3-trimestre-2025.xlsx",
    (2025, 4): "https://torrent.es/wp-content/uploads/2026/01/4-trimestre-2025.xlsx",
    (2026, 1): "https://torrent.es/wp-content/uploads/2026/04/1-trimestre-2026.xlsx",
    (2026, 2): "https://torrent.es/wp-content/uploads/2026/07/2-trimestre-2026.xlsx",
}


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn").lower()).strip()


def _buscar_col(cabecera, *, contiene, no_contiene=()):
    """Índice de la primera columna cuyo nombre normalizado contiene TODAS las palabras de `contiene` y
    NINGUNA de `no_contiene`. None si no hay ninguna."""
    for i, c in enumerate(cabecera):
        n = _norm(c)
        if all(p in n for p in contiene) and not any(p in n for p in no_contiene):
            return i
    return None


def _importe(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    t = re.sub(r"[^\d.,]", "", str(valor or ""))
    if not t:
        return 0.0
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return 0.0


def _fecha_iso(valor):
    import datetime
    if isinstance(valor, datetime.datetime):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return ""


def _descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _parsear_trimestre(anio, trimestre, crudo):
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    ws = wb.worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return []
    # la fila de cabecera real no siempre es la primera: algunos ficheros llevan filas de título/fecha antes
    # (mismo patrón que el ODS de Alicante) -- se busca la primera fila cuya normalización de alguna celda sea
    # exactamente "expediente"
    idx_cabecera = next((i for i, f in enumerate(filas[:30])
                          if any(_norm(c) == "expediente" for c in f)), None)
    if idx_cabecera is None:
        print(f"  !! {anio}T{trimestre}: no se encontró la fila de cabecera ('Expediente') en las primeras "
              "30 filas, fichero omitido", flush=True)
        return []
    filas = filas[idx_cabecera:]
    cabecera = [str(c or "") for c in filas[0]]
    i_exp = _buscar_col(cabecera, contiene=("expediente",))
    i_obj = _buscar_col(cabecera, contiene=("objeto",))
    i_tipo = _buscar_col(cabecera, contiene=("tipo",))
    i_imp = _buscar_col(cabecera, contiene=("importe",))
    i_nif = _buscar_col(cabecera, contiene=("doc",))   # "Doc. adjudicatario" (solo en ficheros antiguos)
    i_adj = _buscar_col(cabecera, contiene=("adjudicatario",), no_contiene=("doc",))
    i_fecha = _buscar_col(cabecera, contiene=("fecha",))
    if None in (i_exp, i_obj, i_imp, i_adj, i_fecha):
        print(f"  !! {anio}T{trimestre}: no se identificaron todas las columnas necesarias en la cabecera "
              f"{cabecera!r}, fichero omitido", flush=True)
        return []
    registros = []
    for fila in filas[1:]:
        if not fila or not any(fila):
            continue
        expediente = str(fila[i_exp] or "").strip()
        adjudicatari = str(fila[i_adj] or "").strip()
        if not expediente or not adjudicatari or fila[i_imp] is None:
            continue   # importe en blanco en la propia fuente (no es un 0 real): se omite, no se inventa
        fecha = _fecha_iso(fila[i_fecha])
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        registros.append({
            "id":               f"torrent::{expediente}",
            "municipio":         "Torrent",
            "provincia":         "valencia",
            "fuente":            "torrent",
            "organisme":         "Ayuntamiento de Torrent",
            "adjudicatari":      adjudicatari,
            "nif":               str(fila[i_nif] or "").strip() if i_nif is not None else "",
            "import_num":        round(_importe(fila[i_imp]), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   str(fila[i_tipo] or "").strip() if i_tipo is not None else "",
            "descripcio":        str(fila[i_obj] or "").strip(),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Torrent, informes trimestrales oficiales en "
                             "XLSX (Perfil del contratante), encontrados navegando la página con un navegador "
                             "real (Playwright). Importe SIN IVA. NIF solo disponible en los ficheros hasta "
                             "2022 (la fuente deja de publicar esa columna desde 2023). "
                             "Ver actualizar_contratos_menores_torrent.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    total_bruto = 0
    for (anio, trimestre), url in sorted(FICHEROS.items()):
        print(f"Descargando {anio}T{trimestre}...", flush=True)
        try:
            crudo = _descargar(url)
        except Exception as e:
            print(f"  !! {anio}T{trimestre}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_trimestre(anio, trimestre, crudo)
        total_bruto += len(registros)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio}T{trimestre}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_bruto} filas brutas procesadas, "
          f"{total_bruto - len(existentes)} colapsadas por clave repetida).")


if __name__ == "__main__":
    main()
