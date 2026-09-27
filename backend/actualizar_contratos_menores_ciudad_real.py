# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Ciudad Real (~75.000 hab., Castilla-La Mancha).

Fuente OFICIAL: una única página del perfil de contratante (`www.ciudadreal.es/ayuntamiento/perfil-contratante/
contratos-menores.html`) con un acordeón por año (2020-2026, todos en el mismo HTML -- no hace falta más de un
fetch). El formato cambia de era a mitad de camino:

  - **2020-2024**: cada contrato es un bloque de texto libre dentro del propio HTML del acordeón (nada
    descargable), con 4 campos SIEMPRE en el mismo orden y siempre los 4 presentes (verificado: el número de
    "OBJETO DEL CONTRATO"/"DURACION"/"IMPORTE"/"ADJUDICATARIO" coincide exactamente en cada año): objeto,
    duración, importe (con IVA, "IVA incluido" en el texto) y adjudicatario. **Sin fecha de adjudicación real
    ni NIF** -- se usa el mismo patrón que Fuente Álamo/Toledo (fecha vacía, ventana de 5 años aplicada a nivel
    de AÑO completo, no de contrato). Por eso se excluyen 2020 y 2021 enteros: 2021 es ambiguo (el corte de
    MENORES_DESDE_FECHA cae a mitad de año, 2021-09-01, y no hay forma de saber si un contrato de esa sección
    es de enero o de octubre) -- mismo criterio que Toledo con su fichero "2021" completo.
  - **2025 en adelante**: la fuente pasó a publicar ficheros XLSX descargables (uno por trimestre en 2025,
    uno acumulativo "formalizados" para el año en curso desde 2026), con columnas
    `numero_expediente, tipo_contrato, fecha_apertura, estado_administrativo, importe_sin_iva, importe_con_iva,
    cif_adjudicataria, empresa_adjudicataria, fecha_adjudicacion` -- SÍ trae NIF/CIF y fecha real de
    adjudicación, pero YA NO trae el objeto/descripción del contrato (se muestra vacío para estas filas). Se
    descartan las filas sin `fecha_adjudicacion` (expedientes todavía en trámite, no adjudicados: ~10 de 1.092
    en todo 2025, mayoría en el año en curso todavía sin cerrar).

**Cómo se encontró (2026-09-30, "prueba otra vía" tras Zaragoza)**: no hizo falta más que localizar la página
del perfil de contratante directamente en el propio site (`/ayuntamiento/perfil-contratante/contratos-
menores.html`, enlazada desde el menú de navegación) -- sin necesidad de portal de transparencia separado,
dataset abierto ni API. Tanto los bloques de texto libre como los enlaces a los XLSX de años futuros se leen
del MISMO fetch de esa única página (los años nuevos no rompen el conector: cualquier sección de año que
contenga enlaces a .xlsx se trata como "era XLSX", cualquier otra como "era texto libre").

Uso (desde backend/):
    python actualizar_contratos_menores_ciudad_real.py

Genera contratos_menores_ciudad_real.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_ciudad_real)."""
import gzip
import html as _html
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_ciudad_real.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_URL_PAGINA = "https://www.ciudadreal.es/ayuntamiento/perfil-contratante/contratos-menores.html"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"

# Años de la era "texto libre" a incluir sin ambigüedad de ventana (2020 y 2021 quedan fuera, ver docstring).
_ANOS_TEXTO_LIBRE_DESDE = 2022


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", _html.unescape(str(txt or ""))).strip()


def _importe(valor):
    """Parsea un importe en texto español ('16.940,00', a veces con la coma de miles mal puesta por error de
    la propia fuente, p.ej. '5,340,00') o un número/entero sin parte decimal ('12.200'). Ver el bug ya
    conocido de Toledo/Palma: nunca asumir que un separador es SIEMPRE el decimal.

    En la era de texto libre el importe viene seguido de la puntuación de la propia frase ("IVA incluido." /
    "IVA incluido," / "IVA y transporte incluidos"), y como el filtro de abajo conserva CUALQUIER '.'/',' que
    haya en el texto (no solo los del número), un punto o coma suelto de cierre de frase se cuela pegado al
    final y contamina el parseo (bug real encontrado: "5,340,00 € IVA incluido." -> "5,340,00." -> se leía
    534.000 en vez de 5.340). Por eso se recortan los separadores sueltos del final antes de parsear."""
    if isinstance(valor, (int, float)):
        return float(valor)
    t = re.sub(r"[^\d.,]", "", str(valor or ""))
    t = re.sub(r"[.,]+$", "", t)   # separador residual de cierre de frase, no del número (ver arriba)
    if not t:
        return 0.0
    if re.match(r"^\d+\.\d{2}$", t):   # formato inglés plano ("10700.00"), como en los XLSX de esta fuente
        return float(t)
    m = re.match(r"^(.+)[.,](\d{2})$", t)   # separador decimal de 2 cifras al final (con o sin miles delante)
    if m:
        entero = re.sub(r"[.,]", "", m.group(1))
        try:
            return float(f"{entero}.{m.group(2)}")
        except ValueError:
            pass
    try:
        return float(re.sub(r"[.,]", "", t))   # solo miles, sin parte decimal ("12.200" -> 12200)
    except ValueError:
        return 0.0


def _fecha_iso(valor):
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", str(valor or "").strip())
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return ""


def _parsear_bloque_texto_libre(html_seccion, anio):
    """2020-2024: bloques de texto libre "OBJETO DEL CONTRATO / DURACION / IMPORTE / ADJUDICATARIO",
    siempre los 4 en ese orden (verificado: el recuento de las 4 etiquetas coincide exactamente en cada año)."""
    texto = re.sub(r"<[^>]+>", " ", html_seccion)
    texto = _html.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    bloques = re.split(r"OBJETO\s+DEL\s+CONTRATO\s*:?", texto, flags=re.I)[1:]
    registros = []
    for i, b in enumerate(bloques):
        m_dur = re.search(r"DURACION\s*:?", b, re.I)
        m_imp = re.search(r"IMPORTE\s*:?", b, re.I)
        m_adj = re.search(r"ADJUDICATARIO\s*:?", b, re.I)
        if not (m_dur and m_imp and m_adj):
            continue   # bloque incompleto (no visto en la práctica, pero no se inventa nada si aparece)
        objeto = b[:m_dur.start()].strip(" :.,")
        importe_txt = b[m_imp.end():m_adj.start()]
        # cortar en el primer € o "IVA": el importe real siempre va ANTES: lo que sigue son incisos tipo
        # "IVA (10%) y portes incluidos" -- bug real encontrado: el "10" de "(10%)" se colaba pegado al
        # número real y multiplicaba el importe por 10 (9.147,75 -> 91.477.510,00).
        m_corte = re.search(r"€|iva", importe_txt, re.I)
        if m_corte:
            importe_txt = importe_txt[:m_corte.start()]
        adjudicatario = _limpiar(b[m_adj.end():]).strip(" :.,")
        if not adjudicatario:
            continue
        registros.append({
            "id":               f"ciudad_real::{anio}::{i}",
            "municipio":         "Ciudad Real",
            "provincia":         "ciudad-real",
            "fuente":            "ciudad_real",
            "organisme":         "Ayuntamiento de Ciudad Real",
            "adjudicatari":      adjudicatario,
            "nif":               "",   # no publicado en la era de texto libre (ver docstring)
            "import_num":        round(_importe(importe_txt), 2),
            "data_adjudicacio":  "",   # no publicada por contrato en esta era, ver docstring
            "tipus_contracte":   "",
            "descripcio":        _limpiar(objeto),
            "codi_cpv":          "",
            "exercici":          str(anio),
        })
    return registros


def _parsear_xlsx(crudo, url):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    ws = wb[wb.sheetnames[0]]
    filas = list(ws.iter_rows(values_only=True))
    # cabecera real en la fila 3 (0-indexada: fila 2), las 2 primeras son título/vacía
    cabecera = None
    idx_cab = None
    for i, fila in enumerate(filas[:5]):
        vals = [_limpiar(c) for c in fila]
        if "numero_expediente" in vals:
            cabecera = vals
            idx_cab = i
            break
    if cabecera is None:
        print(f"  !! {url}: cabecera no reconocida, fichero omitido", flush=True)
        return []
    try:
        idx_exp = cabecera.index("numero_expediente")
        idx_tipo = cabecera.index("tipo_contrato")
        idx_impsiniva = cabecera.index("importe_sin_iva")
        idx_impconiva = cabecera.index("importe_con_iva")
        idx_cif = cabecera.index("cif_adjudicataria")
        idx_emp = cabecera.index("empresa_adjudicataria")
        idx_fadj = cabecera.index("fecha_adjudicacion")
    except ValueError as e:
        print(f"  !! {url}: columna no encontrada ({e}), fichero omitido", flush=True)
        return []

    registros = []
    for fila in filas[idx_cab + 1:]:
        if len(fila) <= max(idx_exp, idx_tipo, idx_impsiniva, idx_impconiva, idx_cif, idx_emp, idx_fadj):
            continue
        fecha = _fecha_iso(fila[idx_fadj])
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue   # sin adjudicar todavía, o fuera de ventana
        empresa = _limpiar(fila[idx_emp])
        if not empresa:
            continue
        # bug real de origen encontrado (2026-09-30): en un puñado de filas la celda de importe_con_iva
        # contiene una FECHA (datetime), no un número -- error de tecleo/formato de la propia fuente al
        # rellenar la hoja (p.ej. "6.638,00" mal interpretado como fecha por Excel; nunca hay que
        # convertir ese datetime a texto y parsearlo como si fuera un número -- sale un valor disparatado).
        # Se usa importe_sin_iva en su lugar; si esa celda TAMBIÉN es una fecha (visto al menos una vez),
        # se deja en 0 -- no se inventa un importe.
        def _valor_seguro(celda):
            return None if hasattr(celda, "strftime") else _importe(celda)
        importe = _valor_seguro(fila[idx_impconiva])
        if importe is None:
            importe = _valor_seguro(fila[idx_impsiniva])
        if importe is None:
            importe = 0.0
        registros.append({
            "id":               f"ciudad_real::{_limpiar(fila[idx_exp]) or fecha + '::' + empresa}",
            "municipio":         "Ciudad Real",
            "provincia":         "ciudad-real",
            "fuente":            "ciudad_real",
            "organisme":         "Ayuntamiento de Ciudad Real",
            "adjudicatari":      empresa,
            "nif":               _limpiar(fila[idx_cif]),
            "import_num":        round(importe, 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   _limpiar(fila[idx_tipo]),
            "descripcio":        "",   # esta era no publica objeto/descripción (ver docstring)
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def main():
    print("Descargando página de contratos menores...", flush=True)
    pagina = _get(_URL_PAGINA).decode("utf-8", errors="replace")

    existentes = {}
    for m in re.finditer(r'id="(\d{4})">(.*?)</div></div></div>', pagina, re.S):
        anio = int(m.group(1))
        seccion = m.group(2)
        urls_xlsx = re.findall(r'href="([^"]+\.xlsx)"', seccion, re.I)
        if urls_xlsx:
            for url_rel in urls_xlsx:
                url = url_rel if url_rel.startswith("http") else f"https://www.ciudadreal.es{url_rel}"
                print(f"  {anio}: descargando {url}...", flush=True)
                try:
                    crudo = _get(url)
                except Exception as e:
                    print(f"    !! error de descarga ({type(e).__name__}: {e})", flush=True)
                    continue
                registros = _parsear_xlsx(crudo, url)
                for r in registros:
                    existentes[r["id"]] = r
                print(f"    {len(registros)} contratos en ventana", flush=True)
        elif anio >= _ANOS_TEXTO_LIBRE_DESDE:
            registros = _parsear_bloque_texto_libre(seccion, anio)
            for r in registros:
                existentes[r["id"]] = r
            print(f"  {anio} (texto libre): {len(registros)} contratos", flush=True)
        else:
            print(f"  {anio}: fuera de ventana o ambiguo, omitido (ver docstring)", flush=True)

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Ciudad Real. 2022-2024: bloques de texto "
                             "libre del perfil de contratante (objeto+importe con IVA+adjudicatario, sin "
                             "fecha real ni NIF). 2025 en adelante: XLSX oficiales con NIF y fecha real de "
                             "adjudicación, pero sin objeto/descripción. Ver "
                             "actualizar_contratos_menores_ciudad_real.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
