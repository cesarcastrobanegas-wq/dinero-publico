# encoding: utf-8
"""
Resuelve, para cada municipio de CUALQUIER provincia que
MUNICIPIOS_POR_PROVINCIA (app.py) cubra, su identificador interno
(idEntidad) en la Plataforma de Rendición de Cuentas de las Corporaciones
Locales (rendiciondecuentas.es, Tribunal de Cuentas) y el último ejercicio
con la Cuenta General rendida, y genera backend/cuentas_anuales.json.

GENERALIZADO 2026-09-21 (Índice de Transparencia nacional, petición de
César, punto 2 de 3 -- ver actualizar_retribuciones.py para el punto 1,
mismo encargo): antes iteraba una lista hardcodeada de solo 5 provincias
(MUNICIPIOS_MURCIA + ...GIRONA + ...LLEIDA + ...BARCELONA + ...TARRAGONA).
Ahora itera MUNICIPIOS_POR_PROVINCIA completo, mismo patrón que
actualizar_deuda_y_liquidaciones.py -- cualquier provincia nueva se recoge
sola, SALVO las 4 que RENDICION_CUENTAS_IDS (app.py) deja fuera a
propósito porque esta fuente concreta no las cubre (ver su comentario
ampliado el mismo día para el detalle completo verificado en vivo):
País Vasco y Navarra (Tribunal de Cuentas foral propio, ni siquiera
aparecen como Comunidad Autónoma en el desplegable de búsqueda) y
Ceuta/Melilla (no aparecen como provincia en el formulario). Este
script salta esas 4 explícitamente en vez de dejar que fallen calladas
contra RENDICION_CUENTAS_IDS.get() -> None -> KeyError.

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
from app import (BASE_DIR, MUNICIPIOS_POR_PROVINCIA, PROVINCIA_LABEL, normalizar,
                  RENDICION_CUENTAS_IDS)
from actualizar_alcaldes import _formas_nucleo_articulo

# Provincias que RENDICION_CUENTAS_IDS (app.py) deja fuera a propósito --
# ver el comentario ampliado ahí el 2026-09-21 para el detalle verificado
# en vivo (Tribunal de Cuentas foral propio para pais_vasco/navarra,
# ausentes del formulario para ceuta/melilla).
_PROVINCIAS_SIN_COBERTURA = {"pais_vasco", "navarra", "ceuta", "melilla"}

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

# Alias puntuales para casos que ninguna transformación genérica resuelve --
# verificados a mano el 2026-09-22 al auditar los 82 "sin idEntidad" tras
# generalizar a toda España (ver informe de esa fecha):
#   - Torla-Ordesa (Huesca): fusión reciente de dos entidades; el portal
#     sigue teniendo registrada solo la entidad antigua "Torla".
#   - Jarque de Moncayo (Zaragoza): _termino_fallback() elige "Moncayo" (más
#     larga que "Jarque") por ser la palabra más larga no conectora, pero el
#     portal solo tiene registrado el nombre corto "Jarque" -- "Moncayo" es
#     la comarca/sierra, no forma parte del nombre real del municipio.
ALIAS_BUSQUEDA = {
    "Torla-Ordesa": "Torla",
    "Jarque de Moncayo": "Jarque",
}

# à/è/ò (vocales catalanas) <-> á/é/ó (vocales castellanas): el propio
# nomenclátor de esta app usa la ortografía valenciana/catalana correcta
# para municipios de Comunitat Valenciana (p.ej. "Benigànim", "Beniardà"),
# pero rendiciondecuentas.es no siempre la respeta y a veces tiene el
# nombre con tilde "castellanizada" -- verificado a mano el 2026-09-22
# ("Beniardà" -> el portal solo tiene "Beniardá"; "Benigànim" -> solo
# "Benigánim"). También pasa al revés (ver "Énova, l'" -> el portal SÍ
# respeta "Ènova" con accent obert ahí). Se prueban ambas direcciones como
# candidato adicional, nunca como único intento.
_ACENTO_CATALAN_A_CASTELLANO = str.maketrans("àèòÀÈÒ", "áéóÁÉÓ")
_ACENTO_CASTELLANO_A_CATALAN = str.maketrans("áéóÁÉÓ", "àèòÀÈÒ")


def _variantes_acento(termino):
    v1 = termino.translate(_ACENTO_CATALAN_A_CASTELLANO)
    v2 = termino.translate(_ACENTO_CASTELLANO_A_CATALAN)
    return {t for t in (v1, v2) if t != termino}


def _buscar_id_entidad(session, municipio, provincia_ids):
    """Devuelve (idEntidad, url_busqueda_usada, params_busqueda) o
    (None, None, None) si no se encontró un único resultado inequívoco.

    La búsqueda es por SUBCADENA, no por palabra exacta -- "Murcia" como
    término encuentra 3 ayuntamientos ("Murcia", "Alhama de Murcia",
    "Fuente Álamo de Murcia"), verificado a mano el 2026-08-02. Cuando hay
    más de un resultado, antes de descartarlo se mira si alguno tiene la
    denominación mostrada IGUAL (normalizada) al municipio buscado -- así
    "Murcia" desambigua sola sin necesitar un término de búsqueda distinto.

    AMPLIADO 2026-09-22 al auditar en vivo los 82 "sin idEntidad" que dejó
    la generalización a toda España (informe de esa fecha) -- además del
    nombre completo, el nombre sin sufijo INE y la palabra más distintiva
    (candidatos "originales", ya validados en producción desde hace meses),
    se prueban ahora también, como candidatos EXTRA de menor confianza:
      - la forma con el artículo reconstruido como prefijo (_formas_
        nucleo_articulo, ya usada en actualizar_alcaldes.py /
        actualizar_deuda_y_liquidaciones.py para "Núcleo, Artículo" ->
        "Artículo Núcleo") -- resuelve p.ej. "Adrada, La" -> "la Adrada".
      - la forma sin el artículo gallego "O "/"A " inicial -- resuelve
        p.ej. "A Illa de Arousa" -> "Illa de Arousa".
      - variantes con guion <-> espacio en ambas direcciones -- resuelve
        p.ej. "Oza-Cesuras" -> "Oza Cesuras" (el portal usa espacio) y
        "Zarza Capilla" -> "Zarza-Capilla" (el portal usa guion, al revés).
      - variantes de acento catalán/castellano en ambas direcciones (ver
        _variantes_acento).
    Para los candidatos EXTRA, a diferencia de los originales, NUNCA se
    acepta un resultado único sin más (ver hallazgo real 2026-09-22:
    "del Cañavate" -- contracción de "el Cañavate" -- da un único
    resultado, pero es el de OTRO municipio, "Atalaya del Cañavate"): solo
    cuentan si hay una coincidencia EXACTA (normalizada) con el nombre
    buscado, entre las formas del artículo reconstruido o la bare
    (_limpiar_sufijo_ine), nunca por ser "el único resultado"."""
    if municipio in ALIAS_BUSQUEDA:
        candidatos_originales = [ALIAS_BUSQUEDA[municipio]]
    else:
        candidatos_originales = []
        for candidato in (municipio, _limpiar_sufijo_ine(municipio), _termino_fallback(municipio)):
            if candidato not in candidatos_originales:
                candidatos_originales.append(candidato)

    formas_articulo = _formas_nucleo_articulo(municipio)
    base_limpio = _limpiar_sufijo_ine(municipio)

    # candidatos_extra: cada transformación se genera A PARTIR de
    # (municipio, base_limpio) -- NUNCA solo de otras transformaciones ya
    # generadas, para que el swap de acento se aplique también al nombre
    # base y no dependa de que antes haya disparado alguna otra
    # transformación (bug real detectado 2026-09-22: "Beniardà" no tiene
    # sufijo INE ni guion/espacio que reordenar, así que sin esto el swap
    # de acento nunca llegaba a probarse).
    candidatos_extra = list(formas_articulo)
    for pref in ("O ", "A "):
        if municipio.startswith(pref):
            sin_articulo = municipio[len(pref):]
            candidatos_extra.append(sin_articulo)
            # El portal también puede tener el propio artículo gallego en
            # formato "Núcleo, Artículo" (hallazgo real 2026-09-22:
            # buscar "Illa de Arousa" devuelve la denominación "Illa de
            # Arousa, A", no "Illa de Arousa" a secas) -- _limpiar_sufijo_ine
            # no reconoce "a"/"o" sueltos como artículo (a propósito, sería
            # demasiado agresivo en general), así que se añade aquí a mano,
            # acotado a este caso concreto.
            candidatos_extra.append(f"{sin_articulo}, {pref.strip()}")
    if "-" in base_limpio:
        candidatos_extra.append(base_limpio.replace("-", " "))
    if " " in base_limpio:
        candidatos_extra.append(base_limpio.replace(" ", "-"))
    # _formas_nucleo_articulo contrae "l'" sin espacio ("l'Énova"), pero
    # rendiciondecuentas.es a veces lo separa con espacio tras el apóstrofe
    # ("L' Ènova", hallazgo real 2026-09-22) -- variante local, no se toca
    # _formas_nucleo_articulo porque otros scripts ya dependen de su
    # convención sin espacio (que sí es la correcta contra SUS fuentes).
    # Se añade ANTES del bucle de acentos para que también le llegue el
    # swap de acento (l'Énova -> l' Énova -> l' Ènova).
    candidatos_extra.extend(f.replace("l'", "l' ", 1) for f in formas_articulo if f.startswith("l'"))
    for base in (municipio, base_limpio, *candidatos_extra):
        candidatos_extra.extend(_variantes_acento(base))

    # objetivos: normalizar() ya iguala á/à, é/è, ó/ò (ver su tabla de
    # sustituciones), así que NO hace falta añadir aparte las variantes de
    # acento aquí -- pero SÍ hace falta añadir cada candidato EXTRA
    # (reconstruido/gallego/guion) como objetivo también, porque el propio
    # portal a veces devuelve ESE mismo candidato en formato "Núcleo,
    # Artículo" (hallazgo real 2026-09-22: buscar "Illa de Arousa" da
    # como denominación "Illa de Arousa, A", no "Illa de Arousa" a secas)
    # -- por eso la comparación de más abajo también prueba
    # normalizar(_limpiar_sufijo_ine(denominación_portal)).
    objetivos = {normalizar(base_limpio)}
    objetivos.update(normalizar(f) for f in formas_articulo)
    objetivos.update(normalizar(c) for c in candidatos_extra)

    candidatos_extra = [c for c in candidatos_extra if c not in candidatos_originales]
    # dedup preservando orden
    vistos = set()
    candidatos_extra = [c for c in candidatos_extra if not (c in vistos or vistos.add(c))]

    def _intentar(termino, exacto_obligatorio):
        params = {
            "idComunidadAutonoma": provincia_ids["idComunidadAutonoma"],
            "idProvincia": provincia_ids["idProvincia"],
            "idTipoEntidad": "A",
            "denominacion": termino,
            "submitFormBusquedaEntidades": "Buscar",
        }
        r = _get_con_reintentos(session, f"{BASE_URL}/buscarEntidades/index.html", params=params)
        filas = _RE_FILA_RESULTADO.findall(r.text)
        if filas:
            exactas = [id_ for id_, denom in filas
                       if normalizar(denom) in objetivos
                       or normalizar(_limpiar_sufijo_ine(denom)) in objetivos]
            if len(exactas) == 1:
                return exactas[0], r.url, params
        if not exacto_obligatorio and len(filas) == 1:
            return filas[0][0], r.url, params
        return None

    for termino in candidatos_originales:
        resultado = _intentar(termino, exacto_obligatorio=False)
        if resultado:
            return resultado
        time.sleep(PAUSA_SEG)
    for termino in candidatos_extra:
        resultado = _intentar(termino, exacto_obligatorio=True)
        if resultado:
            return resultado
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


def _guardar(resultado):
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "municipios": resultado},
                   f, ensure_ascii=False, indent=1)


def main():
    # Reanudable: con ~8.000 municipios y ~1.6s por municipio (2 peticiones
    # x PAUSA_SEG) la ejecución completa puede tardar varias horas -- si ya
    # hay un cuentas_anuales.json de una ejecución anterior (parcial o
    # completa), se parte de ahí y se saltan los municipios que ya tengan
    # idEntidad+ejercicio, en vez de volver a pedirlos todos desde cero.
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            resultado = json.load(f).get("municipios", {})
    except (FileNotFoundError, json.JSONDecodeError):
        resultado = {}
    if resultado:
        print(f"Reanudando: {len(resultado)} municipios ya en {OUT_FILE}, se saltan.")

    sin_match = []
    sin_ejercicio = []

    tareas = [(m, clave) for clave, municipios in MUNICIPIOS_POR_PROVINCIA.items()
              if clave not in _PROVINCIAS_SIN_COBERTURA
              for m in municipios]
    print(f"{len(tareas)} municipios a procesar en {len(MUNICIPIOS_POR_PROVINCIA) - len(_PROVINCIAS_SIN_COBERTURA)} "
          f"provincias (excluidas sin cobertura en esta fuente: {sorted(_PROVINCIAS_SIN_COBERTURA)}).")

    CHECKPOINT_CADA = 50  # guarda progreso cada N municipios NUEVOS procesados

    procesados_esta_ejecucion = 0
    for i, (municipio, provincia) in enumerate(tareas, 1):
        if normalizar(municipio) in resultado:
            continue
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

        procesados_esta_ejecucion += 1
        if procesados_esta_ejecucion % 20 == 0:
            print(f"...{i}/{len(tareas)} procesados ({len(resultado)} con idEntidad+ejercicio)")
        if procesados_esta_ejecucion % CHECKPOINT_CADA == 0:
            _guardar(resultado)
        time.sleep(PAUSA_SEG)

    _guardar(resultado)

    print(f"\nMunicipios con idEntidad + ejercicio rendido: {len(resultado)} / {len(tareas)}")
    if sin_match:
        print(f"\nSin idEntidad encontrado ({len(sin_match)}): {sin_match}")
    if sin_ejercicio:
        print(f"\nCon idEntidad pero sin ningún ejercicio rendido ({len(sin_ejercicio)}): {sin_ejercicio}")

    print()
    for clave, municipios in MUNICIPIOS_POR_PROVINCIA.items():
        if clave in _PROVINCIAS_SIN_COBERTURA:
            continue
        esperados = len(municipios)
        n_prov = sum(1 for v in resultado.values() if v["provincia"] == clave)
        print(f"{PROVINCIA_LABEL.get(clave, clave)}: {n_prov}/{esperados}")

    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
