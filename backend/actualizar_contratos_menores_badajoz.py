# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Badajoz (~150.000 hab., la mayor ciudad de Extremadura sin conectar
hasta ahora en ningún frente -- ver LIMITACIONES_COBERTURA.md, "Cierre de España").

Fuente OFICIAL: `aytobadajoz.es/es/ayto/perfil-del-contratante`, un selector de AÑO + CATEGORÍA (formulario JS,
sin URL propia por combinación -- se navega con Playwright, seleccionando cada año 2021-2026 × cada categoría
"... - Contrato Menor" -- hay tres entidades con contratación propia: AYTO (Ayuntamiento), IMSS (Instituto
Municipal de Servicios Sociales) e IFEBA (Institución Ferial). Cada expediente de la lista filtrada muestra un
enlace "Documento PDF" junto a la etiqueta "Adjudicación Definitiva" (identificado por su atributo
`title="Documento PDF: Adjudicación Definitiva..."`, no por el nombre de fichero, que es muy inconsistente:
desde "1632-23_adjudicacion_contrato_menor.pdf" hasta "tomodule_(97).pdf" o "DECRETO ADJUDICACION FIRMADO(1).pdf")
-- ese PDF es el decreto/resolución real de adjudicación, con el nombre del adjudicatario y el importe.

**IMPORTANTE -- alcance real de esta fuente**: el propio PDF de adjudicación se titula "ADJUDICACION MENOR CON
PUBLICIDAD": este selector de "Contrato Menor" parece cubrir solo los contratos menores que el Ayuntamiento
decide publicar con concurrencia pública (varias empresas invitadas a presentar oferta), no necesariamente el
universo completo de contratos menores de adjudicación directa sin publicidad -- de ahí que el volumen anual
sea pequeño (4-14 por año y entidad) comparado con otras ciudades de tamaño similar. Se documenta así en la
descripción del fichero: es una fuente OFICIAL y VERIFICADA, pero probablemente parcial.

**Dos formatos de PDF de adjudicación, con patrones de texto distintos** (verificado descargando varios de
cada tipo):
- **AYTO**: "Adjudicar el expediente referenciado a <NOMBRE>, por importe de <IMPORTE> €" (sin NIF).
- **IMSS**: tabla "Adjudicatario propuesto / PRESUPUESTO" con una fila "<NIF> <NOMBRE> <IMPORTE>€" (con NIF).
Se prueban ambos patrones en orden; si ninguno coincide, el expediente se omite y se cuenta como "sin
parsear" (para revisar a mano si el número es alto).

**Fecha**: se toma de "de fecha <día> de <mes> de <año>" en el propio texto del decreto (formato AYTO) o de la
fecha de la resolución cuando no hay esa frase (formato IMSS, se usa el "Fecha de emisión" del pie del
documento firmado electrónicamente). Nunca se usa la "Fecha Publicación" de la lista (es la fecha en que se
abrió el plazo de ofertas, no la de adjudicación).

Uso (desde backend/, requiere Playwright):
    python actualizar_contratos_menores_badajoz.py

Genera contratos_menores_badajoz.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_badajoz)."""
import gzip
import io
import json
import os
import re
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_badajoz.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_BASE_URL = "https://www.aytobadajoz.es"
_URL_PERFIL = f"{_BASE_URL}/es/ayto/perfil-del-contratante"
_CATS = {"AYTO - Contrato Menor": "Ayuntamiento de Badajoz",
         "IMSS - Contrato Menor": "Instituto Municipal de Servicios Sociales (IMSS) de Badajoz",
         "IFEBA - Contrato Menor": "Institución Ferial de Badajoz (IFEBA)"}
_ANOS = ["2021", "2022", "2023", "2024", "2025", "2026"]

_MESES = {"enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
          "julio": "07", "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11",
          "diciembre": "12"}


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _importe(txt):
    """Texto en notación española SIEMPRE (estos documentos nunca usan notación inglesa): la coma es el
    separador decimal y el punto SIEMPRE es separador de miles, tenga uno o los dígitos que tenga detrás --
    '6.000' son seis mil euros, no seis con cero céntimos (bug encontrado: un primer intento trataba un único
    punto sin coma como separador decimal, convirtiendo '6.000€' en 6,00€)."""
    t = re.sub(r"[^\d.,]", "", str(txt or ""))
    if not t:
        return 0.0
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _fecha_desde_texto(texto):
    """'de fecha 3 de octubre de 2023' -> '2023-10-03'. Si no hay esa frase, intenta 'Fecha de emisión: 31 de
    Enero de 2023'."""
    t = re.sub(r"\s+", " ", texto)
    for patron in (r"de fecha\s+(\d{1,2})\s+de\s+([a-zA-Zéáíóú]+)\s+de\s+(\d{4})",
                   r"Fecha de emisi[oó]n:\s*(\d{1,2})\s+de\s+([a-zA-Zéáíóú]+)\s+de\s+(\d{4})"):
        m = re.search(patron, t, re.IGNORECASE)
        if m:
            dia, mes_txt, anio = m.groups()
            mes = _MESES.get(mes_txt.lower())
            if mes:
                return f"{anio}-{mes}-{dia.zfill(2)}"
    return ""


def _extraer_adjudicacion(texto):
    """Devuelve (adjudicatario, nif, importe) o (None, None, None) si no coincide ningún patrón conocido.
    Los PDF de Badajoz rompen línea en puntos impredecibles (a veces en mitad de una frase o de un nombre de
    empresa) -- se normaliza todo el texto a espacios simples antes de aplicar los patrones, en vez de intentar
    adivinar dónde puede caer cada salto de línea."""
    t = re.sub(r"\s+", " ", texto)
    # Formato AYTO: "Adjudicar el expediente referenciado a X, por importe de Y €"
    m = re.search(r"[Aa]djudicar el expediente referenciado a (.+?), por importe de ([\d.,]+)\s*€", t)
    if m:
        return _limpiar(m.group(1)), "", _importe(m.group(2))
    # Formato IMSS (tabla): "Adjudicatario propuesto PRESUPUESTO" seguida de "NIF. NOMBRE IMPORTE€"
    # (el NIF puede ser CIF -letra+8 dígitos, a veces con guion- o DNI -8 dígitos+letra-, así que el primer
    # carácter puede ser letra o dígito).
    m = re.search(r"[Aa]djudicatario propuesto PRESUPUESTO ([A-Z0-9][A-Z0-9\-]{6,9})\.?\s+"
                  r"([A-ZÁÉÍÓÚÑ.,\- ]+?) ([\d.,]+)\s*€", t)
    if m:
        return _limpiar(m.group(2)), m.group(1).strip(), _importe(m.group(3))
    # Formato IMSS (resolución en prosa): "a favor de la empresa X, con NIF/CIF: Y que llevará a cabo la
    # ejecución del mismo por un precio total de Z €"
    m = re.search(r"a favor de la empresa (.+?)\.?,?\s*con (?:NIF|CIF):\s*([A-Z0-9][A-Z0-9\-]{6,9}) "
                  r"que llevar[áa] a cabo.*?precio total de ([\d.,]+)\s*€", t)
    if m:
        return _limpiar(m.group(1)), m.group(2).strip(), _importe(m.group(3))
    return None, None, None


def main():
    from playwright.sync_api import sync_playwright

    combos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(_URL_PERFIL, wait_until="networkidle", timeout=45000)
        for anio in _ANOS:
            for cat in _CATS:
                page.select_option("select[name='anio']", anio)
                page.wait_for_timeout(200)
                page.select_option("select[name='setcat']", label=cat)
                page.wait_for_timeout(1200)
                pdfs = page.eval_on_selector_all(
                    "a[title*='Adjudicaci']", "els => els.map(e => e.getAttribute('href'))")
                for href in pdfs:
                    combos.append((anio, cat, href))
        pdfs_unicos = sorted({href for _, _, href in combos})
        print(f"{len(pdfs_unicos)} PDFs de adjudicación únicos encontrados (2021-2026, 3 entidades).", flush=True)

        existentes = {}
        sin_parsear = 0
        for href in pdfs_unicos:
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"
            try:
                resp = page.context.request.get(url)
                contenido = resp.body()
            except Exception as e:
                print(f"  !! error descargando {url}: {e}", flush=True)
                continue
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                    texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
            except Exception as e:
                print(f"  !! error leyendo PDF {url}: {e}", flush=True)
                continue
            adjudicatari, nif, importe = _extraer_adjudicacion(texto)
            if not adjudicatari or importe <= 0:
                sin_parsear += 1
                print(f"  !! sin parsear (patrón no reconocido): {url}", flush=True)
                continue
            fecha = _fecha_desde_texto(texto)
            if not fecha or fecha < MENORES_DESDE_FECHA:
                continue
            t_norm = re.sub(r"\s+", " ", texto)
            m_exp = re.search(r"exp(?:te\.?|ediente)?\.?\s*(?:n[.º°]?:?\s*)?(?:IMSS\s*)?"
                              r"(\d[\d/\-]{1,10})", t_norm, re.IGNORECASE)
            expediente = m_exp.group(1) if m_exp else href.rsplit("/", 1)[-1]
            entidad = next((v for k, v in _CATS.items() if k.split(" - ")[0].lower() in url.lower()
                             or "imss" in url.lower() and k.startswith("IMSS")
                             or "ifeba" in url.lower() and k.startswith("IFEBA")), "Ayuntamiento de Badajoz")
            # descripción: entre comillas tipográficas (formato IMSS en prosa) o, si no hay, entre la línea del
            # expediente y el arranque de la fórmula de firma (formato AYTO)
            m_obj = (re.search(r"[“\"]([^”\"]{8,220})[”\"]", t_norm)
                     or re.search(r"CONTRATO MENOR\s*EXP\.?\s*\d[\d/\-]*\s+(.{8,220}?)\s+El (?:Ilmo|Excmo)", t_norm))
            descripcio = _limpiar(m_obj.group(1)) if m_obj else ""
            reg_id = f"badajoz::{expediente}"
            existentes[reg_id] = {
                "id":               reg_id,
                "municipio":         "Badajoz",
                "provincia":         "badajoz",
                "fuente":            "badajoz",
                "organisme":         entidad,
                "adjudicatari":      adjudicatari,
                "nif":               nif or "",
                "import_num":        round(importe, 2),
                "data_adjudicacio":  fecha,
                "tipus_contracte":   "",
                "descripcio":        descripcio,
                "codi_cpv":          "",
                "exercici":          fecha[:4],
            }
        browser.close()

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Badajoz (y sus entidades IMSS e IFEBA), "
                             "obtenidos de los decretos/resoluciones de adjudicación en PDF enlazados desde su "
                             "Perfil del Contratante (navegado con Playwright, selector de año/categoría sin "
                             "URL propia). Los propios PDF se titulan 'MENOR CON PUBLICIDAD': es probable que "
                             "esta fuente cubra solo los contratos menores publicados con concurrencia, no el "
                             "universo completo de adjudicación directa sin publicidad. Ver "
                             "actualizar_contratos_menores_badajoz.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({sin_parsear} PDFs sin parsear, patrón no "
          "reconocido).")


if __name__ == "__main__":
    main()
