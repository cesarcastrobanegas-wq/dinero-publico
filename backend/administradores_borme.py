# encoding: utf-8
"""
Administradores vigentes de las sociedades adjudicatarias a partir del índice local del BORME (borme_actos.py).

1. Recorre los actos de cada sociedad en orden cronológico (nombramientos, reelecciones, ceses/dimisiones,
   cancelaciones de oficio, cambios de órgano de administración, extinción) siguiendo los cambios de denominación
   social, y calcula el órgano de administración vigente al final del periodo descargado.
2. Lo cruza con los adjudicatarios del sitio por denominación social normalizada (el BORME no publica NIF; las
   denominaciones son únicas por ley).
3. Escribe backend/administradores_borme.json: {clave de directores (NIF o nombre normalizado como en app.py):
   {"nombre", "cargo", "desde", "fuente", "sociedad_borme", "extinguida"}}.

Uso:  python backend/administradores_borme.py [--cache ruta/cache.db] [--salida ruta.json]

Límite conocido: solo ve lo publicado en el periodo descargado. Un administrador nombrado antes y sin ningún acto
posterior (frecuente en SL con cargo indefinido) no aparece: cuanto más atrás se descargue, más cobertura.
"""
import argparse
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


def construir_estado(db_path=BORME_DB):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    filas = db.execute("SELECT fecha, doc, numero, sociedad, soc_norm, actos FROM anuncios ORDER BY fecha, doc, numero").fetchall()
    den = Denominaciones()
    for fecha, doc, num, soc, norm, actos_json in filas:
        den.raiz(norm)
        nuevo = json.loads(actos_json).get("Cambio de denominación social")
        if nuevo:
            den.unir(norm, normalizar_denominacion(nuevo.split(" | ")[0]))
    estado = {}   # raiz -> {"admin": {cargo_label: {persona: (fecha, doc)}}, "extinguida": fecha|None, "nombres": set()}
    for fecha, doc, num, soc, norm, actos_json in filas:
        r = den.raiz(norm)
        e = estado.setdefault(r, {"admin": defaultdict(dict), "extinguida": None, "nombres": set(), "ultimo": fecha})
        e["nombres"].add(soc)
        e["ultimo"] = fecha
        actos = json.loads(actos_json)
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
    c = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True)
    adj = {}
    for (data,) in c.execute("SELECT data FROM municipios"):
        try:
            d = json.loads(data)
        except Exception:
            continue
        for ct in d.get("contratos", []):
            emp = ct.get("empresa", "")
            if emp and emp != "No localizada":
                adj.setdefault(clave_directores(emp, ct.get("nif", "")), (emp, ct.get("nif", "")))
    for emp, nif in c.execute("SELECT adjudicatari, nif FROM contratos_menors_locales"):
        if emp:
            adj.setdefault(clave_directores(emp, nif or ""), (emp, nif or ""))
    directores = {k: (n, cg) for k, n, cg in c.execute("SELECT clave, nombre, cargo FROM directores")}
    return adj, directores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(BASE, "cache.db"))
    ap.add_argument("--salida", default=SALIDA)
    a = ap.parse_args()
    t0 = time.time()
    den, estado = construir_estado()
    print(f"sociedades en el índice: {len(estado):,} ({time.time() - t0:.0f} s)")
    adj, directores = adjudicatarios(a.cache)
    salida, stats = {}, defaultdict(int)
    for clave, (emp, nif) in adj.items():
        norm = normalizar_denominacion(emp)
        if norm not in den.padre:
            stats["sin anuncios en el periodo"] += 1
            continue
        e = estado.get(den.raiz(norm))
        pr = administrador_principal(e) if e else None
        if not pr:
            stats["en el BORME pero sin órgano de administración vigente en el periodo"] += 1
            continue
        nombre, cargo, desde, doc = pr
        salida[clave] = {"nombre": nombre, "cargo": cargo, "desde": desde, "fuente": doc,
                         "sociedad_borme": sorted(e["nombres"])[-1], "extinguida": e["extinguida"]}
        if nif:   # también por nombre: muchos contratos de la misma sociedad llegan sin NIF
            salida.setdefault(_norm_app(emp), salida[clave])
        antes = directores.get(clave) or directores.get(_norm_app(emp))
        if not antes or not antes[0]:
            stats["NUEVO (antes sin administrador)"] += 1
        elif antes[1] == "Autónomo / Persona física":
            stats["CORRIGE una falsa 'persona física'"] += 1
        elif _norm_app(antes[0]) == _norm_app(nombre) or _norm_app(antes[0]) in _norm_app(nombre):
            stats["coincide con el que ya había"] += 1
        else:
            stats["DISTINTO del que había (más reciente en BORME)"] += 1
    json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"),
               "periodo": list(sqlite3.connect(f"file:{BORME_DB}?mode=ro", uri=True).execute(
                   "SELECT min(fecha), max(fecha) FROM dias").fetchone()),
               "administradores": salida}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"adjudicatarios: {len(adj):,}")
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {k:70s} {v:7,d}")
    print(f"con administrador vigente según el BORME: {len(salida):,} -> {a.salida}")


if __name__ == "__main__":
    main()
