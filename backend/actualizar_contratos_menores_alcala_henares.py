# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Alcalá de Henares (~195.000 hab., Comunidad de Madrid).

Fuente OFICIAL: informes trimestrales en PDF (hacienda.ayto-alcaladehenares.es/s-informacion-contratos-menores/,
certificado SSL inválido -- lectura sin verificar, mismo caso ya aceptado para el conector de sueldos de esta
misma ciudad). Sin tabla real reconocible por `pdfplumber` (`extract_table()` no encuentra nada en ningún
trimestre probado) -- son informes contables de líneas de texto libre, parseados aquí línea a línea con
expresiones regulares sobre `extract_text()`.

**Dos formatos estructuralmente distintos según la época** (comprobado en vivo, 2026-09-29):

1. **Formato "Tercero" (hasta 2023, aprox.)**: el nombre del acreedor aparece en su PROPIA línea (detectada
   porque la línea SIGUIENTE es literalmente "Aplicación Presupuestaria ..."), seguida de una o varias líneas
   de registro (`Núm.Oper. Fecha Objeto Importe`), hasta una línea "TOTAL TRIMESTRE <importe>". **Esta fuente
   NO publica NIF/CIF en absoluto** en este formato -- ni máscarado ni completo.

2. **Formato "ADO" (2024 en adelante)**: cada registro es una línea que empieza por `<número> ADO <fecha>`,
   seguida de NIF (con las personas físicas MASCARADO, p.ej. "***8694**" -- se guarda tal cual, nunca se
   intenta "desenmascarar") o CIF completo (empresas, sin máscara), el nombre del adjudicatario, un código de
   aplicación presupuestaria y el año, en un ORDEN que varía de un trimestre a otro (comprobado: en 2024T1 el
   orden es fecha-año-código-NIF-nombre; en 2025T3 es fecha-NIF-nombre-código-año) -- por eso NO se asume una
   posición fija: se extraen por PATRÓN (el NIF por su forma, el importe por ser el último de 4 números al
   final de la línea, el año por coincidir con el de la fecha, el código de aplicación por ser un número largo
   suelto) y lo que queda del texto es el nombre. El objeto del contrato viene en la(s) línea(s) siguiente(s),
   hasta una línea "TOTAL PARTIDA"/"TOTAL ACREEDOR" (se descartan, son subtotales, no registros nuevos).

Dado el volumen de páginas (hasta 67 por trimestre) y la naturaleza heurística del parseo, se registra cuántas
líneas candidatas a registro NO se pudieron interpretar, para poder revisar a mano si ese número es alto en
algún trimestre nuevo.

Uso (desde backend/):
    python actualizar_contratos_menores_alcala_henares.py

Genera contratos_menores_alcala_henares.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_alcala_henares)."""
import gzip
import io
import json
import os
import re
import ssl
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_alcala_henares.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_BASE = "https://hacienda.ayto-alcaladehenares.es/wp-content/uploads"
# (año, trimestre) -> URL exacta (recogidas a mano de la página de contratos menores, 2026-09-29).
FICHEROS = {
    (2021, 3): f"{_BASE}/2022/01/Contratos-Menores-3er-TRIM.2021.pdf",
    (2021, 4): f"{_BASE}/2022/04/Contratos-Menores-4o-TRIM.2021.pdf",
    (2022, 1): f"{_BASE}/2022/05/Contratos-menores-1er-TRIM.2022.pdf",
    (2022, 2): f"{_BASE}/2022/07/C.-MENOR-2T-2022-1.pdf",
    (2022, 3): f"{_BASE}/2022/10/C.-MENOR-3ER-T-2022.pdf",
    (2022, 4): f"{_BASE}/2023/03/4T-2022-MENORES-2.pdf",
    (2023, 1): f"{_BASE}/2023/05/1-T-MENORES-2023.pdf",
    (2023, 2): f"{_BASE}/2023/08/2T-MENORES-2023.pdf",
    (2023, 3): f"{_BASE}/2023/11/PMP-3T-2023-2.pdf",   # nombre raro, pero SÍ es el informe de menores (comprobado)
    (2023, 4): f"{_BASE}/2024/03/MENORES-4-T-2023.pdf",
    (2024, 1): f"{_BASE}/2024/06/MENORES-1ER-TRIM.-2024.pdf",
    (2024, 2): f"{_BASE}/2024/11/MENORES-2o-T-2024.pdf",
    (2024, 3): f"{_BASE}/2024/11/MENORES-3-T-2024.pdf",
    (2024, 4): f"{_BASE}/2025/02/4-T-MENORES-2024-1.pdf",
    (2025, 1): f"{_BASE}/2025/04/MENORES-1ER-TRIM-2025-1.pdf",
    (2025, 2): f"{_BASE}/2025/07/MENORES-2o-TRIM-2025.pdf",
    (2025, 3): f"{_BASE}/2025/10/MENORES-3ER-TRIM-2025-1.pdf",
    (2025, 4): f"{_BASE}/2026/02/MENORES-4T-2025.pdf",
    (2026, 1): f"{_BASE}/2026/04/MENORES-1ER-TRIM.-2026.pdf",
    (2026, 2): f"{_BASE}/2026/08/MENORES-2o-TRIM-2026-2.pdf",
}

_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_CTX_SIN_VERIFICAR = ssl._create_unverified_context()   # certificado SSL inválido en este dominio, comprobado

_RE_ADO_INICIO = re.compile(r"^(\d{10,})\s+ADO\s+(\d{2}/\d{2}/\d{4})\s+(.+)$")
_RE_TERCERO_INICIO = re.compile(r"^(\d{10,})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.,]+)$")
_RE_APLIC_PPTA = re.compile(r"^Aplicación Presupuestaria", re.IGNORECASE)
_RE_TOTAL_TRIM = re.compile(r"^TOTAL TRIMESTRE\b", re.IGNORECASE)
_RE_TOTAL_PARTIDA_O_ACREEDOR = re.compile(r"^TOTAL (PARTIDA|ACREEDOR)\b", re.IGNORECASE)

_RE_NIF_MASCARADO = re.compile(r"\*{2,3}\d{2,5}\*{0,2}")
_RE_NIF_CIF = re.compile(r"\b[A-Z]\d{7,8}")   # sin \b final: a veces el PDF no deja espacio entre el CIF y
_RE_NIF_DNI = re.compile(r"\b\d{8}[A-Z]\b")   # el nombre que sigue ("A80282114FERRETERIA...", comprobado)
_RE_CODIGO_LARGO = re.compile(r"\b\d{6,15}\b")
_RE_4_NUMEROS_FINAL = re.compile(r"([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=90, context=_CTX_SIN_VERIFICAR) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).replace("ﬁ", "fi").strip(" ,.")


def _fecha_iso(dmy):
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", dmy or "")
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def _importe(txt):
    limpio = (txt or "").replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _extraer_paginas_texto(crudo):
    import pdfplumber
    lineas = []
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            lineas.extend(texto.split("\n"))
    return lineas


def _parsear_resto_ado(resto, fecha_iso):
    """Extrae NIF/nombre/importe de la parte variable de una línea 'ADO' -- por PATRÓN, no por posición fija
    (ver docstring del módulo: el orden de los campos varía de un trimestre a otro)."""
    m = _RE_4_NUMEROS_FINAL.search(resto)
    if not m:
        return None
    importe = m.group(4)
    resto = resto[:m.start()].strip()

    nif = ""
    for patron in (_RE_NIF_MASCARADO, _RE_NIF_CIF, _RE_NIF_DNI):
        m2 = patron.search(resto)
        if m2:
            nif = m2.group(0)
            resto = resto[:m2.start()] + " " + resto[m2.end():]
            break

    anio_fecha = fecha_iso[:4] if fecha_iso else ""
    if anio_fecha:
        resto = re.sub(r"(?<!\d)" + anio_fecha + r"(?!\d)", " ", resto)
    resto = _RE_CODIGO_LARGO.sub(" ", resto)
    # a veces el código de aplicación presupuestaria viene en formato "23/338/" (con barras) en vez de un
    # número largo suelto -- se ve como un resto pegado al final del nombre, se recorta aparte
    resto = re.sub(r"\s*\d{1,4}/\d{1,4}/?\s*$", " ", resto)
    nombre = _limpiar(resto)
    return nif, nombre, importe


def _procesar_formato_ado(lineas, contador):
    registros = []
    i = 0
    while i < len(lineas):
        linea = lineas[i].strip()
        m = _RE_ADO_INICIO.match(linea)
        if not m:
            i += 1
            continue
        id_, fecha_dmy, resto = m.groups()
        fecha = _fecha_iso(fecha_dmy)
        parsed = _parsear_resto_ado(resto, fecha)
        i += 1
        if parsed is None:
            contador["ado_no_reconocidas"] += 1
            continue
        nif, nombre, importe_txt = parsed
        # Posible continuación del nombre en la línea siguiente -- el nombre se corta a veces a mitad de
        # palabra por el ancho de columna del PDF ("AGUIRRE*AVELLANO,FRA" + "NCISCO JAVIER" en la línea de
        # abajo, partiendo literalmente "FRANCISCO" en dos). NO se puede detectar buscando "FRA." como marca
        # de inicio de descripción (bug real: esa abreviatura de factura varía, "FRA.", "FA.", o directamente
        # el número sin prefijo alguno según el trimestre) -- se usa en su lugar que una continuación de
        # nombre es una línea CORTA hecha solo de letras y espacios (sin dígitos ni puntuación), mientras que
        # la descripción real siempre es mucho más larga y con dígitos/puntuación.
        if (i < len(lineas) and re.match(r"^[A-Za-zÀ-ſ\s]{1,25}$", lineas[i].strip())
                and not _RE_TOTAL_PARTIDA_O_ACREEDOR.match(lineas[i].strip())
                and not _RE_ADO_INICIO.match(lineas[i].strip())):
            nombre = _limpiar(nombre + " " + lineas[i].strip())
            i += 1
        desc_lineas = []
        tope = i + 20
        while i < len(lineas) and i < tope:
            l2 = lineas[i].strip()
            if _RE_TOTAL_PARTIDA_O_ACREEDOR.match(l2):
                i += 1
                # puede haber una segunda línea TOTAL (ACREEDOR y PARTIDA, en cualquier orden)
                if i < len(lineas) and _RE_TOTAL_PARTIDA_O_ACREEDOR.match(lineas[i].strip()):
                    i += 1
                break
            if _RE_ADO_INICIO.match(l2):
                break   # se coló el siguiente registro sin ver una línea TOTAL -- cortar aquí, defensivo
            desc_lineas.append(l2.lstrip("* "))
            i += 1
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        registros.append({
            "id":               f"alcala_henares::{id_}",
            "municipio":         "Alcalá de Henares",
            "provincia":         "madrid",
            "fuente":            "alcala_henares",
            "organisme":         "Ayuntamiento de Alcalá de Henares",
            "adjudicatari":      nombre or "No localizada",
            "nif":               nif,
            "import_num":        round(_importe(importe_txt), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        _limpiar(" ".join(desc_lineas)),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def _procesar_formato_tercero(lineas, contador):
    registros = []
    nombre_actual = ""
    for i, linea in enumerate(lineas):
        l = linea.strip()
        if not l:
            continue
        if i + 1 < len(lineas) and _RE_APLIC_PPTA.match(lineas[i + 1].strip()):
            nombre_actual = _limpiar(l)
            continue
        m = _RE_TERCERO_INICIO.match(l)
        if not m:
            continue
        id_, fecha_dmy, objeto, importe_txt = m.groups()
        fecha = _fecha_iso(fecha_dmy)
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        # el objeto puede continuar en la línea siguiente (hasta "TOTAL TRIMESTRE")
        desc = [objeto]
        j = i + 1
        tope = j + 10
        while j < len(lineas) and j < tope:
            l2 = lineas[j].strip()
            if not l2 or _RE_TOTAL_TRIM.match(l2) or _RE_TERCERO_INICIO.match(l2) or _RE_APLIC_PPTA.match(l2):
                break
            desc.append(l2)
            j += 1
        registros.append({
            "id":               f"alcala_henares::{id_}",
            "municipio":         "Alcalá de Henares",
            "provincia":         "madrid",
            "fuente":            "alcala_henares",
            "organisme":         "Ayuntamiento de Alcalá de Henares",
            "adjudicatari":      nombre_actual or "No localizada",
            "nif":               "",   # esta fuente no publica NIF en este formato (ver docstring)
            "import_num":        round(_importe(importe_txt), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        _limpiar(" ".join(desc)),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def _parsear(crudo, etiqueta):
    lineas = _extraer_paginas_texto(crudo)
    contador = {"ado_no_reconocidas": 0}
    es_formato_ado = any(_RE_ADO_INICIO.match(l.strip()) for l in lineas[:200])
    if es_formato_ado:
        registros = _procesar_formato_ado(lineas, contador)
    else:
        registros = _procesar_formato_tercero(lineas, contador)
    if contador["ado_no_reconocidas"]:
        print(f"  !! {etiqueta}: {contador['ado_no_reconocidas']} líneas 'ADO ...' no se pudieron interpretar "
              "(sin los 4 números finales esperados) -- revisar a mano si es un número alto", flush=True)
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Alcalá de Henares, informes trimestrales "
                             "oficiales en PDF (sin tabla real, parseados línea a línea). Dos formatos "
                             "distintos según la época -- ver actualizar_contratos_menores_alcala_henares.py. "
                             "NIF de personas físicas MASCARADO en el formato reciente (solo los últimos "
                             "dígitos visibles, tal cual lo publica la fuente); sin NIF en absoluto en el "
                             "formato anterior a 2024."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    for (anio, trimestre), url in sorted(FICHEROS.items()):
        etiqueta = f"{anio}T{trimestre}"
        print(f"Descargando {etiqueta}...", flush=True)
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {etiqueta}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        try:
            registros = _parsear(crudo, etiqueta)
        except Exception as e:
            print(f"  !! {etiqueta}: error al parsear ({type(e).__name__}: {e}), omitido", flush=True)
            continue
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {etiqueta}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
