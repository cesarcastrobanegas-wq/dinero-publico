# encoding: utf-8
"""
Administradores vigentes de las sociedades adjudicatarias a partir del índice local del BORME (borme_actos.py).

1. Recorre los actos de cada sociedad en orden cronológico (nombramientos, reelecciones, ceses/dimisiones,
   cancelaciones de oficio, cambios de órgano de administración, extinción) siguiendo los cambios de denominación
   social, y calcula el órgano de administración vigente al final del periodo descargado.
2. Lo cruza con los adjudicatarios del sitio por denominación social normalizada (el BORME no publica NIF; las
   denominaciones son únicas por ley), probando TODAS las grafías con las que aparece cada NIF.
3. Escribe backend/administradores_borme.json: {clave de directores (NIF o nombre normalizado como en app.py):
   {"nombre", "cargo", "desde", "fuente", "sociedad_borme", "extinguida"}}, más "periodo" y un "resumen" con
   recuentos (nunca nombres) de la cola: qué adjudicatarios no son del BORME ("no aplica") y cuántas sociedades
   quedan sin administrador.

Uso:  python backend/administradores_borme.py [--cache ruta/cache.db] [--salida ruta.json]
          [--historico ruta/borme_actos_historico.db] [--solo-primera-grafia] [--solo-recuentos]

Memoria (2026-10-09): el cálculo es por streaming. Solo se siguen las sociedades que son adjudicatarias (y las que
cambiaron de denominación hacia o desde una de ellas): SQLite ordena en disco los anuncios de esas sociedades y se
procesan uno a uno. Antes se cargaban en memoria los 3,3 millones de anuncios del índice (3,8 GB con 2021-2026);
con el histórico desde 2009 no habría cabido.

Límite conocido: solo ve lo publicado en el periodo descargado. Un administrador nombrado antes y sin ningún acto
posterior (frecuente en SL con cargo indefinido) no aparece: cuanto más atrás se descargue, más cobertura. El BORME
solo existe como dato abierto desde 2009.
"""
import argparse
import heapq
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from borme_actos import BORME_DB, CARGOS_ADMIN, cargos, normalizar_denominacion  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "administradores_borme.json")
BORME_DB_HISTORICO = os.environ.get("BORME_DB_HISTORICO", os.path.join(BASE, "borme_actos_historico.db"))


def _norm_app(s):
    """normalizar() de app.py (sin importarlo, para no arrancar el servidor)."""
    s = (s or "").lower().strip()
    for a, b in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n", "à": "a", "è": "e", "ò": "o",
                 "ï": "i", "ç": "c"}.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)


def clave_directores(empresa, nif):
    return nif.upper().strip() if nif else _norm_app(empresa)


def _cargo_admin(etiqueta):
    return CARGOS_ADMIN.get(re.sub(r"\s+", " ", etiqueta.strip().lower()))


class Denominaciones:
    """Unión de denominaciones de una misma sociedad (cambios de denominación social)."""

    def __init__(self):
        self.padre = {}

    def raiz(self, x):
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unir(self, a, b):
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.padre[ra] = rb


def _abrir(ruta):
    return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)


def _aplicar_anuncio(estado, raiz, fecha, doc, soc, actos):
    """Aplica un anuncio al estado de su sociedad. Los anuncios deben llegar en orden (fecha, doc, numero)."""
    e = estado.setdefault(raiz, {"admin": defaultdict(dict), "extinguida": None, "nombres": set(), "ultimo": fecha})
    e["nombres"].add(soc)
    e["ultimo"] = fecha
    if "Cambio del Organo de Administración" in actos.get("Otros conceptos", ""):
        e["admin"].clear()
    for acto in ("Ceses/Dimisiones", "Cancelaciones de oficio de nombramientos"):
        for etiqueta, personas in cargos(actos.get(acto, "")):
            c = _cargo_admin(etiqueta)
            if c:
                for p in personas:
                    e["admin"][c[0]].pop(p, None)
    for acto in ("Nombramientos", "Reelecciones"):
        for etiqueta, personas in cargos(actos.get(acto, "")):
            c = _cargo_admin(etiqueta)
            if not c:
                continue
            if c[0] == "Administrador Único":          # solo puede haber uno: el nuevo sustituye al anterior
                e["admin"][c[0]].clear()
            for p in personas:
                e["admin"][c[0]][p] = (fecha, doc)
    if "Extinción" in actos:
        e["extinguida"] = fecha
    elif e["extinguida"] and ("Nombramientos" in actos or "Reapertura hoja registral" in actos):
        e["extinguida"] = None


def construir_estado(objetivo, rutas):
    """Órgano de administración vigente de las sociedades cuyas denominaciones normalizadas están en `objetivo`,
    leyendo los índices de `rutas` (el histórico y el reciente) por streaming. Devuelve (den, estado)."""
    # 1) Cambios de denominación: son pocos (un anuncio de cada cien) y bastan para unir nombres de una sociedad.
    den = Denominaciones()
    for ruta in rutas:
        db = _abrir(ruta)
        for norm, actos_json in db.execute(
                "SELECT soc_norm, actos FROM anuncios WHERE actos LIKE '%Cambio de denominación social%'"):
            nuevo = json.loads(actos_json).get("Cambio de denominación social")
            if nuevo:
                den.unir(norm, normalizar_denominacion(nuevo.split(" | ")[0]))
        db.close()
    # 2) Denominaciones que interesan: las de los adjudicatarios y las unidas a ellas por un cambio de nombre.
    raices = {den.raiz(n) for n in objetivo}
    interesan = set(objetivo) | {n for n in list(den.padre) if den.raiz(n) in raices}

    # 3) Los anuncios de esas sociedades, ordenados en disco por SQLite, de cada índice; se mezclan por fecha.
    def _flujo(ruta):
        db = _abrir(ruta)
        db.execute("PRAGMA temp_store=FILE")
        db.execute("CREATE TEMP TABLE objetivo (norm TEXT PRIMARY KEY) WITHOUT ROWID")
        db.executemany("INSERT OR IGNORE INTO objetivo VALUES (?)", ((n,) for n in interesan))
        yield from db.execute(
            "SELECT a.fecha, a.doc, a.numero, a.sociedad, a.soc_norm, a.actos FROM objetivo o "
            "JOIN anuncios a ON a.soc_norm = o.norm ORDER BY a.fecha, a.doc, a.numero")
        db.close()

    estado = {}
    for fecha, doc, _num, soc, norm, actos_json in heapq.merge(*(_flujo(r) for r in rutas), key=lambda f: f[:3]):
        _aplicar_anuncio(estado, den.raiz(norm), fecha, doc, soc, json.loads(actos_json))
    return den, estado


def _titulo(nombre):
    t = " ".join(w.capitalize() for w in nombre.split())
    # administradores que son sociedades: la forma jurídica en mayúsculas ("Seresco SA", no "Seresco Sa")
    t = re.sub(r"\bS\.(l\.u|a\.u|l|a)\b\.?", lambda m: "S." + m.group(1).upper() + ".", t)
    return re.sub(r"\b(Sl|Sa|Slu|Sau|Slp|Sll|Slne|Scoop|Ute)\b", lambda m: m.group(1).upper(), t)


def administrador_principal(e):
    """(nombre para mostrar, cargo, desde, doc) del cargo de mayor prioridad con alguien vigente."""
    prioridad = {v[0]: v[1] for v in CARGOS_ADMIN.values()}
    # "Consejero" suelto no se muestra como administrador: del consejo solo se conoce lo publicado en el periodo
    # descargado (p. ej. el último consejero nombrado), no su composición completa.
    vigentes = [(prioridad.get(c, 99), c, ps) for c, ps in e["admin"].items() if ps and c != "Consejero"]
    if not vigentes:
        return None
    _, cargo, personas = min(vigentes)
    orden = sorted(personas.items(), key=lambda kv: kv[1][0])          # por antigüedad del nombramiento
    nombres = [_titulo(p) for p, _ in orden]
    desde = max(v[0] for v in personas.values())
    doc = max(personas.values())[1]
    if len(nombres) == 1:
        return nombres[0], cargo, desde, doc
    plural = {"Administrador Solidario": "Administradores Solidarios", "Administrador Mancomunado": "Administradores Mancomunados",
              "Consejero": "Consejeros", "Liquidador": "Liquidadores"}.get(cargo, cargo)
    mostrados = nombres[:3]
    texto = ", ".join(mostrados[:-1]) + " y " + mostrados[-1] if len(mostrados) > 1 else mostrados[0]
    if len(nombres) > 3:
        texto = ", ".join(mostrados) + f" y {len(nombres) - 3} más"
    return texto, plural, desde, doc


def adjudicatarios(cache_path):
    """{clave de directores: {"nif", "nombres" (todas las grafías, la primera vista primero), "nf", "impf", "nm",
    "impm"}} de los contratos formales y menores, y la tabla `directores`."""
    c = _abrir(cache_path)
    adj = {}

    def _suma(emp, nif, formales, imp_f, menores, imp_m, guardado=None):
        a = adj.setdefault(clave_directores(emp, nif), {"nif": nif, "nombres": {}, "nf": 0, "impf": 0.0, "nm": 0, "impm": 0.0,
                                                        "guardado": {}})
        a["nombres"].setdefault(emp, None)
        a["nf"] += formales; a["impf"] += imp_f; a["nm"] += menores; a["impm"] += imp_m
        if guardado:            # qué lleva guardado el propio contrato formal (lo que se enseñaría sin el BORME)
            g = a["guardado"].setdefault(guardado, [0, 0.0])
            g[0] += formales; g[1] += imp_f

    for (data,) in c.execute("SELECT data FROM municipios"):
        try:
            d = json.loads(data)
        except Exception:
            continue
        for ct in d.get("contratos", []):
            emp = ct.get("empresa", "")
            if emp and emp != "No localizada":
                try:
                    imp = float(ct.get("importe_num") or 0)
                except (TypeError, ValueError):
                    imp = 0.0
                _suma(emp, ct.get("nif", "") or "", 1, imp, 0, 0.0,
                      clase_guardado(ct.get("directivo", ""), ct.get("cargo", ""), emp, ct.get("nif", "") or ""))
        del d
    for emp, nif, n, imp in c.execute("SELECT adjudicatari, nif, COUNT(*), SUM(import_num) FROM contratos_menors_locales "
                                      "WHERE adjudicatari IS NOT NULL AND adjudicatari <> '' GROUP BY adjudicatari, nif"):
        _suma(emp, nif or "", 0, 0.0, n, float(imp or 0))
    directores = {k: (n, cg) for k, n, cg in c.execute("SELECT clave, nombre, cargo FROM directores")}
    c.close()
    return adj, directores


# ── Qué adjudicatarios pueden estar en el BORME ────────────────────────────────────────────────────────────────
# El BORME publica sociedades mercantiles. Las personas físicas no tienen administrador, y asociaciones, fundaciones,
# cooperativas, comunidades de bienes, sociedades civiles, UTE y administraciones se inscriben en otros registros:
# para todas ellas buscar en el BORME "no aplica" y no deben contarse como pendientes.
_RE_FORMA = re.compile(r"(?i)(\bS\.?\s?L\.?(\s?U\.?|\s?L\.?|\s?P\.?|\s?N\.?E\.?)?\.?$|\bS\.?\s?A\.?(\s?U\.?|\s?L\.?|\s?T\.?)?\.?$|"
                       r"\bSOCIEDAD (AN[OÓ]NIMA|LIMITADA|DE RESPONSABILIDAD)|\bA\.?I\.?E\.?$|\bS\.?\s?COM\b)")
_RE_NO_MERCANTIL = re.compile(r"(?i)(\basociaci[oó]n?\b|\bassociaci[oó]\b|\bfundaci[oó]n?\b|\bayuntamiento\b|\bajuntament\b|"
                              r"\buniversi|\bdiputaci|\bconsorci|\bmancomunidad\b|\bcomunidad de (propietarios|bienes)\b|"
                              r"\bU\.?T\.?E\.?\b|\buni[oó]n temporal\b|\bclub\b|\bfederaci|\bcolegio\b|\bcol·legi\b|"
                              r"\bparroquia\b|\bc[aá]ritas\b|\bcruz roja\b|\bcreu roja\b|\bsindicat|\bS\.?\s?COOP|\bSCCL\b|"
                              r"\bS\.?\s?C\.?\s?P\.?$|\bC\.?\s?B\.?$)")
TIPO_SOCIEDAD, TIPO_PERSONA, TIPO_NO_MERCANTIL, TIPO_DUDOSO = "sociedad mercantil", "persona física", "entidad no mercantil", "sin clasificar"


def tipo_adjudicatario(nombre, nif):
    n = (nif or "").upper().strip()
    if re.match(r"^[AB]\d", n):
        return TIPO_SOCIEDAD
    if re.match(r"^[CDEFGHJNPQRSUVW]\d", n):
        return TIPO_NO_MERCANTIL
    if n and (re.match(r"^(\d|[XYZKLM]\d)", n) or "*" in n):
        return TIPO_PERSONA
    nombre = (nombre or "").strip()
    if _RE_NO_MERCANTIL.search(nombre):
        return TIPO_NO_MERCANTIL
    if _RE_FORMA.search(nombre):
        return TIPO_SOCIEDAD
    palabras = nombre.split()
    if 2 <= len(palabras) <= 4 and all(re.match(r"^[A-Za-zÁÉÍÓÚÑÜáéíóúñüàèòïç·'-]+$", p) for p in palabras):
        return TIPO_PERSONA
    return TIPO_DUDOSO


CLASES_GUARDADO = ("administrador antiguo sin respaldo del BORME", "apoderado o socio (oculto)", "persona física", "nada")


def clase_guardado(nombre, cargo, empresa, nif):
    """Qué es lo guardado para un contrato o un adjudicatario (misma regla que app.py al mostrar, sin el BORME)."""
    if not nombre:
        return "nada"
    c = _norm_app(cargo)
    if c.startswith("autonomo"):
        return "persona física" if tipo_adjudicatario(empresa, nif) in (TIPO_PERSONA, TIPO_DUDOSO) else "nada"
    if c.startswith("apoderad") or c.startswith("socio"):
        return "apoderado o socio (oculto)"
    return "administrador antiguo sin respaldo del BORME"


def resumen_visible(adj, situacion, directores):
    """Recuentos de lo que se enseña en los contratos: lo del BORME manda; si no lo hay, lo guardado."""
    filas = {k: {"contratos_formales": 0, "importe_formales": 0.0, "contratos_menores": 0, "importe_menores": 0.0}
             for k in ("según el BORME",) + CLASES_GUARDADO}
    for clave, a in adj.items():
        nombre0 = next(iter(a["nombres"]))
        if situacion[clave] in ("con administrador", "por nombre (NIF con varias sociedades)"):
            f = filas["según el BORME"]
            f["contratos_formales"] += a["nf"]; f["importe_formales"] += a["impf"]
            f["contratos_menores"] += a["nm"]; f["importe_menores"] += a["impm"]
            continue
        for clase, (n, imp) in a["guardado"].items():
            filas[clase]["contratos_formales"] += n; filas[clase]["importe_formales"] += imp
        d = directores.get(clave) or directores.get(_norm_app(nombre0)) or ("", "")
        f = filas[clase_guardado(d[0] or "", d[1] or "", nombre0, a["nif"])]
        f["contratos_menores"] += a["nm"]; f["importe_menores"] += a["impm"]
    for f in filas.values():
        f["importe_formales"], f["importe_menores"] = round(f["importe_formales"]), round(f["importe_menores"])
    return filas


def _imprimir_visible(filas):
    tf = sum(f["contratos_formales"] for f in filas.values()) or 1
    ti = sum(f["importe_formales"] for f in filas.values()) or 1
    tm = sum(f["contratos_menores"] for f in filas.values()) or 1
    print(f"{'QUÉ SE ENSEÑA EN CADA CONTRATO':46s} {'formales':>9s} {'%':>6s} {'M€ form.':>9s} {'%':>6s} {'menores':>10s} {'%':>6s}")
    for k, f in filas.items():
        print(f"{k:46s} {f['contratos_formales']:9,d} {100 * f['contratos_formales'] / tf:5.1f}% {f['importe_formales'] / 1e6:9,.0f} "
              f"{100 * f['importe_formales'] / ti:5.1f}% {f['contratos_menores']:10,d} {100 * f['contratos_menores'] / tm:5.1f}%")


def cruzar(adj, den, estado, solo_primera_grafia=False):
    """(salida {clave: registro}, situacion {clave: texto}) -- la situación de cada adjudicatario frente al BORME."""
    salida, situacion = {}, {}
    for clave, a in adj.items():
        nombres = list(a["nombres"])
        if solo_primera_grafia:
            nombres = nombres[:1]
        hallados = {}          # raiz -> (registro, nombres que casan)
        visto = False          # alguna grafía tiene anuncios en el periodo
        for emp in nombres:
            r = den.raiz(normalizar_denominacion(emp))
            e = estado.get(r)
            if not e:
                continue
            visto = True
            pr = administrador_principal(e)
            if pr:
                hallados.setdefault(r, ({"nombre": pr[0], "cargo": pr[1], "desde": pr[2], "fuente": pr[3],
                                         "sociedad_borme": sorted(e["nombres"])[-1], "extinguida": e["extinguida"]}, []))[1].append(emp)
        if len(hallados) == 1:
            registro, casan = next(iter(hallados.values()))
            salida[clave] = registro
            if a["nif"]:   # también por nombre: muchos contratos de la misma sociedad llegan sin NIF
                for emp in casan:
                    salida.setdefault(_norm_app(emp), registro)
            situacion[clave] = "extinguida" if registro["extinguida"] else "con administrador"
        elif len(hallados) > 1:
            # Las grafías de un mismo NIF casan con sociedades DISTINTAS (NIF mal puesto en algún contrato, UTE con el
            # NIF de un socio...): no se atribuye nada al NIF; cada contrato se resuelve por la denominación que lleva.
            for registro, casan in hallados.values():
                for emp in casan:
                    salida.setdefault(_norm_app(emp), registro)
            situacion[clave] = "por nombre (NIF con varias sociedades)"
        else:
            situacion[clave] = "sin órgano vigente" if visto else "no consta"
    return salida, situacion


def resumen_cola(adj, situacion, directores):
    """Recuentos (nunca nombres) por tipo de adjudicatario y situación frente al BORME."""
    filas = defaultdict(lambda: {"adjudicatarios": 0, "contratos_formales": 0, "importe_formales": 0.0,
                                 "contratos_menores": 0, "importe_menores": 0.0})
    for clave, a in adj.items():
        tipo = tipo_adjudicatario(next(iter(a["nombres"])), a["nif"])
        sit = situacion[clave]
        if sit in ("con administrador", "extinguida", "por nombre (NIF con varias sociedades)"):
            grupo = f"en el BORME: {sit}"          # lo que el BORME da manda, sea cual sea el tipo deducido
        elif tipo == TIPO_SOCIEDAD:
            grupo = f"sociedad mercantil: {sit}"
        elif tipo == TIPO_DUDOSO:
            grupo = f"sin clasificar (sin NIF ni forma jurídica): {sit}"
        else:
            grupo = f"no aplica: {tipo}"
        f = filas[grupo]
        f["adjudicatarios"] += 1
        f["contratos_formales"] += a["nf"]; f["importe_formales"] += a["impf"]
        f["contratos_menores"] += a["nm"]; f["importe_menores"] += a["impm"]
    for f in filas.values():
        f["importe_formales"], f["importe_menores"] = round(f["importe_formales"]), round(f["importe_menores"])
    return dict(filas)


def _imprimir_resumen(resumen):
    tot = defaultdict(float)
    print(f"{'':52s} {'adjudic.':>9s} {'formales':>9s} {'M€ form.':>9s} {'menores':>9s} {'M€ men.':>8s}")
    for k, f in sorted(resumen.items()):
        print(f"{k:52s} {f['adjudicatarios']:9,d} {f['contratos_formales']:9,d} {f['importe_formales'] / 1e6:9,.0f} "
              f"{f['contratos_menores']:9,d} {f['importe_menores'] / 1e6:8,.0f}")
        for c, v in f.items():
            tot[c] += v
    print(f"{'TOTAL':52s} {int(tot['adjudicatarios']):9,d} {int(tot['contratos_formales']):9,d} "
          f"{tot['importe_formales'] / 1e6:9,.0f} {int(tot['contratos_menores']):9,d} {tot['importe_menores'] / 1e6:8,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(BASE, "cache.db"))
    ap.add_argument("--salida", default=SALIDA)
    ap.add_argument("--historico", default=BORME_DB_HISTORICO,
                    help="índice del BORME anterior al principal (2009-2020); se ignora si el fichero no existe")
    ap.add_argument("--sin-historico", action="store_true")
    ap.add_argument("--solo-primera-grafia", action="store_true", help="cruce como antes del 2026-10-09 (para comparar)")
    ap.add_argument("--solo-recuentos", action="store_true", help="no escribe el fichero: solo imprime los recuentos")
    a = ap.parse_args()
    t0 = time.time()
    rutas = [r for r in ([] if a.sin_historico else [a.historico]) if os.path.exists(r)] + [BORME_DB]
    periodos = [_abrir(r).execute("SELECT min(fecha), max(fecha), count(*) FROM dias").fetchone() for r in rutas]
    periodo = [min(p[0] for p in periodos), max(p[1] for p in periodos)]
    print(f"índices del BORME: {len(rutas)}; periodo {periodo[0]}-{periodo[1]}; días: {sum(p[2] for p in periodos):,}")
    adj, directores = adjudicatarios(a.cache)
    print(f"adjudicatarios: {len(adj):,} ({time.time() - t0:.0f} s)")
    objetivo = {normalizar_denominacion(emp) for x in adj.values() for emp in x["nombres"]}
    den, estado = construir_estado(objetivo, rutas)
    print(f"sociedades adjudicatarias con anuncios en el periodo: {len(estado):,} ({time.time() - t0:.0f} s)")
    salida, situacion = cruzar(adj, den, estado, a.solo_primera_grafia)
    stats = defaultdict(int)
    for clave, reg in salida.items():
        if clave not in adj:
            continue
        nombre0 = next(iter(adj[clave]["nombres"]))
        antes = directores.get(clave) or directores.get(_norm_app(nombre0))
        if not antes or not antes[0]:
            stats["NUEVO (antes sin administrador)"] += 1
        elif antes[1] == "Autónomo / Persona física":
            stats["CORRIGE una falsa 'persona física'"] += 1
        elif _norm_app(antes[0]) == _norm_app(reg["nombre"]) or _norm_app(antes[0]) in _norm_app(reg["nombre"]):
            stats["coincide con el que ya había"] += 1
        else:
            stats["DISTINTO del que había (más reciente en BORME)"] += 1
    resumen = resumen_cola(adj, situacion, directores)
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {k:70s} {v:7,d}")
    _imprimir_resumen(resumen)
    _imprimir_visible(resumen_visible(adj, situacion, directores))
    print(f"con administrador vigente según el BORME: {sum(1 for c in salida if c in adj):,} adjudicatarios, "
          f"{len(salida):,} claves ({time.time() - t0:.0f} s)")
    if a.solo_recuentos:
        return
    json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "periodo": periodo, "resumen": resumen,
               "administradores": salida}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"-> {a.salida}")


if __name__ == "__main__":
    main()
