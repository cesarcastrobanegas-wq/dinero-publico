# encoding: utf-8
"""
Resuelve, para cada municipio de Murcia y Girona, su identificador interno
(idEntidad) en la Plataforma de Rendición de Cuentas de las Corporaciones
Locales (rendiciondecuentas.es, Tribunal de Cuentas) y el último ejercicio
con la Cuenta General rendida, y genera backend/cuentas_anuales.json.

Con (idEntidad, último ejercicio rendido) se puede enlazar DIRECTO a la
ficha de esa Cuenta General concreta:
  https://www.rendiciondecuentas.es/es/consultadeentidadesycuentas/
      buscarCuentas/consultarCuenta.html?idEntidad=<id>&ejercicio=<año>
-- verificado a mano el 2026-08-02 que esa URL funciona "en frío" (sin
sesión/Referer previos, GET directo). Sin este script, el enlace de la
ficha cae al buscador genérico por nombre (ver rendicion_cuentas_url() en
app.py), que sigue funcionando pero es un paso menos directo.

No hay API: hay que pasar por el formulario de búsqueda del portal
(GET con denominación de texto libre) y parsear el HTML resultante -- ver
notas de _buscar_id_entidad() sobre por qué la búsqueda por el nombre
completo falla en un tercio largo de los municipios de Girona (apóstrofes
catalanes en mitad de la cadena) y qué alternativa se usa en ese caso.

El resultado NO incluye el importe de superávit/déficit: esa cifra vive
detrás de un visualizador Java (VisualizadorPortalCiudadano) que carga los
datos por AJAX tras una cadena de sesión de varios pasos -- confirmado que
architectónicamente no es un enlace estable para un usuario final, y
reproducirlo de servidor a servidor añadiría una dependencia de sesión
frágil al cron diario. Queda fuera de alcance (decisión 2026-08-02).

Uso:  python actualizar_cuentas_anuales.py
(Solo usa 'requests', ya en requirements.txt -- a diferencia de los otros
scripts de este directorio, no hace falta openpyxl.)
"""
import json
import re
import sys
import time

import requests
import requests.sessions

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import (BASE_DIR, MUNICIPIOS_MURCIA, MUNICIPIOS_GIRONA, normalizar,
                  RENDICION_CUENTAS_IDS)

# rendiciondecuentas.es declara charset=ISO-8859-1 y, cuando la denominación
# buscada lleva alguna vocal acentuada (Abarán, Águilas, Anglès...), el
# header Location del 302 llega con esa letra en bytes Latin-1 sin
# porcentaje-codificar. `requests.sessions.get_redirect_target()` asume
# siempre UTF-8 al decodificarlo (to_native_string(location, "utf8")) y
# revienta con UnicodeDecodeError incluso con allow_redirects=False --
# `Session.send()` prepara igualmente el primer salto de redirección por
# adelantado (verificado a mano el 2026-08-02 con "Abarán"/"Águilas").
# Parche mínimo y acotado a este script: reintenta como Latin-1 solo si la
# decodificación UTF-8 falla, sin tocar el comportamiento normal para el
# resto de webs que si mandan Location en UTF-8.
_to_native_string_original = requests.sessions.to_native_string


def _to_native_string_con_fallback_latin1(string, encoding="ascii"):
    try:
        return _to_native_string_original(string, encoding)
    except UnicodeDecodeError:
        return _to_native_string_original(string, "latin-1")


requests.sessions.to_native_string = _to_native_string_con_fallback_latin1

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
BASE_URL = "https://www.rendiciondecuentas.es/es/consultadeentidadesycuentas"
OUT_FILE = f"{BASE_DIR}/cuentas_anuales.json"

# Pausa entre peticiones -- portal público del Tribunal de Cuentas, sin
# límite de tasa documentado; este valor es un gesto de cortesía, no una
# medida anti-bloqueo (no hemos visto ningún 429/403 en las pruebas).
PAUSA_SEG = 0.8
REINTENTOS = 3

CONECTORES = {"la", "el", "els", "les", "los", "las", "l", "de", "d", "i", "en", "del", "dels", "y"}


def _limpiar_sufijo_ine(municipio):
    """'Jonquera, la' -> 'Jonquera' -- el sufijo de artículo al estilo INE
    no forma parte del nombre real y rompe la búsqueda por texto libre."""
    return re.sub(r",\s*(la|el|els|les|los|las|l')\s*$", "", municipio, flags=re.I).strip()


def _termino_fallback(municipio):
    """Cuando ni el nombre completo ni el nombre sin sufijo INE encuentran
    resultados (típicamente municipios catalanes con apóstrofe en medio del
    nombre, ej. "Canet d'Adri", "Bisbal d'Empordà" -- verificado a mano el
    2026-08-02 que el buscador da 0 resultados en cuanto la cadena
    contiene un apóstrofe, sea cual sea su codificación), se prueba con la
    palabra más larga del nombre que no sea un conector/artículo. No
    siempre es unívoco (p.ej. "Empordà" solo, o "Vall" solo, dan varios
    municipios a la vez) -- se descarta más abajo si el resultado no es
    exactamente 1."""
    limpio = _limpiar_sufijo_ine(municipio)
    limpio = re.sub(r"['\-]", " ", limpio)
    palabras = [w for w in limpio.split() if normalizar(w) not in CONECTORES and len(w) > 2]
    if not palabras:
        return limpio
    return max(palabras, key=len)


def _get_con_reintentos(session, url, params=None, referer=None):
    headers = {"Referer": referer} if referer else {}
    for intento in range(REINTENTOS):
        try:
            r = session.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if intento == REINTENTOS - 1:
                raise
            time.sleep(2 * (intento + 1))


_RE_FILA_RESULTADO = re.compile(
    r'idEntidad" value="(\d+)"[^<]*/>\s*</td>\s*<td>Ayuntamiento</td>\s*<td>\s*([^<]+?)\s*</td>')


def _buscar_id_entidad(session, municipio, provincia_ids):
    """Devuelve (idEntidad, url_busqueda_usada, params_busqueda) o
    (None, None, None) si no se encontró un único resultado inequívoco.
    Prueba, en orden: nombre completo -> nombre sin sufijo INE -> palabra
    más distintiva.

    La búsqueda es por SUBCADENA, no por palabra exacta -- "Murcia" como
    término encuentra 3 ayuntamientos ("Murcia", "Alhama de Murcia",
    "Fuente Álamo de Murcia"), verificado a mano el 2026-08-02. Cuando hay
    más de un resultado, antes de descartarlo se mira si exactamente uno
    de ellos tiene la denominación mostrada IGUAL (normalizada) al
    municipio buscado -- así "Murcia" desambigua sola sin necesitar un
    término de búsqueda distinto."""
    candidatos = []
    for candidato in (municipio, _limpiar_sufijo_ine(municipio), _termino_fallback(municipio)):
        if candidato not in candidatos:
            candidatos.append(candidato)

    objetivo = normalizar(_limpiar_sufijo_ine(municipio))
    for termino in candidatos:
        params = {
            "idComunidadAutonoma": provincia_ids["idComunidadAutonoma"],
            "idProvincia": provincia_ids["idProvincia"],
            "idTipoEntidad": "A",
            "denominacion": termino,
            "submitFormBusquedaEntidades": "Buscar",
        }
        r = _get_con_reintentos(session, f"{BASE_URL}/buscarEntidades/index.html", params=params)
        filas = _RE_FILA_RESULTADO.findall(r.text)
        if len(filas) == 1:
            return filas[0][0], r.url, params
        if len(filas) > 1:
            exactas = [id_ for id_, denom in filas if normalizar(denom) == objetivo]
            if len(exactas) == 1:
                return exactas[0], r.url, params
        time.sleep(PAUSA_SEG)
    return None, None, None


def _ultimo_ejercicio_rendido(session, id_entidad, url_busqueda, params_busqueda):
    """A partir de la página de resultados de la búsqueda, sigue a
    'Información de Cuentas Remitidas' y se queda con el ejercicio más alto
    que tenga un enlace 'consultarCuenta.html' -- las celdas sin cuenta
    rendida no llevan enlace, solo un <img>, así que basta con mirar qué
    ejercicios SÍ son enlaces.

    IMPORTANTE: hay que reenviar los mismos idComunidadAutonoma/idProvincia/
    idTipoEntidad/denominacion de la búsqueda que encontró id_entidad --
    verificado a mano el 2026-08-02 que sin ellos el servidor no puede
    reconstruir su propia redirección interna (construye la URL con esos
    campos literalmente a "null" y la página siguiente da 500)."""
    params = {
        **params_busqueda,
        "idEntidad": id_entidad,
        "option": "Información de Cuentas Remitidas",
        "selectedLocale": "es",
    }
    params.pop("submitFormBusquedaEntidades", None)
    r = _get_con_reintentos(session, f"{BASE_URL}/buscarEntidades/consultarEntidad.html",
                             params=params, referer=url_busqueda)
    ejercicios = [int(e) for _id, e in
                  re.findall(r'consultarCuenta\.html\?idEntidad=(\d+)&amp;ejercicio=(\d+)', r.text)
                  if _id == str(id_entidad)]
    if not ejercicios:
        return None
    return max(ejercicios)


def main():
    resultado = {}
    sin_match = []
    sin_ejercicio = []

    tareas = ([(m, "murcia") for m in MUNICIPIOS_MURCIA] +
              [(m, "girona") for m in MUNICIPIOS_GIRONA])

    for i, (municipio, provincia) in enumerate(tareas, 1):
        provincia_ids = RENDICION_CUENTAS_IDS[provincia]
        # Sesión nueva por municipio -- gesto de aislamiento razonable entre
        # peticiones a un servicio público de terceros, sin coste real (el
        # portal no exige mantener sesión entre búsquedas distintas).
        session = requests.Session()
        session.headers.update(HEADERS)
        try:
            id_entidad, url_busqueda, params_busqueda = _buscar_id_entidad(session, municipio, provincia_ids)
            if not id_entidad:
                sin_match.append((provincia, municipio))
                continue
            time.sleep(PAUSA_SEG)
            ejercicio = _ultimo_ejercicio_rendido(session, id_entidad, url_busqueda, params_busqueda)
            if not ejercicio:
                sin_ejercicio.append((provincia, municipio))
                continue
            resultado[normalizar(municipio)] = {
                "municipio": municipio,
                "provincia": provincia,
                "id_entidad": int(id_entidad),
                "ultimo_ejercicio_rendido": ejercicio,
            }
        except requests.RequestException as e:
            print(f"[aviso] {municipio} ({provincia}): fallo de red, se salta -- {e}")
            sin_match.append((provincia, municipio))

        if i % 20 == 0:
            print(f"...{i}/{len(tareas)} procesados ({len(resultado)} con idEntidad+ejercicio)")
        time.sleep(PAUSA_SEG)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "municipios": resultado},
                   f, ensure_ascii=False, indent=1)

    print(f"\nMunicipios con idEntidad + ejercicio rendido: {len(resultado)} / {len(tareas)}")
    if sin_match:
        print(f"\nSin idEntidad encontrado ({len(sin_match)}): {sin_match}")
    if sin_ejercicio:
        print(f"\nCon idEntidad pero sin ningún ejercicio rendido ({len(sin_ejercicio)}): {sin_ejercicio}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
