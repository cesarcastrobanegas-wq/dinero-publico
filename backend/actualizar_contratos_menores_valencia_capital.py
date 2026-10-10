# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Valencia (capital, ~800.000 hab. -- el mayor municipio de los seis sin
agregador regional que se investigan desde el 2026-09-27, ver LIMITACIONES_COBERTURA.md).

Fuente OFICIAL: buscador de contratos menores del propio Ayuntamiento (www.valencia.es/cas/ayuntamiento/
buscador-contratos-menores), un portlet Liferay que expone un formulario (POST) y devuelve una tabla HTML con
TODOS los campos relevantes -- incluido NIF y, a diferencia de Madrid/RPC/Euskadi, un enlace por contrato
(columna "Objeto", <a> a una ficha .jsp con el número de contrato). El portal antiguo (gobiernoabierto.
valencia.es, CKAN) se retiró en la reorganización de junio de 2026; ESTE es el sustituto real, verificado en
vivo el 2026-09-28.

Mecanismo (verificado en vivo):
  1. GET a la página del buscador para obtener una sesión (JSESSIONID) y un token p_auth fresco (Liferay CSRF).
  2. POST a la misma URL con `_javax.portlet.action=buscarContrato` y los campos del formulario, reutilizando
     la MISMA sesión/token para todas las peticiones siguientes (confirmado: el token no es de un solo uso).
  3. La respuesta es la página completa; los resultados están en <table id="tablaContratos"> (ordenados por
     fecha descendente).

Paginación -- el tope real es `maxResultados=500` (no hay parámetro de página/offset):
  - El filtro de fecha (`fechaInicio`/`fechaFin`) es fiable sobre RANGOS pero tiene una rareza real (comprobada
    en vivo): una consulta de UN SOLO DÍA (fechaInicio==fechaFin) puede devolver 0 filas aunque ese día SÍ tenga
    contratos (confirmado: un rango de 2 semanas que incluía ese día sí los traía). Por eso NUNCA se usa el
    "día siguiente" como pivote exacto -- cuando una consulta agota el tope de 500, la siguiente usa como nuevo
    `fechaFin` la fecha más antigua vista **más `SOLAPE_DIAS` días de margen**, y se DEDUPLICA por número de
    expediente (clave real y única del propio portal) en vez de confiar en que el corte de fecha sea exacto.
    Preferible pedir de más y deduplicar a arriesgarse a perder filas por un corte impreciso.
  - "Estado" (ADJUDICADOS/MODIFICADOS/RESUELTOS) es el estado ACTUAL del contrato, no un histórico de fases
    (a diferencia de PSCP) -- cada contrato aparece en uno solo de los tres, así que hay que consultar los TRES
    por separado y juntar el resultado (no se solapan entre sí, solo dentro del mismo estado por el paginado).

Uso (desde backend/):
    python actualizar_contratos_menores_valencia_capital.py                  # barrido completo, 3 estados
    python actualizar_contratos_menores_valencia_capital.py --meses 2        # solo los últimos 2 meses (pruebas rápidas)

Genera contratos_menores_valencia_capital.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_valencia_capital)."""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_valencia_capital.json.gz")

from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py
BUSCADOR_URL = "https://www.valencia.es/cas/ayuntamiento/buscador-contratos-menores"
NS = "_contratos_menores_ContratosMenoresPortlet_INSTANCE_GB76u1gGDWNH_"
SOLAPE_DIAS = 7          # margen de solape al repaginar (ver docstring: el corte de fecha no es exacto)
MAX_RESULTADOS = 500     # tope real del propio buscador, no hay parámetro de página
MAX_ITER_POR_ESTADO = 400  # tope de seguridad (evita bucle infinito si el solape nunca reduce la fecha)

_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _dmy(d):
    return d.strftime("%d/%m/%Y")


def _fecha_iso(dmy):
    """'25/09/2026' -> '2026-09-25'"""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (dmy or "").strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


class SesionValencia:
    """Sesión HTTP con cookies + token p_auth de Liferay, obtenidos una vez y reutilizados en todas las
    peticiones (confirmado en vivo: el token no caduca de un solo uso, sirve para toda la sesión)."""

    def __init__(self):
        self.cookie_jar = {}
        self.p_auth = None
        self._iniciar()

    def _request(self, method, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", _UA)
        if self.cookie_jar:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items()))
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=30) as r:
            for ck in r.headers.get_all("Set-Cookie") or []:
                nombre_valor = ck.split(";", 1)[0]
                if "=" in nombre_valor:
                    k, v = nombre_valor.split("=", 1)
                    self.cookie_jar[k] = v
            return r.read().decode("utf-8", errors="replace")

    def _iniciar(self):
        html = self._request("GET", BUSCADOR_URL)
        i = html.find("formContrato")
        bloque = html[max(0, i - 3000):i + 100]
        m = re.search(r"p_auth=([A-Za-z0-9]+)", bloque)
        if not m:
            raise RuntimeError("No se encontró el token p_auth -- la estructura de la página pudo haber cambiado")
        self.p_auth = m.group(1)

    def buscar(self, fecha_inicio, fecha_fin, estado, max_resultados=MAX_RESULTADOS):
        action = (
            f"{BUSCADOR_URL}?p_p_id=contratos_menores_ContratosMenoresPortlet_INSTANCE_GB76u1gGDWNH"
            f"&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view"
            f"&_contratos_menores_ContratosMenoresPortlet_INSTANCE_GB76u1gGDWNH_javax.portlet.action=buscarContrato"
            f"&p_auth={self.p_auth}"
        )
        campos = {
            f"{NS}objeto": "", f"{NS}numExpediente": "", f"{NS}nifAdjudicatario": "",
            f"{NS}importeMin": "", f"{NS}importeMax": "",
            f"{NS}selectTipo": "todos", f"{NS}selectEstado": estado,
            f"{NS}fechaInicio": _dmy(fecha_inicio), f"{NS}fechaFin": _dmy(fecha_fin),
            f"{NS}maxResultados": str(max_resultados),
            f"{NS}formDate": str(int(time.time() * 1000)),
        }
        boundary = "----dineropublico"
        partes = []
        for k, v in campos.items():
            partes.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
        partes.append(f"--{boundary}--\r\n")
        cuerpo = "".join(partes).encode("utf-8")
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._request("POST", action, data=cuerpo, headers=headers)


def _parsear_filas(html):
    i = html.find('id="tablaContratos"')
    if i < 0:
        return []
    j = html.find("</table>", i)
    bloque = html[i:j]
    filas_html = bloque.split("<tr>")[2:]  # [0] es basura antes de <thead>, [1] es la cabecera
    registros = []
    for fila in filas_html:
        celdas = re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)
        if len(celdas) < 14:
            continue
        objeto_html = celdas[1]
        m_url = re.search(r'numContrato=(\w+)"', objeto_html)
        num_contrato = m_url.group(1) if m_url else ""

        def _texto(html_celda):
            return re.sub(r"<[^>]+>", "", html_celda).replace("&amp;", "&").strip()

        registros.append({
            "objeto": _texto(celdas[0]),
            "tipo": _texto(celdas[2]),
            "fecha": _texto(celdas[3]),
            "importe_sin_iva": _texto(celdas[4]),
            "expediente": _texto(celdas[6]),
            "organo": _texto(celdas[7]),
            "adjudicatari": _texto(celdas[11]),
            "nif": _texto(celdas[12]),
            "estado": _texto(celdas[13]),
            "num_contrato": num_contrato,
        })
    return registros


def _importe(txt):
    """'630,00 €' -> 630.0"""
    limpio = (txt or "").replace("€", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _registro_a_contrato(r):
    """Clave única = N° de contrato (columna oculta en la URL del título), NUNCA el N° de expediente --
    comprobado en vivo (2026-09-28): un mismo expediente agrupa varios contratos DISTINTOS (adjudicatario,
    objeto, importe y fecha diferentes; ver docstring del módulo/LIMITACIONES_COBERTURA.md). Usar el
    expediente como clave se detectó que colapsaba silenciosamente contratos reales entre sí (327 filas
    parseadas -> solo 149 tras deduplicar por expediente en la primera prueba)."""
    fecha = _fecha_iso(r["fecha"])
    clave = r["num_contrato"] or r["expediente"]
    return {
        "id":               f"valencia_capital::{clave}",
        "municipio":         "Valencia",
        "provincia":         "valencia",
        "fuente":            "valencia_capital",
        "organisme":         r["organo"] or "Ayuntamiento de Valencia",
        "adjudicatari":      r["adjudicatari"] or "No localizada",
        "nif":               r["nif"],
        "import_num":        round(_importe(r["importe_sin_iva"]), 2),
        "data_adjudicacio":  fecha,
        "tipus_contracte":   r["tipo"],
        "descripcio":        r["objeto"],
        "codi_cpv":          "",
        "exercici":          fecha[:4] if fecha else "",
        "_estado_origen":    r["estado"],   # solo para depuración/stats, no se guarda en la tabla compartida
    }


def _barrer_estado(sesion, estado, desde, hasta_inicial):
    """Pagina hacia atrás en el tiempo desde `hasta_inicial` hasta `desde`, repitiendo con solape cuando se
    agota el tope de 500 (ver docstring del módulo). Devuelve dict clave->contrato (deduplicado)."""
    encontrados = {}
    hasta = hasta_inicial
    ultima_fecha_min = None
    for iteracion in range(MAX_ITER_POR_ESTADO):
        html = sesion.buscar(desde, hasta, estado)
        filas = _parsear_filas(html)
        for r in filas:
            c = _registro_a_contrato(r)
            if c["data_adjudicacio"]:
                encontrados[c["id"]] = c
        print(f"    [{estado}] {_dmy(desde)} -> {_dmy(hasta)}: {len(filas)} filas "
              f"(acumulado {len(encontrados)})", flush=True)
        if len(filas) < MAX_RESULTADOS:
            break   # no se agotó el tope: ya está todo el rango cubierto
        fechas_iso = sorted(c["data_adjudicacio"] for c in
                             (_registro_a_contrato(r) for r in filas) if c["data_adjudicacio"] if c)
        if not fechas_iso:
            break
        fecha_min = fechas_iso[0]
        if fecha_min == ultima_fecha_min:
            print(f"    [{estado}] !! no hay progreso (fecha mínima repetida, {fecha_min}), se corta aquí "
                  "-- revisar a mano", flush=True)
            break
        ultima_fecha_min = fecha_min
        nueva_hasta = datetime.strptime(fecha_min, "%Y-%m-%d") + timedelta(days=SOLAPE_DIAS)
        if nueva_hasta.date() >= hasta.date():
            nueva_hasta = hasta - timedelta(days=1)
        hasta = nueva_hasta
        if hasta <= desde:
            break
        time.sleep(0.3)
    return encontrados


def _leer_existente():
    if not os.path.exists(FICHERO):
        return {}
    with gzip.open(FICHERO, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return {r["id"]: r for r in d.get("registros", [])}


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    limpios = [{k: v for k, v in r.items() if not k.startswith("_")} for r in existentes.values()]
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Valencia (capital), buscador oficial "
                             "www.valencia.es/cas/ayuntamiento/buscador-contratos-menores. data_adjudicacio = "
                             "columna 'Fecha' real del buscador. Ver "
                             "actualizar_contratos_menores_valencia_capital.py."),
            "registros": limpios,
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    meses = None
    if "--meses" in sys.argv:
        meses = int(sys.argv[sys.argv.index("--meses") + 1])

    sesion = SesionValencia()
    hoy = datetime.now()
    desde = datetime.strptime(MENORES_DESDE_FECHA, "%Y-%m-%d") if meses is None else hoy - timedelta(days=meses * 31)

    existentes = _leer_existente()
    total_estado = {}
    for estado in ("ADJUDICADOS", "MODIFICADOS", "RESUELTOS"):
        print(f"=== Estado: {estado} ===", flush=True)
        encontrados = _barrer_estado(sesion, estado, desde, hoy)
        existentes.update(encontrados)
        total_estado[estado] = len(encontrados)
        _guardar(existentes)   # progreso a salvo tras cada estado

    # Alcance de 5 años (por si el solape trajo algo de antes del corte)
    antes = len(existentes)
    existentes = {k: v for k, v in existentes.items() if v["data_adjudicacio"] >= MENORES_DESDE_FECHA}
    if len(existentes) != antes:
        print(f"Descartados por fecha < {MENORES_DESDE_FECHA}: {antes - len(existentes)}", flush=True)
    _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}. Por estado (con solape, antes de deduplicar "
          f"entre estados -- no debería solaparse): {total_estado}")


if __name__ == "__main__":
    main()
