# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Madrid (capital, ~3,3 M de habitantes -- el mayor municipio de España, y con
diferencia el hallazgo más importante de la ronda de investigación de menores del 2026-09-27: Madrid, Castilla y
León, Comunitat Valenciana, Aragón, Illes Balears y Castilla-La Mancha NO tienen agregador regional -- ver
LIMITACIONES_COBERTURA.md -- así que toca ayuntamiento a ayuntamiento, y este es, de largo, el ayuntamiento más
grande de los seis).

Fuente OFICIAL: portal de datos abiertos del propio Ayuntamiento de Madrid (datos.madrid.es), dataset
"Contratos menores" (id 300253, "Actividad contractual"), gestionado por la Dirección General de Contratación y
Servicios. NO es un agregador ni prensa -- es la fuente primaria municipal, publicada en CSV/XLSX, actualización
mensual, cobertura desde enero de 2015. Verificado en vivo (2026-09-27): delimitador ';', codificación UTF-8 con
BOM, comillas correctas alrededor de campos con salto de línea (varios licitadores en INVITADOS A PRESENTAR
OFERTA).

Un fichero CSV por año (2021 aparece partido en dos periodos por un cambio de estructura en marzo de 2021; solo
hace falta el segundo, "desde marzo", porque el alcance de 5 años empieza en septiembre de 2021). Los ids de
recurso de cada año se han visto en el propio portal y pueden cambiar si el Ayuntamiento reestructura el dataset
-- si algún año deja de descargarse, revisar a mano en
https://datos.madrid.es/dataset/300253-0-contratos-actividad-menores/downloads

Campos reales del CSV (cabecera verificada en vivo): N. DE REGISTRO DE CONTRATO; N. DE EXPEDIENTE;
CENTRO - SECCION; ORGANO DE CONTRATACION; OBJETO DEL CONTRATO; TIPO DE CONTRATO; N. DE INVITACIONES CURSADAS;
INVITADOS A PRESENTAR OFERTA; IMPORTE LICITACION IVA INC.; N. LICITADORES PARTICIPANTES; NIF ADJUDICATARIO;
RAZON SOCIAL ADJUDICATARIO; PYME; IMPORTE ADJUDICACION IVA INC.; FECHA DE ADJUDICACION; PLAZO;
FECHA DE INSCRIPCION; ORGANISMO_CONTRATANTE; ORGANISMO_PROMOTOR. Sin CPV y sin URL por expediente (mismo límite
que RPC Cataluña); SÍ trae NIF (a diferencia de RPC). Importe CON IVA. Fecha de adjudicación REAL (no de
inscripción), formato DD/MM/AA -- se usa tal cual para el filtro de 5 años.

Uso (desde backend/):
    python actualizar_contratos_menores_madrid_capital.py

Genera contratos_menores_madrid_capital.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_madrid_capital) y vuelca a la tabla compartida contratos_menors_locales. Incremental:
si el fichero ya existe, un registro con el mismo id se sustituye por la versión más reciente de esta ejecución
(no borra registros de años que no se vuelvan a pedir en una relanzada parcial -- aunque normalmente se piden
todos los años de golpe)."""
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_madrid_capital.json.gz")

from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

# (año representativo -> resource id del CSV en datos.madrid.es, dataset 300253). "2021" es ya solo el periodo
# "desde marzo" (el único que puede tener filas >= MENORES_DESDE_FECHA).
RECURSOS = {
    "2021": 8,
    "2022": 23,
    "2023": 4,
    "2024": 2,
    "2025": 27,
    "2026": 26,
}
URL_TPL = ("https://datos.madrid.es/dataset/300253-0-contratos-actividad-menores/resource/"
           "300253-{id}-contratos-actividad-menores-csv/download/300253-{id}-contratos-actividad-menores-csv.csv")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"}


def _descargar(anio, resource_id):
    """Descarga y decodifica -- NO todos los años usan la misma codificación (comprobado en vivo, 2026-09-27):
    2022 y 2026 vienen en UTF-8 con BOM, pero 2021/2023/2024/2025 vienen en cp1252/latin-1 (el propio portal
    mezcla generaciones del fichero). Se prueba UTF-8 primero (falla rápido y limpio si no lo es) y se cae a
    cp1252 -- decodifica CUALQUIER byte sin error, así que solo se usa como último recurso."""
    url = URL_TPL.format(id=resource_id)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        crudo = r.read()
    try:
        return crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return crudo.decode("cp1252")


def _fecha_iso(dmy):
    """'23/12/25' -> '2025-12-23' o '28/12/2023' -> '2023-12-28' -- el propio portal mezcla año de 2 y de 4
    dígitos según el fichero (comprobado en vivo, 2026-09-27: el CSV de 2026 usa 2 dígitos, el de 2024 usa 4).
    Con 2 dígitos, asumir 20xx es seguro (todo el dataset cubre 2015-2026, sin ambigüedad de siglo posible)."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2}|\d{4})$", (dmy or "").strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    if len(y) == 2:
        y = f"20{y}"
    return f"{y}-{mo}-{d}"


def _importe(txt):
    """'15.808,00€' -> 15808.0"""
    if not txt:
        return 0.0
    limpio = txt.replace("€", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _fila_a_registro(fila, anio):
    fecha = _fecha_iso(fila.get("FECHA DE ADJUDICACION", ""))
    registro = (fila.get("N. DE REGISTRO DE CONTRATO") or fila.get("N. DE EXPEDIENTE") or "").strip()
    return {
        "id":               f"madrid_capital::{registro}",
        "municipio":         "Madrid",
        "provincia":         "madrid",
        "fuente":            "madrid_capital",
        "organisme":         (fila.get("ORGANISMO_CONTRATANTE") or fila.get("ORGANO DE CONTRATACION") or "").strip()
                             or "Ayuntamiento de Madrid",
        "adjudicatari":      (fila.get("RAZON SOCIAL ADJUDICATARIO") or "").strip() or "No localizada",
        "nif":               (fila.get("NIF ADJUDICATARIO") or "").strip(),
        "import_num":        round(_importe(fila.get("IMPORTE ADJUDICACION IVA INC.", "")), 2),
        "data_adjudicacio":  fecha,
        "tipus_contracte":   (fila.get("TIPO DE CONTRATO") or "").strip(),
        "descripcio":        (fila.get("OBJETO DEL CONTRATO") or "").strip(),
        "codi_cpv":          "",
        "exercici":          fecha[:4] if fecha else anio,
    }


def _leer_existente():
    if not os.path.exists(FICHERO):
        return {}
    with gzip.open(FICHERO, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return {r["id"]: r for r in d.get("registros", [])}


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Madrid (capital), dataset oficial 300253 de "
                            "datos.madrid.es (\"Contratos menores\", Dirección General de Contratación y "
                            "Servicios). data_adjudicacio = FECHA DE ADJUDICACION real del CSV. Ver "
                            "actualizar_contratos_menores_madrid_capital.py y "
                            "_cargar_contratos_menores_madrid_capital en app.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = _leer_existente()
    total_nuevos = 0
    total_descartados = 0
    por_anio = {}

    for anio, resource_id in RECURSOS.items():
        print(f"Descargando {anio} (resource {resource_id})...", flush=True)
        try:
            texto = _descargar(anio, resource_id)
        except Exception as e:
            print(f"  !! {anio}: error de descarga ({type(e).__name__}: {e}), se omite este año", flush=True)
            continue
        # Al menos un año (2023, comprobado en vivo 2026-09-27) trae una fila de título antes de la cabecera real
        # ("CONTRATOS MENORES A 31 DE DICIEMBRE DE 2023;;;;...") -- se descarta cualquier línea inicial que no
        # sea ya la cabecera real, en vez de asumir que la primera línea siempre lo es.
        lineas = texto.splitlines()
        while lineas and not lineas[0].startswith("N. DE REGISTRO DE CONTRATO"):
            lineas.pop(0)
        lector = csv.DictReader(io.StringIO("\n".join(lineas)), delimiter=";")
        n_anio, n_descartados_anio = 0, 0
        for fila in lector:
            reg = _fila_a_registro(fila, anio)
            if not reg["data_adjudicacio"] or reg["data_adjudicacio"] < MENORES_DESDE_FECHA:
                n_descartados_anio += 1
                continue
            existentes[reg["id"]] = reg
            n_anio += 1
        total_nuevos += n_anio
        total_descartados += n_descartados_anio
        por_anio[anio] = n_anio
        print(f"  {anio}: {n_anio} contratos en ventana ({n_descartados_anio} descartados por fecha)", flush=True)
        _guardar(existentes)   # progreso a salvo tras cada año

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_nuevos} nuevos/actualizados esta ejecución, "
          f"{total_descartados} descartados por fecha < {MENORES_DESDE_FECHA}).")
    print(f"Por año (esta ejecución): {por_anio}")


if __name__ == "__main__":
    main()
