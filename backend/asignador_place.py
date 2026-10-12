"""Asignación de las licitaciones de PLACE de entidades locales a su destino (fase 2 de cobertura, 2026-10-10).

Hasta ahora los contratos formales se asignaban a un municipio por el NOMBRE del órgano ("Ayuntamiento de X",
_regex_anclado en app.py). Eso dejaba fuera a los ayuntamientos que PLACE nombra distinto que la app (Las Rozas,
Borriana, Benicàssim), a los órganos sin esa fórmula (distritos y áreas de Madrid, "Gobierno de Zaragoza") y a los
entes municipales (organismos, patronatos, empresas). Aquí el destino sale de los datos oficiales del órgano, en
este orden:

  1. Entidades que NO son un municipio (DIR3 L02-L08, o por su jerarquía): diputaciones, cabildos y consells,
     mancomunidades, comarcas, áreas metropolitanas, consorcios y entidades locales menores -> ENTIDAD PROPIA.
  2. Jerarquía oficial "<Municipio> / Ayuntamientos / <Provincia>" (la misma regla que ya usan los contratos menores
     de PLACE, actualizar_contratos_menores_place.Asignador).
  3. Código INE del DIR3 del ayuntamiento (L01<INE><dígito>), contra la tabla OFICIAL del INE
     (ine_municipios.json). No se "aprende" de otros contratos: un código mal tecleado en origen arrastraba a otro
     municipio (agosto de 2026: Cárcer -> Canet d'en Berenguer). El NIF municipal (P<INE>00<letra>) NO se usa: su
     numeración es la de cuando se asignó y no coincide con el INE vigente en muchos municipios (piloto de
     julio-septiembre de 2026: P3502000G es San Bartolomé de Tirajana, pero 35020 es hoy La Aldea de San Nicolás;
     Llíria salía en Losa del Obispo).
  4. Localidad de la dirección del órgano, para entes bajo "Ayuntamientos" cuyo nombre ocupa el hueco del municipio.
  5. Empresas, fundaciones y organismos locales fuera de "Ayuntamientos": al municipio que PLACE pone en su
     jerarquía ("EMT de Madrid / Madrid / Comunidad de Madrid"). Si no hay un municipio único (ACOSOL, Aguas de
     Huesna: son de varios) -> ENTIDAD PROPIA, igual que una mancomunidad (criterio de César, 2026-10-10).
  6. Último recurso: el nombre del órgano, con el patrón vigente de la app. Así nada de lo que hoy se asigna se pierde.

Criterios de César (2026-10-10): los contratos de entes municipales cuentan en la ficha y en el Índice de su
municipio; las entidades propias tienen ficha aparte y no entran en el Índice municipal. Formentera es a la vez isla
y municipio: su Consell Insular (L03070001) va al municipio.

Este módulo no escribe en ninguna base ni usa la red."""
import collections
import json
import os
import re

import actualizar_contratos_menores_place as M

RUTA_INE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ine_municipios.json")

TIPOS_DIR3 = {"L02": "diputación", "L03": "cabildo o consell insular", "L04": "entidad local menor",
              "L05": "mancomunidad", "L06": "comarca", "L07": "área metropolitana", "L08": "agrupación local"}
# Etiquetas de la jerarquía de PLACE que no son el nombre de ninguna entidad.
_ROTULOS = re.compile(r"^(sector publico|entidades locales|sociedades, fundaciones y consorcios.*|otras entidades del sector publico|"
                      r"ayuntamientos|juntas vecinales|sociedades del cabildo.*)$")
_RE_DIPUTACION = re.compile(r"\b(diputacion|cabildo|consell insular|consejo insular)\b")
# Empresas privadas que publican en PLACE colgadas de una entidad local: nunca se asignan a un municipio (criterio
# de César, 2026-10-11). Tampoco las empresas MIXTAS con cualquier participación privada, sin mirar quién tiene la
# mayoría: las que lo dicen en el nombre y las conocidas (lista hecha de memoria, no contrastada una a una). Ni las
# juntas de compensación, entidades urbanísticas y comunidades de usuarios o regantes (son de particulares).
_RE_PRIVADA = re.compile(
    r"\b(aguas de valencia|global omnium|mixta|aguas de huelva|madrid calle 30|club de campo villa de madrid|"
    r"aigues municipals de paterna|cementerio jardin|aguas de montilla|(suministradora|comercializadora) electrica de cadiz|"
    r"cementerios y servicios funerarios de granada|abastecimiento y saneamiento de granada|terminal maritima de zaragoza|"
    r"parque cientifico y tecnologico de cordoba|aguas del puerto empresa municipal|aigues de sagunt|aigues de l'horta|"
    r"sanejament d'elx|aigues de cullera|aguas de cieza|aguas de jumilla|aguas de guadix|aguas de priego|teidagua|"
    r"aguas de telde|gorona del viento|junta de compensacion|entidad urbanistica|comunidad de usuarios|"
    r"comunidad general de regantes)\b")
# Entidades sin municipio en su jerarquía que César ha validado a mano (fase2_entidades_para_validar.csv): trozo del
# nombre normalizado -> (provincia, municipio) de la app. Lo que no esté aquí se queda como entidad propia.
VALIDADAS = {
    "fundacion para la promocion del empleo, la formacion profesional y el movimiento cooperativo": ("las_palmas", "Ingenio"),
    "fundacion andres de ribera": ("cadiz", "Jerez de la Frontera"),
    "mercazaragoza": ("zaragoza", "Zaragoza"),   # 51 % ayuntamiento y 49 % Mercasa, sin socio privado (zaragoza.es, 2017)
    "aquaoleiros": ("a_coruna", "Oleiros"),      # BORME 27-12-2021: socio único, Ayuntamiento de Oleiros
}
# Asociaciones y grupos de desarrollo rural: son de varios municipios aunque PLACE los cuelgue del de su sede.
_RE_VARIOS = re.compile(r"\b(asociacion|associacio|grupo de (accion|desarrollo)|grup d'accio)\b")
_RE_CARGO = re.compile(
    r"^(presidencia|vicepresidencia|presidente|vicepresidente|gerencia|gerente|direccion( general| gerente| gerencia)?|"
    r"consejeria delegada|consejer[oa] delegad[oa]|consejo de administracion|consejo rector|comision ejecutiva|"
    r"junta de gobierno( local)?|junta rectora|junta general|pleno|delegad[oa]|secretaria general|alcaldia)\s+"
    r"(de la |del |de las |de los |de l'|de |d')", re.I)
# Comunidad tal como la escribe PLACE -> clave de la app (para resolver "ente / municipio / comunidad").
_COMUNIDADES = [(r"andaluc", "andalucia"), (r"aragon", "aragon"), (r"asturias", "asturias"), (r"balear", "baleares"),
                (r"canarias", "canarias"), (r"cantabria", "cantabria"), (r"castilla y leon", "castilla_y_leon"),
                (r"castilla.la mancha", "castilla_la_mancha"), (r"catalu", "cataluna"), (r"valencia", "valenciana"),
                (r"extremadura", "extremadura"), (r"galicia", "galicia"), (r"madrid", "madrid"), (r"murcia", "murcia"),
                (r"navarra", "navarra"), (r"pais vasco|euskadi", "pais_vasco"), (r"rioja", "la_rioja"),
                (r"ceuta", "ceuta"), (r"melilla", "melilla")]


def _plano(s):
    """Minúsculas y sin tildes, carácter a carácter (misma longitud que el original, para cortar por posición)."""
    import unicodedata
    return "".join((unicodedata.normalize("NFD", c)[0] if unicodedata.normalize("NFD", c)[0].isalnum() else c).lower()
                   for c in s)


class AsignadorPlace:
    def __init__(self, A, ruta_ine=RUTA_INE):
        self.A = A
        self.asg = M.Asignador(A)
        self.norm = self.asg._norm
        with open(ruta_ine, encoding="utf-8") as f:
            self.ine = {k: tuple(v) for k, v in json.load(f)["municipios"].items()}
        # provincias con fuente propia de contratos formales: el resultado se calcula, pero no se aplica
        self.fuera = {"murcia"} | set(A.PROVINCIAS_CATALUNYA) | set(A.PROVINCIAS_PAIS_VASCO) | set(A.PROVINCIAS_NAVARRA)
        self.provs_de_comunidad = collections.defaultdict(list)
        for prov, com in A.COMUNIDAD_AUTONOMA_POR_PROVINCIA.items():
            self.provs_de_comunidad[com].append(prov)
        # índice del patrón por nombre vigente (mismo que generar_backfill_formales_place.py)
        self._idx = collections.defaultdict(list)
        for prov, lst in A.MUNICIPIOS_POR_PROVINCIA.items():
            if prov in self.fuera:
                continue
            for m in lst:
                for v in A._variantes_nombre_municipio(A.normalizar(m)):
                    pal = re.findall(r"[a-z0-9]+", v)
                    k = max(pal, key=len) if pal else v
                    if (prov, m) not in self._idx[k]:
                        self._idx[k].append((prov, m))
        self._rx = {}
        self.aprendido = {}

    # ---- patrón por nombre vigente (lo que se asigna HOY) ----
    def por_nombre(self, contrato):
        A = self.A
        on = A.normalizar(contrato.get("organo", ""))
        toks = set(re.findall(r"[a-z0-9]+", on)) | set(re.findall(r"[a-z0-9]+", on.replace("-", "")))
        out = set()
        for t in toks:
            for prov, m in self._idx.get(t, ()):
                if (prov, m) not in self._rx:
                    self._rx[(prov, m)] = A._regex_anclado(m)
                if not self._rx[(prov, m)].search(on):
                    continue
                cpn = A._cp_esperado_anclaje(m)
                if cpn and not contrato.get("cp", "").startswith(cpn):
                    continue
                if A._cp_de_otra_provincia(contrato, m, prov):
                    continue
                out.add((prov, m))
        return out

    # ---- piezas ----
    def es_local(self, r):
        # "ENTIDADES LOCALES" o "SOCIEDADES, FUNDACIONES Y CONSORCIOS ENTIDADES LOCALES" (empresas municipales sin DIR3)
        return (r["dir3"] or "").startswith("L") or any("entidades locales" in self.norm(x) for x in r["padres"])

    def aprender(self, registros):
        """Segunda pasada. Un mismo órgano aparece unas veces con jerarquía y otras sin ella (las áreas de gobierno y
        los distritos de Madrid, por ejemplo). Se apunta a qué municipio llevó la jerarquía cada código DIR3 y cada
        NIF de órgano, y solo si TODAS las veces fue el mismo (y al menos 3), se usa para las que vienen sin
        jerarquía. Es identidad exacta del órgano, no deducir el INE de un código."""
        votos = collections.defaultdict(collections.Counter)
        for r, res in registros:
            if res["destino"] == "municipio" and res["via"] == "jerarquía oficial":
                for k in (("dir3", r["dir3"]), ("nif", (r["nif_org"] or "").upper())):
                    if k[1]:
                        votos[k][(res["prov"], res["muni"])] += 1
        self.aprendido = {k: v.most_common(1)[0][0] for k, v in votos.items() if len(v) == 1 and sum(v.values()) >= 3}
        return len(self.aprendido)

    def _no_municipal(self, r):
        """Entidad bajo "Ayuntamientos" que no es el municipio (por el nombre del hueco o del órgano). A diferencia de
        actualizar_contratos_menores_place.es_no_municipal, no mira el DIR3: "L0461332" es Gestalgar mal tecleado."""
        p = r["padres"]
        hueco = p[p.index("Ayuntamientos") - 1] if "Ayuntamientos" in p and p.index("Ayuntamientos") > 0 else ""
        return bool(M.NO_MUNICIPAL.search(self.A.normalizar(hueco)) or M.NO_MUNICIPAL.search(self.A.normalizar(r["organo"])))

    def _ine(self, r):
        """(provincia, municipio) por el código INE del DIR3 del ayuntamiento, con la tabla oficial."""
        m = re.match(r"^L01(\d{5})\d$", r["dir3"] or "")
        if m and m.group(1) in self.ine:
            return self.ine[m.group(1)], "DIR3 del ayuntamiento"
        return None, ""

    def _ine_nif(self, r):
        """Solo para control de calidad: el municipio que saldría del NIF (no se usa para asignar)."""
        m = re.match(r"^P(\d{5})00[A-Z]$", (r["nif_org"] or "").upper())
        return self.ine.get(m.group(1)) if m else None

    def _nombre_entidad(self, r, patron=None):
        """Nombre de la entidad propia: el nodo de la jerarquía que casa con `patron` (o el primero que no sea un
        rótulo ni un territorio), y si no, el nombre del órgano sin el cargo que lo encabeza."""
        cands = []
        for x in r["padres"]:
            n = self.norm(x)
            if _ROTULOS.match(n):
                continue
            if patron is not None and patron.search(n):
                cands.append(x.strip())
            elif patron is None and not (self.asg.provincia(x) or self._comunidad(x)):
                return x.strip()
        if cands:
            return min(cands, key=len)      # "Cabildo Insular de Tenerife", no "Consejo de Gobierno Insular del Cabildo..."
        org = r["organo"].strip()
        for _ in range(2):                      # "Presidencia del Consejo de Administración de X" -> "X"
            m = _RE_CARGO.match(_plano(org))
            if not m:
                break
            org = org[m.end():].strip()
        return org

    def _comunidad(self, nombre):
        n = self.norm(nombre)
        if len(n) > 40:
            return None
        for pat, clave in _COMUNIDADES:
            if re.search(pat, n):
                return clave
        return None

    def _municipio_en_jerarquia(self, r):
        """"<ente> / <municipio> / <comunidad o provincia> / ...": el municipio, si es uno solo e inequívoco."""
        p = r["padres"]
        for i in range(1, len(p) - 1):
            # PLACE usa a veces "Diputación Provincial de Teruel" como nodo de la provincia (Urban Teruel)
            sig = re.sub(r"^diputacion( provincial| foral)? de ", "", self.norm(p[i + 1]))
            com, prov = self._comunidad(p[i + 1]), self.asg.provincia(p[i + 1]) or self.asg.provincia(sig)
            provs = [prov] if prov else self.provs_de_comunidad.get(com, [])
            if not provs:
                continue
            cands = {(pr, m) for pr in provs for m in [self.asg.nombre_a_municipio(p[i], pr)] if m}
            if len(cands) != 1:
                return None
            # La jerarquía pone la LOCALIDAD donde está el ente, que no siempre es su dueño: la Agencia Provincial
            # de Extinción de Incendios de Granada o el Instituto Leonés de Cultura son de la diputación. Solo se
            # asigna si el nombre del ente dice "municipal" o lleva el nombre del municipio, y no dice
            # provincial/insular/comarcal.
            pr, m = next(iter(cands))
            ente = self.norm(p[0] + " / " + r["organo"])
            if re.search(r"\b(provincial|insular|comarcal|diputacion|cabildo)\b", ente):
                return None
            formas = {f for f in self.asg._formas(m) if len(f) >= 4} | {self.norm(p[i])}
            if re.search(r"\bmunicipal(es)?\b", ente) or any(re.search(r"\b" + re.escape(f) + r"\b", ente) for f in formas):
                return (pr, m)
            return None
        return None

    # ---- regla completa ----
    def asignar(self, r, contratos=()):
        """r = registro de actualizar_contratos_menores_place.parsear(entry); contratos = los de app._entry_to_contratos.
        Devuelve {"destino": "municipio" | "entidad" | "", "prov", "muni", "tipo", "entidad", "via", "aplica"}."""
        res = {"destino": "", "prov": "", "muni": "", "tipo": "", "entidad": "", "via": "", "aplica": True}

        def muni(pm, via):
            res.update(destino="municipio", prov=pm[0], muni=pm[1], via=via, aplica=pm[0] not in self.fuera)
            return res

        def entidad(tipo, nombre, via):
            res.update(destino="entidad", tipo=tipo, entidad=nombre, via=via)
            return res

        if not self.es_local(r):
            res["via"] = "no es una entidad local"
            return res
        d, p = r["dir3"] or "", r["padres"]
        _nom = []

        def nombres():
            """Municipios que da HOY el patrón por nombre. Si es uno solo, un código o una jerarquía mal puestos en
            origen no lo mueven a otro municipio (Armuña de Almanzora con el DIR3 de Armuña, Segovia)."""
            if not _nom:
                _nom.append(set().union(*(self.por_nombre(c) for c in contratos)) if contratos else set())
            return _nom[0]
        texto = self.norm(r["organo"] + " / " + " / ".join(x for x in p if not _ROTULOS.match(self.norm(x))))
        bajo_ayto = "Ayuntamientos" in p

        # 1) entidades que no son un municipio
        if d == "L03070001":
            return muni(("baleares", "Formentera"), "Consell Insular de Formentera (isla y municipio)")
        es_ayto = bool(re.search(r"\b(ayuntamiento|ajuntament|concello|udala)\b", self.norm(r["organo"])))
        por_jer = self.asg.por_jerarquia(r) if bajo_ayto else (None, None)
        if not bajo_ayto and _RE_PRIVADA.search(self.norm((p[0] if p else "") + " / " + r["organo"])):
            return entidad("empresa o fundación local sin municipio único", self._nombre_entidad(r), "empresa privada o mixta")
        if not bajo_ayto:
            ente_v = self.norm((p[0] if p else "") + " / " + r["organo"])
            for trozo, pm in VALIDADAS.items():
                if trozo in ente_v:
                    return muni(pm, "entidad validada a mano")
        if re.match(r"^L0[2-8]\d{6}$", d):
            # Un antiguo código de entidad local menor en un ayuntamiento que PLACE ya cuelga de "Ayuntamientos" con
            # su nombre (Torrenueva Costa, municipio desde 2018) no lo convierte en entidad menor.
            # Tampoco si llega sin jerarquía y su nombre es el de un único municipio (Carrizo, El Palmar de Troya).
            if not (d[:3] == "L04" and es_ayto and (por_jer[0] or len(nombres()) == 1)):
                pat = {"L02": _RE_DIPUTACION, "L03": _RE_DIPUTACION}.get(d[:3])
                return entidad(TIPOS_DIR3[d[:3]], self._nombre_entidad(r, pat), "DIR3 " + d[:3])
        if any(self.norm(x) == "juntas vecinales" for x in p) or re.search(r"\bentidad local (menor|autonoma)\b|\bjunta vecinal\b", texto):
            return entidad("entidad local menor", self._nombre_entidad(r), "jerarquía o nombre")
        # (c) mancomunidades y consorcios que publican con el perfil (y el DIR3) del ayuntamiento que los aloja:
        # "Mancomunidad Integral Sierra Suroeste" bajo "Jerez de los Caballeros / Ayuntamientos" no es Jerez.
        org_n = self.norm(r["organo"])
        if not es_ayto:
            for clave, tipo in (("mancomunidad", "mancomunidad"), ("mancomunitat", "mancomunidad"), ("mancomunidade", "mancomunidad"),
                                ("consorcio", "consorcio"), ("consorci ", "consorcio")):
                if clave in org_n and not re.search(r"\bmunicipal\b", org_n):
                    return entidad(tipo, self._nombre_entidad({"padres": [], "organo": r["organo"]}), "nombre del órgano")

        # 2) jerarquía "<Municipio> / Ayuntamientos / <Provincia>"
        no_muni = bajo_ayto and self._no_municipal(r) and not (es_ayto and por_jer[0])
        if bajo_ayto and not no_muni:
            m, prov = por_jer
            if m:
                # La jerarquía también llega equivocada (el Ayuntamiento de Laguna de Cameros colgado de Cenicero):
                # si el nombre dice otro municipio y el DIR3 no confirma la jerarquía, manda el nombre.
                if es_ayto and len(nombres()) == 1 and (prov, m) not in nombres() and self._ine(r)[0] != (prov, m):
                    return muni(next(iter(nombres())), "nombre del órgano (la jerarquía indica otro municipio)")
                return muni((prov, m), "jerarquía oficial")
        # 3) código INE oficial del DIR3 del ayuntamiento. El DIR3 también llega mal tecleado (Andorra con el código
        # de Ansó): sin jerarquía que lo confirme, solo vale si el nombre del órgano lleva el del municipio.
        pm, via = self._ine(r)
        if pm and not no_muni and not (nombres() and pm not in nombres()):
            if any(re.search(r"\b" + re.escape(f) + r"\b", org_n.replace("-", " ")) for f in self.asg._formas(pm[1]) if len(f) >= 3):
                return muni(pm, via)
        # 3 bis) el mismo órgano (mismo DIR3 o mismo NIF) ya asignado por jerarquía en otras licitaciones
        for k in (("dir3", d), ("nif", (r["nif_org"] or "").upper())):
            if k in self.aprendido and not no_muni and not (nombres() and self.aprendido[k] not in nombres()):
                return muni(self.aprendido[k], "mismo órgano que otras licitaciones con jerarquía")
        if bajo_ayto:
            if no_muni:
                tipo = ("mancomunidad" if "mancomunidad" in texto else "consorcio" if "consorci" in texto else
                        "comarca" if "comarca" in texto else "entidad local menor")
                return entidad(tipo, self._nombre_entidad(r), "jerarquía o nombre")
            # 4) localidad del órgano
            m, prov = self.asg.por_ciudad(r)
            if m:
                return muni((prov, m), "localidad del órgano")

        # 5) fuera de "Ayuntamientos": diputaciones y sus entes, agrupaciones, y empresas/fundaciones locales
        if not bajo_ayto:
            ente = self.norm((p[0] if p else "") + " / " + r["organo"])
            # Sociedad municipal con la diputación solo como nodo de la provincia: es del municipio, no de la diputación.
            if re.search(r"\b(municipal(es)?|ayuntamiento|ajuntament|concello)\b", ente) and not _RE_DIPUTACION.search(ente) \
                    and not re.search(r"mancomuni|consorci|comarca", ente):
                pm = self._municipio_en_jerarquia(r)
                if pm:
                    return muni(pm, "ente con su municipio en la jerarquía")
            if _RE_DIPUTACION.search(texto):
                tipo = "diputación" if "diputacion" in texto else "cabildo o consell insular"
                return entidad(tipo, self._nombre_entidad(r, _RE_DIPUTACION), "jerarquía o nombre")
            for clave, tipo in (("mancomunidad", "mancomunidad"), ("mancomunitat", "mancomunidad"), ("consorci", "consorcio"),
                                ("comarca", "comarca"), ("metropolitan", "área metropolitana"), ("federacion", "federación de municipios")):
                if clave in texto:
                    return entidad(tipo, self._nombre_entidad(r), "jerarquía o nombre")
            pm = None if _RE_VARIOS.search(ente) else self._municipio_en_jerarquia(r)
            if pm:
                return muni(pm, "ente con su municipio en la jerarquía")
        # 6) último recurso: el nombre del órgano (patrón vigente)
        if len(nombres()) == 1:
            return muni(next(iter(nombres())), "nombre del órgano (último recurso)")
        if not bajo_ayto:
            return entidad("empresa o fundación local sin municipio único", self._nombre_entidad(r), "sin municipio en la jerarquía")
        res["via"] = "municipal sin resolver"
        return res
