# encoding: utf-8
"""
Indicadores para revisar en contratos menores (cola de revisión interna de César, ver INFORME_BOT_CASOS.md).

NADA de lo que sale de aquí se publica: es una lista de candidatos para que una persona los mire. Por eso el lenguaje
es neutro ("indicador", "posible fraccionamiento a revisar") y cada candidato lleva los contratos que lo disparan, su
fuente y los avisos de calidad del dato.

Marco legal (comprobado el 05-10-2026): contrato menor si el valor estimado SIN IVA es inferior a 40.000 € (obras) o
15.000 € (servicios y suministros), art. 118.1 LCSP, sin cambios desde 2018. Desde el RDL 3/2020 sumar varios menores
al mismo contratista NO es ilegal por sí mismo: lo prohibido es partir el objeto para eludir el umbral (arts. 99.2 y
118.2). Por eso la regla 1 no mira solo sumas, sino indicios de un mismo objeto partido.

Regla 1, "posible fraccionamiento" (versión estricta aprobada por César el 05-10): mismo organismo, misma empresa y
mismo tipo; al menos 2 menores en 30 días, cada uno por encima del 40 % del umbral, cuyas descripciones comparten
alguna palabra significativa, y cuya suma supera el umbral. Puntuación 0-100 para ordenar la cola (ver puntuar()).

Ajustes de César (05-10, tras ver 40 ejemplos): espectáculos y fiestas (artistas distintos, que pueden justificarse por
exclusividad) se quedan, con la puntuación rebajada y la categoría "espectaculos" para revisarlos aparte; obras y
servicios de emergencia (DANA, incendios, temporales: art. 120 LCSP) se quedan con aviso y puntuación rebajada; los
lotes del mismo día con objetos parecidos pero distintos (calles, edificios) se quedan como están.

Regla 2, "menor por encima del umbral": un contrato de la lista de menores cuyo importe supera el umbral de su tipo
INCLUSO descontando un 21 % de IVA (importe >= 1,21 x umbral), para no confundir la base del IVA con una irregularidad
(aprobado por César el 05-10). También puede ser un error de la fuente o un contrato mal clasificado como menor.

Limpieza de la cola (encargo de César del 12-10, tras ver que la encabezaban errores de datos):
  - Regla 2: un "menor" de más de 3 veces el umbral se marca como probable error de clasificación (casi siempre es
    un contrato de otro procedimiento publicado en la lista de menores) y pierde puntos; sigue en la cola, al final.
  - Regla 2: los contratos de emergencia ya no cuentan. La tramitación de emergencia (art. 120 LCSP) no tiene el
    límite de importe del contrato menor. La regla 1 no cambia: ahí siguen con su aviso.
  - Las dos reglas: si el "adjudicatario" parece el objeto del contrato y no una empresa (o es el propio organismo),
    se marca como dato mal leído.
  - Las dos reglas: los adjudicatarios que son personas físicas llevan el aviso de no publicar el nombre. Se
    reconocen por el NIF (DNI/NIE, entero o enmascarado); sin NIF y sin forma jurídica solo se avisa de que podría
    serlo, porque por la forma del nombre no se puede saber.

Uso:
    python backend/indicios_contratos.py --cache cache.db --salida candidatos.ndjson.gz [--muestra 25]
Sin --muestra solo imprime recuentos (se ejecuta en GitHub Actions, cuyo registro es público).
"""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata

VERSION_REGLA_1 = "fraccionamiento-v2"
VERSION_REGLA_2 = "menor-sobre-umbral-v1"
FACTOR_IVA = 1.21
PENALIZACION = {"espectaculos": 25, "emergencia": 20}
_RE_ESPECTACULO = re.compile(r"ACTUACI|CONCIERT|CONCERT|ESPECT|ORQUEST|ARTIST|CACHE|FIESTA|FESTES|FESTIVAL|VERBENA|"
                             r"CHARANGA|DISCOMOVIL|GRUPO MUSICAL|MUSICA EN DIRECTO|PREGON|FUEGOS ARTIFICIALES")
_RE_EMERGENCIA = re.compile(r"\bDANA\b|EMERGENCI|INCENDI|TEMPORAL DE (?:LLUVIA|VIENTO|NIEVE|MAR)|TEMPORALES|INUNDACI|RIADA|BORRASCA|CATASTROF|TORMENTA|"
                            r"GOTA FRIA|DESPRENDIMIENTO|DERRUMBE|ERUPCI|VOLCAN")
UMBRAL = {"obras": 40000.0, "servicios": 15000.0, "suministros": 15000.0}
VENTANA_DIAS = 30
MINIMO_RELATIVO = 0.40            # cada contrato del grupo, al menos el 40 % del umbral
PEGADO = 0.90                     # "pegado al umbral": entre el 90 % y el 100 %
# Fuentes cuyo importe está verificado SIN IVA (misma lista que _FUENTES_CM_SIN_IVA de app.py)
FUENTES_SIN_IVA = {"torre-pacheco", "cartagena-governalia", "ibi-governalia", "sax-governalia",
                   "vilamarxant-governalia", "castello-governalia", "xirivella-governalia",
                   "santabrigida-governalia", "alzira-governalia", "valencia_capital", "alicante", "leganes",
                   "torrent", "la_laguna", "sevilla", "torrejon", "place-menores"}
# Palabras que no identifican un objeto (genéricas de la contratación, castellano, catalán, gallego, euskera)
GENERICAS = set("""SERVICIO SERVICIOS SUMINISTRO SUMINISTROS CONTRATO CONTRATOS MENOR MENORES OBRA OBRAS PARA SOBRE
ENTRE DESDE HASTA MUNICIPAL MUNICIPALES MUNICIPIO AYUNTAMIENTO CONTRACTE CONTRACTES SERVEI SERVEIS SUBMINISTRAMENT
SUBMINISTRAMENTS AJUNTAMENT CONCELLO SERVIZO SERVIZOS SUBMINISTRACION ADQUISICION COMPRA PRESTACION REALIZACION
TRABAJOS TRABAJO DIVERSOS DIVERSAS VARIOS VARIAS MATERIAL MATERIALES GENERAL GENERALES CONTRATACION EXPEDIENTE
FACTURA FACTURAS SEGUN PRESUPUESTO EJERCICIO MANTENIMIENTO REPARACION REPARACIONES ANUAL MENSUAL NECESARIOS
NECESARIAS DESTINADO DESTINADOS DESTINADA ADJUDICACION LICITACION ZERBITZUA HORNIDURA KONTRATUA""".split())
_RE_DNI = re.compile(r"^\d{8}[A-Z]$")
_RE_NIE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
# NIF enmascarado, por la fuente o por enmascarar_nif.py ("***4567**", "****4567*", "XXXXX750E", "05*****8F"): las
# administraciones solo enmascaran el de las personas físicas. Mismo criterio que _persona_fisica_cm de app.py.
_RE_NIF_ENMASCARADO = re.compile(r"^(?=.*[*]|.*X{4,})[0-9A-Z*]{6,12}$")
FACTOR_ERROR_CLASIFICACION = 3.0   # regla 2: por encima de 3 veces el umbral, probable error de clasificación
AVISO_ERROR_CLASIFICACION = ("probable error de clasificación: más de 3 veces el umbral del contrato menor (suele ser "
                             "un contrato de otro procedimiento publicado en la lista de menores)")
AVISO_DATO_MAL_LEIDO = "dato mal leído: el adjudicatario parece el objeto del contrato y no una empresa"
AVISO_ES_EL_ORGANISMO = "dato mal leído: el adjudicatario es el propio organismo"
AVISO_PERSONA_FISICA = "PERSONA FÍSICA: no publicar el nombre"
AVISO_POSIBLE_PERSONA_FISICA = ("sin NIF y sin forma jurídica: podría ser una persona física; no publicar el nombre "
                                "sin comprobarlo")
# Formas jurídicas y palabras de entidad en cualquier parte del nombre (ya normalizado, sin puntuación)
_RE_ENTIDAD = re.compile(
    r"\b(S L L|S A L|S L U|S A U|S L P|S L N E|S R L|S L|S A|S C|S COOP\w*|COOP\w*|C B|S C P|S C C L|SCCL|SCP|SLL|SAL|SLU|"
    r"SAU|SLP|SLNE|SRL|SL|SA|SC|CB|UTE|U T E|AIE|LTD|GMBH|INC|SOCIEDAD|SOCIETAT|COOPERATIVA|FUNDACION|FUNDACIO|ASOC\w*|"
    r"ASSOC\w*|ELKARTE\w*|KOOP\w*|HERMANOS|HNOS|COMUNIDAD|UNIVERSI\w+|AYUNTAMIENTO|AJUNTAMENT|CONCELLO|UDALA|CONSORCI\w*|"
    r"CONSELL|MANCOMUNI\w+|DIPUTACI\w+|COLEGIO|COL LEGI|CAMARA|CAMBRA|INSTITUT\w*|CLUB|FEDERACI\w+|CRUZ ROJA|CREU ROJA|"
    r"CARITAS|GREMI\w*|ORQUEST\w+|PARROQUIA|OBISPADO|SECRETARIA|MUTUA\w*|EMPRESA|GRUPO?|CENTRO?|ESTUDIO|TALLERES)\b")
# Comienzos propios de la descripción de un contrato, no del nombre de una empresa
_RE_OBJETO = re.compile(
    r"^(ASESORAMIENTO|SERVICIOS? (DE|DEL|PARA|EN)|SUMINISTROS? (DE|DEL|PARA|E)|OBRAS? (DE|DEL|PARA|EN)|"
    r"MANTENIMIENTO (DE|DEL|PREVENTIVO)|REPARACION|ADQUISICION|CONTRATACION|REDACCION|TRABAJOS (DE|PARA|EN)|"
    r"ALQUILER (DE|DEL)|ARRENDAMIENTO|EJECUCION|INSTALACION (DE|DEL)|LIMPIEZA (DE|DEL)|ASISTENCIA TECNICA|ELABORACION|"
    r"ORGANIZACION (DE|DEL)|ACTUALIZACION|RENOVACION|SUSTITUCION|PROYECTO (DE|DEL|PARA)|PLAN (DE|MUNICIPAL)|CURSO|"
    r"RECAUDACION|REALIZACION|PRESTACION|COMPRA (DE|DEL)|CONTRATO|ACONDICIONAMIENTO|MEJORA (DE|DEL)|REFORMA (DE|DEL)|"
    r"REHABILITACION|PAVIMENTACION|URBANIZACION (DE|DEL)|DIRECCION (DE|FACULTATIVA)|COORDINACION|INFORME|IMPARTICION|"
    r"ACTUACION|CAMPANA|RETIRADA|DEMOLICION|DESBROCE|SERVEI (DE|D)|SUBMINISTRAMENT|OBRES (DE|D)|REDACCIO|ADQUISICIO|"
    r"CONTRACTACIO|SERVIZO (DE|DO)|SUBMINISTRACION|LOTE)\b")


def normalizar(s):
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", s).split())


def nombre_empresa(s):
    s = normalizar(s)
    s = re.sub(r"\b(S L U|S L|S A U|S A|SLU|SL|SAU|SA|SLL|S COOP|SCOOP|SOCIEDAD LIMITADA|SOCIEDAD ANONIMA|C B|CB)\b",
               " ", s)
    return " ".join(s.split())


def tipo_contrato(t):
    t = (t or "").upper()
    if "OBR" in t:
        return "obras"
    if "SERV" in t:
        return "servicios"
    if "SUMIN" in t or "SUBMIN" in t or t.startswith("SUM"):
        return "suministros"
    return ""


def palabras(d):
    return {w for w in normalizar(d).split() if len(w) >= 5 and w not in GENERICAS and not w.isdigit()}


def es_persona_fisica(nif):
    """Por el NIF: DNI o NIE, entero o enmascarado. Euskadi enmascara también algunos CIF ("XXXXX0807"): esos
    terminan en cifra, y un DNI/NIE termina siempre en letra."""
    n = re.sub(r"[\s.\-]", "", (nif or "").upper())
    if _RE_DNI.match(n) or _RE_NIE.match(n):
        return True
    return bool(n and _RE_NIF_ENMASCARADO.match(n) and not (n.startswith("XXXX") and n[-1].isdigit()))


def nif_enmascarado(nif):
    n = re.sub(r"[\s.\-]", "", (nif or "").upper())
    return bool(n and _RE_NIF_ENMASCARADO.match(n))


def adjudicatario_mal_leido(adjudicatario, organismo, nif):
    """Aviso si el campo del adjudicatario no trae una empresa: el objeto del contrato (Iurreta, "ASESORAMIENTO EN
    PROCEDIMIENTO SANCIONADOR") o el propio organismo. '' si parece un adjudicatario normal."""
    a = normalizar(adjudicatario)
    if not a:
        return ""
    if a == normalizar(organismo):
        return AVISO_ES_EL_ORGANISMO
    if _RE_OBJETO.search(a) and not _RE_ENTIDAD.search(a) and not es_persona_fisica(nif):
        return AVISO_DATO_MAL_LEIDO
    return ""


def avisos_adjudicatario(adjudicatario, organismo, nif):
    """(avisos, persona_fisica, puntos_a_restar) comunes a las dos reglas."""
    mal = adjudicatario_mal_leido(adjudicatario, organismo, nif)
    if mal:
        return [mal], False, 40
    if es_persona_fisica(nif):
        return [AVISO_PERSONA_FISICA], True, 0
    if not (nif or "").strip() and adjudicatario and not _RE_ENTIDAD.search(normalizar(adjudicatario)):
        return [AVISO_POSIBLE_PERSONA_FISICA], False, 0
    return [], False, 0


def nif_mostrar(nif):
    """Como _nif_mostrar de app.py: el DNI/NIE de un autónomo nunca sale entero."""
    n = (nif or "").upper().strip()
    if _RE_DNI.match(n):
        return "***" + n[3:7] + "**"
    if _RE_NIE.match(n):
        return "****" + n[4:8] + "*"
    return n


def fecha_valida(f, hoy):
    try:
        d = dt.date.fromisoformat((f or "")[:10])
    except ValueError:
        return None
    return d if dt.date(2015, 1, 1) <= d <= hoy else None


def deduplicar(filas):
    """Quita duplicados dentro de un grupo (el mismo contrato traído por el feed de PLACE y por la fuente propia):
    misma fecha (±3 días), importe a ±2 % (o ×1,21 por IVA) y alguna palabra común. Se queda con el de PLACE, que es
    SIN IVA."""
    filas = sorted(filas, key=lambda c: (c["fecha"], c["fuente"] != "place-menores"))
    # Registros idénticos (mismo día, mismo importe al céntimo, misma descripción) en la MISMA fuente: casi siempre es
    # el mismo contrato publicado dos veces (medido el 05-10: 337 candidatos, 22 de los 151 mejor puntuados, solo
    # existían por eso). Se dejan en uno y el candidato lo avisa.
    vistos, unicas, identicos = set(), [], 0
    for c in filas:
        k = (c["fuente"], c["fecha"], round(c["importe"], 2), normalizar(c["descripcion"]))
        if k in vistos:
            identicos += 1
            continue
        vistos.add(k)
        unicas.append(c)
    filas = unicas
    fuera = set()
    for i, a in enumerate(filas):
        if i in fuera:
            continue
        for j in range(i + 1, len(filas)):
            b = filas[j]
            if (b["fecha"] - a["fecha"]).days > 3:
                break
            if j in fuera or a["fuente"] == b["fuente"]:
                continue
            r = b["importe"] / a["importe"] if a["importe"] else 0
            if (0.98 <= r <= 1.02 or 1.19 <= r <= 1.23 or 0.81 <= r <= 0.84) and (a["palabras"] & b["palabras"]):
                fuera.add(j)
    return [c for k, c in enumerate(filas) if k not in fuera], len(fuera), identicos


def mejor_racimo(filas, umbral):
    """Mayor conjunto de contratos que cumple la regla 1 estricta: ventana de 30 días desde un contrato ancla, todos
    >= 40 % del umbral y con alguna palabra del objeto en común con el ancla; la suma supera el umbral."""
    cand = [c for c in filas if c["importe"] >= MINIMO_RELATIVO * umbral]
    mejor = None
    for a in range(len(cand)):
        grupo = [cand[a]]
        for b in range(a + 1, len(cand)):
            if (cand[b]["fecha"] - cand[a]["fecha"]).days > VENTANA_DIAS:
                break
            if cand[a]["palabras"] & cand[b]["palabras"]:
                grupo.append(cand[b])
        suma = sum(c["importe"] for c in grupo)
        if len(grupo) >= 2 and suma > umbral and (mejor is None or suma > mejor[1]):
            mejor = (grupo, suma)
    return mejor


def jaccard_medio(grupo):
    pares = [(a, b) for i, a in enumerate(grupo) for b in grupo[i + 1:]]
    if not pares:
        return 0.0
    return sum(len(a["palabras"] & b["palabras"]) / max(1, len(a["palabras"] | b["palabras"])) for a, b in pares) / len(pares)


def puntuar(grupo, suma, umbral, sin_iva, con_nif):
    """0-100. Ordena la cola: primero lo más parecido a un objeto partido y con datos más fiables."""
    pts = {}
    pts["suma"] = round(min(suma / umbral, 4.0) / 4.0 * 30)                               # 1,1x -> 8; 4x o más -> 30
    pegados = sum(1 for c in grupo if PEGADO * umbral <= c["importe"] < umbral)
    pts["pegados_al_umbral"] = 20 if pegados >= 2 else (10 if pegados == 1 else 0)
    dias = (max(c["fecha"] for c in grupo) - min(c["fecha"] for c in grupo)).days
    pts["cercania"] = 15 if dias == 0 else (10 if dias <= 7 else 5)
    pts["objeto_parecido"] = round(jaccard_medio(grupo) * 20)
    pts["fiabilidad"] = (10 if sin_iva else 0) + (5 if con_nif else 0)
    return sum(pts.values()), pts, pegados, dias


def candidato_regla2(r, muni, t, fecha, imp):
    umbral = UMBRAL[t]
    ratio = imp / umbral
    fuente = r["fuente"] or ""
    nif = (r["nif"] or "").upper().strip()
    sin_iva = fuente in FUENTES_SIN_IVA
    avisos = []
    if not sin_iva:
        avisos.append("base de IVA sin verificar: aun así supera el umbral descontando un 21 % de IVA")
    if not nif:
        avisos.append("sin NIF del adjudicatario")
    puntos = {"exceso": round(min((ratio - FACTOR_IVA) / 2.0, 1.0) * 40) + 30, "fiabilidad": (15 if sin_iva else 0) +
              (5 if nif else 0)}
    if ratio > 25:
        avisos.append("importe desproporcionado para un menor: probable error de la fuente (importe o tipo)")
        puntos["posible_error_de_origen"] = -40
    elif ratio > FACTOR_ERROR_CLASIFICACION:
        avisos.append(AVISO_ERROR_CLASIFICACION)
        puntos["probable_error_de_clasificacion"] = -30
    categoria = "espectaculos" if _RE_ESPECTACULO.search(normalizar(r["descripcio"])) else (
        "emergencia" if _RE_EMERGENCIA.search(normalizar(r["descripcio"])) else "")
    if categoria == "emergencia":
        return None          # la emergencia (art. 120 LCSP) no tiene el límite del contrato menor: no es un indicio
    avisos_adj, persona_fisica, resta = avisos_adjudicatario(r["adjudicatari"], r["organisme"], nif)
    avisos += avisos_adj
    if resta:
        puntos["dato_mal_leido"] = -resta
    huella = hashlib.sha256(f'{VERSION_REGLA_2}|{r["id"]}'.encode()).hexdigest()[:20]
    return {"huella": huella, "regla": VERSION_REGLA_2, "categoria": categoria, "municipio": muni["municipio"],
            "provincia": muni["provincia"] or "", "organismo": r["organisme"] or "",
            "adjudicatario": r["adjudicatari"] or "", "nif": nif_mostrar(nif), "persona_fisica": persona_fisica,
            "tipo": t, "umbral": umbral, "n_contratos": 1, "suma": round(imp, 2), "dias": 0, "pegados_al_umbral": 0,
            "desde": fecha.isoformat(), "hasta": fecha.isoformat(), "puntuacion": max(0, sum(puntos.values())),
            "puntos": puntos, "avisos": avisos,
            "contratos": [{"id": r["id"], "fecha": fecha.isoformat(), "importe": imp,
                           "descripcion": (r["descripcio"] or "")[:300], "fuente": fuente}]}


def analizar(cache, hoy):
    db = sqlite3.connect(cache)       # solo lee
    db.row_factory = sqlite3.Row
    candidatos = []
    stats = collections.Counter()
    # Una sola pasada por el índice (municipio, provincia): se procesa cada municipio al terminar de leerlo, así en
    # memoria solo hay los contratos de un municipio a la vez.
    def por_municipio():
        actual, filas = None, []
        for r in db.execute("SELECT id, municipio, provincia, organisme, adjudicatari, nif, import_num, "
                            "data_adjudicacio, tipus_contracte, descripcio, fuente FROM contratos_menors_locales "
                            "ORDER BY municipio, provincia"):
            clave = (r["municipio"], r["provincia"])
            if clave != actual and filas:
                yield actual, filas
                filas = []
            actual = clave
            filas.append(r)
        if filas:
            yield actual, filas

    for (m_nombre, m_prov), filas_muni in por_municipio():
        muni = {"municipio": m_nombre, "provincia": m_prov}
        grupos = collections.defaultdict(list)
        nombres_por_nif = collections.defaultdict(set)
        r2_muni = []
        for r in filas_muni:
            stats["contratos"] += 1
            t = tipo_contrato(r["tipus_contracte"])
            f = fecha_valida(r["data_adjudicacio"], hoy)
            imp = r["import_num"] or 0
            if not t or not f or imp <= 0:
                stats["no_evaluables"] += 1
                continue
            if imp >= UMBRAL[t]:
                if imp >= FACTOR_IVA * UMBRAL[t]:
                    c2 = candidato_regla2(r, muni, t, f, float(imp))
                    if c2:
                        r2_muni.append(c2)
                    else:
                        stats["regla2_emergencias_excluidas"] += 1
                continue                     # la regla 1 solo mira contratos por debajo del umbral
            nif = (r["nif"] or "").upper().strip()
            emp = nif or "N:" + nombre_empresa(r["adjudicatari"])
            if emp in ("N:", ""):
                continue
            if nif_enmascarado(nif):
                # Un NIF enmascarado ("***4567**") solo enseña 4 cifras: dos personas distintas pueden compartirlo.
                # Se agrupa por NIF y nombre juntos (las palabras del nombre en cualquier orden) para no mezclarlas.
                nombre = " ".join(sorted(nombre_empresa(r["adjudicatari"]).split()))
                nombres_por_nif[(normalizar(r["organisme"]), nif, t)].add(nombre)
                emp = nif + "|" + nombre
            grupos[(normalizar(r["organisme"]), emp, t)].append({
                "id": r["id"], "fecha": f, "importe": float(imp), "descripcion": (r["descripcio"] or "")[:300],
                "fuente": r["fuente"] or "", "palabras": palabras(r["descripcio"]),
                "adjudicatario": r["adjudicatari"] or "", "organismo": r["organisme"] or "", "nif": nif})
        # Regla 2: el mismo contrato publicado por dos fuentes (feed de PLACE y portal propio) cuenta una vez: mismo
        # adjudicatario e importe a ±1 % (o ×1,21 por IVA), aunque la fecha difiera; se queda el de PLACE (sin IVA).
        r2_muni.sort(key=lambda c: c["contratos"][0]["fuente"] != "place-menores")
        elegidos = []
        for c in r2_muni:
            emp = c["nif"] or nombre_empresa(c["adjudicatario"])
            if any((e["nif"] or nombre_empresa(e["adjudicatario"])) == emp and
                   any(0.99 <= c["suma"] / e["suma"] * f <= 1.01 for f in (1, 1.21, 1 / 1.21)) for e in elegidos):
                stats["regla2_duplicados_quitados"] += 1
                continue
            elegidos.append(c)
        candidatos.extend(elegidos)
        for (org, emp, t), filas in grupos.items():
            if len(filas) < 2:
                continue
            stats["grupos"] += 1
            filas, dup, identicos = deduplicar(filas)
            stats["duplicados_quitados"] += dup
            stats["registros_identicos_unidos"] += identicos
            res = mejor_racimo(filas, UMBRAL[t])
            if not res:
                continue
            grupo, suma = res
            sin_iva = all(c["fuente"] in FUENTES_SIN_IVA for c in grupo)
            con_nif = not emp.startswith("N:")
            puntos, desglose, pegados, dias = puntuar(grupo, suma, UMBRAL[t], sin_iva, con_nif)
            avisos = []
            if not sin_iva:
                avisos.append("base de IVA sin verificar en alguna fuente: la suma podría incluir IVA")
            if not con_nif:
                avisos.append("sin NIF: contratos agrupados por el nombre del adjudicatario")
            if identicos:
                avisos.append(f"{identicos} registro(s) idéntico(s) unidos: posible publicación duplicada en la fuente")
            if len({c["fuente"] for c in grupo}) > 1:
                avisos.append("contratos de fuentes distintas: comprobar que no son el mismo contrato duplicado")
            categoria = ""
            if all(_RE_ESPECTACULO.search(normalizar(c["descripcion"])) for c in grupo):
                categoria = "espectaculos"
                avisos.append("espectáculos o fiestas: contratar a artistas distintos puede justificarse por "
                              "exclusividad; revisar si es una misma programación partida")
            elif any(_RE_EMERGENCIA.search(normalizar(c["descripcion"])) for c in grupo):
                categoria = "emergencia"
                avisos.append("posible tramitación de emergencia (art. 120 LCSP: DANA, incendio, temporal...)")
            if categoria:
                desglose["categoria"] = -PENALIZACION[categoria]
                puntos = max(0, puntos - PENALIZACION[categoria])
            nif_ej = next((c["nif"] for c in grupo if c["nif"]), "")
            avisos_adj, persona_fisica, resta = avisos_adjudicatario(grupo[0]["adjudicatario"], grupo[0]["organismo"],
                                                                     nif_ej)
            avisos += avisos_adj
            if resta:
                desglose["dato_mal_leido"] = -resta
                puntos = max(0, puntos - resta)
            # La huella identifica al candidato de una semana a otra (y conserva lo ya decidido). Con NIF enmascarado
            # sigue siendo la de siempre (solo el NIF) mientras bajo ese NIF haya un único nombre en el organismo;
            # si hay varios, eran personas mezcladas y cada una estrena huella.
            emp_huella = emp
            if "|" in emp and len(nombres_por_nif[(org, emp.split("|")[0], t)]) == 1:
                emp_huella = emp.split("|")[0]
            else:
                stats["grupos_separados_por_nombre"] += 1 if "|" in emp else 0
            huella = hashlib.sha256(f'{VERSION_REGLA_1}|{muni["municipio"]}|{muni["provincia"]}|{org}|{emp_huella}|{t}|'
                                    f'{min(c["fecha"] for c in grupo)}'.encode()).hexdigest()[:20]
            candidatos.append({
                "huella": huella, "regla": VERSION_REGLA_1, "categoria": categoria, "municipio": muni["municipio"],
                "provincia": muni["provincia"] or "", "organismo": grupo[0]["organismo"],
                "adjudicatario": grupo[0]["adjudicatario"], "nif": nif_mostrar(nif_ej),
                "persona_fisica": persona_fisica, "tipo": t, "umbral": UMBRAL[t],
                "n_contratos": len(grupo), "suma": round(suma, 2), "dias": dias, "pegados_al_umbral": pegados,
                "desde": min(c["fecha"] for c in grupo).isoformat(), "hasta": max(c["fecha"] for c in grupo).isoformat(),
                "puntuacion": puntos, "puntos": desglose, "avisos": avisos,
                "contratos": [{"id": c["id"], "fecha": c["fecha"].isoformat(), "importe": c["importe"],
                               "descripcion": c["descripcion"], "fuente": c["fuente"]} for c in grupo]})
    candidatos.sort(key=lambda c: (-c["puntuacion"], -c["suma"]))
    return candidatos, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--muestra", type=int, default=0, help="imprime los N primeros (solo en local: lleva nombres)")
    a = ap.parse_args()
    candidatos, stats = analizar(a.cache, dt.date.today())
    with gzip.open(a.salida, "wt", encoding="utf-8") as f:
        for c in candidatos:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"contratos leídos: {stats['contratos']} ({stats['no_evaluables']} sin tipo/fecha/importe válidos) | "
          f"grupos empresa+organismo+tipo con 2 o más: {stats['grupos']} | duplicados entre fuentes quitados: "
          f"{stats['duplicados_quitados']} | registros idénticos unidos: {stats['registros_identicos_unidos']} | "
          f"regla 2, duplicados entre fuentes quitados: {stats['regla2_duplicados_quitados']} | regla 2, emergencias "
          f"que ya no cuentan: {stats['regla2_emergencias_excluidas']} | regla 1, candidatos de un NIF enmascarado "
          f"compartido por varios nombres (separados): {stats['grupos_separados_por_nombre']}")
    marcas = (("probable error de clasificación (más de 3 veces el umbral)", AVISO_ERROR_CLASIFICACION),
              ("dato mal leído (el adjudicatario parece el objeto)", AVISO_DATO_MAL_LEIDO),
              ("dato mal leído (el adjudicatario es el organismo)", AVISO_ES_EL_ORGANISMO),
              ("persona física: no publicar el nombre", AVISO_PERSONA_FISICA),
              ("posible persona física (sin NIF ni forma jurídica)", AVISO_POSIBLE_PERSONA_FISICA))
    print("avisos de limpieza: " + " | ".join(f"{nombre}: {sum(1 for c in candidatos if aviso in c['avisos'])}"
                                              for nombre, aviso in marcas))
    for regla in (VERSION_REGLA_1, VERSION_REGLA_2):
        cs = [c for c in candidatos if c["regla"] == regla]
        tr = collections.Counter("80-100" if c["puntuacion"] >= 80 else "60-79" if c["puntuacion"] >= 60 else
                                 "40-59" if c["puntuacion"] >= 40 else "<40" for c in cs)
        print(f"{regla}: {len(cs)} candidatos | por puntuación: {dict(sorted(tr.items()))} | por tipo: "
              f"{dict(collections.Counter(c['tipo'] for c in cs))} | por categoría: "
              f"{dict(collections.Counter(c['categoria'] or 'general' for c in cs))}")
    if a.muestra:
        sys.stdout.reconfigure(encoding="utf-8")
        for c in [c for c in candidatos if c["regla"] == VERSION_REGLA_1][:a.muestra] + \
                 [c for c in candidatos if c["regla"] == VERSION_REGLA_2][:max(10, a.muestra // 3)]:
            print(f"\n[{c['regla']} {c['puntuacion']}{' ' + c['categoria'] if c['categoria'] else ''}] {c['municipio']} ({c['provincia']}) · {c['organismo']} -> {c['adjudicatario']} "
                  f"{c['nif']} · {c['tipo']} · {c['n_contratos']} contratos, {c['suma']:,.2f} € en {c['dias']} días "
                  f"(umbral {c['umbral']:,.0f}) · puntos {c['puntos']}")
            for k in c["contratos"]:
                print(f"     {k['fecha']}  {k['importe']:>11,.2f} €  [{k['fuente']}]  {k['descripcion'][:110]}")
            for av in c["avisos"]:
                print(f"     ! {av}")


if __name__ == "__main__":
    main()
