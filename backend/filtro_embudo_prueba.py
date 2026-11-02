# encoding: utf-8
"""
Pruebas del embudo de licitaciones (filtro_embudo.py) con licitaciones INVENTADAS. No toca la base de datos ni la web.
Uso:  python backend/filtro_embudo_prueba.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filtro_embudo as E   # noqa: E402

AHORA = datetime(2026, 11, 1, 12, 0)
fallos = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        fallos.append(txt)


def lic(**k):
    base = {"id": "L1", "titulo": "Prueba", "organo": "Ayuntamiento inventado", "url": "https://ejemplo.test/1",
            "fin_plazo": "2026-11-20 14:00", "ambito": "local", "provincia": "murcia", "nuts": "ES620",
            "cpv": "90910000", "cpvs": ["90910000"], "tipo": "2", "procedimiento": "1", "presupuesto": 100_000,
            "valor_estimado": 100_000, "duracion_meses": 12, "req": {}, "lotes_detalle": []}
    base.update(k)
    return base


def perfil(**k):
    params = {"cpv": ["90"], "ambito": ["murcia"], "facturacion": ["150k-300k"], "trabajadores": ["1-5"],
              "clasificacion": ["no"]}
    params.update(k)
    p, err = E.leer(params)
    assert not err, err
    return p


def grupo(l, p=None):
    r = E.evaluar(l, p or perfil(), AHORA)
    return r[0]["grupo"] if r else None


# --- lectura del formulario
p, err = E.leer({})
ok(len(err) == 4, f"formulario vacío: 4 errores ({len(err)})")
p, err = E.leer({"cpv": ["90", "zz"], "ambito": ["valenciana", "p:murcia"], "facturacion": ["<60k"],
                 "trabajadores": ["1-5"], "importe_min": ["1.500.000"], "importe_max": ["1000"]})
ok(any("mínimo es mayor" in e for e in err), "importe mínimo > máximo: error")
ok(p["divisiones"] == ["90"], "sector inexistente descartado")
ok(set(p["provincias"]) == {"alicante", "castellon", "valencia", "murcia"}, f"comunidad + provincia ({p['provincias']})")
ok(p["importe_min"] == 1_500_000, "importe con puntos de miles")
p, err = E.leer({"cpv": ["45"], "ambito": ["toda"], "facturacion": ["<60k"], "trabajadores": ["1-5"],
                 "clasificacion": ["si"], "clas_codigos": ["c2-4, X"]})
ok(any("Clasificación" in e for e in err), "código de clasificación mal escrito: error")
ok(len(p["provincias"]) == len(E.TODAS_PROVINCIAS), "toda España = todas las provincias")
p, err = E.leer({"cpv": ["45"], "ambito": ["toda"], "facturacion": ["<60k"], "trabajadores": ["1-5"],
                 "clasificacion": ["no"], "clas_codigos": ["C2-4"]})
ok(not err and p["clasificacion"] == [], "con «No», los códigos escritos se ignoran")

# --- interés: plazo, sector, zona, importe
ok(grupo(lic(fin_plazo="2026-11-01 11:59")) is None, "plazo cerrado: no sale")
ok(grupo(lic(fin_plazo="2026-11-01 12:30")) is not None, "plazo abierto aunque cierre hoy: sale")
r = E.evaluar(lic(fin_plazo="2026-11-02 10:00"), perfil(), AHORA)
ok(any("menos de 2 días" in a for a in r[0]["avisos"]), "cierra pronto: aviso")
ok(grupo(lic(cpvs=["72000000"], cpv="72000000")) is None, "otro sector: no sale")
ok(grupo(lic(nuts="ES618", provincia="sevilla")) is None, "otra provincia: no sale")
ok(grupo(lic(nuts="ES618", provincia="sevilla"), perfil(ambito=["toda"])) is not None, "toda España: sale")
ok(grupo(lic(), perfil(importe_min=["200000"])) is None, "por debajo del importe mínimo: no sale")
ok(grupo(lic(), perfil(importe_max=["50000"])) is None, "por encima del importe máximo: no sale")
ok(grupo(lic(), perfil(importe_min=["50000"], importe_max=["100000"])) is not None, "dentro del rango: sale")

# --- solvencia económica (art. 87.3.a): exigida = 1,5 x VAM
ok(grupo(lic(presupuesto=90_000)) == E.ENCAJA, "VAM 90k -> exige 135k, tramo 150-300k: encaja")
ok(grupo(lic(presupuesto=150_000)) == E.CONDICIONES, "VAM 150k -> exige 225k, dentro del tramo: con condiciones")
r = E.evaluar(lic(presupuesto=250_000), perfil(), AHORA)[0]
ok(r["grupo"] == E.CONDICIONES and not r["fuera"] and "revise la solvencia" in r["condiciones"][0],
   "VAM 250k, tope legal 375k > 300k pero el anuncio no da la cifra: con condiciones, «revise la solvencia»")
ok(grupo(lic(presupuesto=250_000, req={"umbral_eco": 375_000})) == E.FUERA,
   "la misma con 375k en el anuncio: fuera de alcance")
ok(grupo(lic(presupuesto=500_000, duracion_meses=60)) == E.ENCAJA, "500k en 5 años: VAM 100k, exige 150k: encaja")
ok(grupo(lic(presupuesto=250_000, req={"umbral_eco": 100_000})) == E.ENCAJA, "umbral del anuncio 100k < 150k: encaja")
ok(grupo(lic(presupuesto=50_000, req={"umbral_eco": 400_000})) == E.FUERA, "umbral del anuncio 400k > 300k: fuera")
ok(grupo(lic(presupuesto=59_000, valor_estimado=59_000, procedimiento="9"), perfil(facturacion=["<60k"])) == E.ENCAJA,
   "sumario: no se pide solvencia")

# --- clasificación en obras >= 500.000 (art. 77)
obra = dict(cpvs=["45233000"], cpv="45233000", tipo="3", presupuesto=600_000, valor_estimado=600_000,
            duracion_meses=12)
pc = dict(cpv=["45"], facturacion=["1,5M-3M"], trabajadores=["11-25"])
r = E.evaluar(lic(**obra), perfil(**pc), AHORA)[0]
ok(r["grupo"] == E.CONDICIONES and any("Requiere clasificación" in c for c in r["condiciones"]),
   "obra de 600k sin clasificación: con condiciones «requiere clasificación», no se oculta")
ok(grupo(lic(**dict(obra, req={"clas": ["C2-3"]})), perfil(**pc, clasificacion=["si"], clas_codigos=["C2-4"]))
   == E.ENCAJA, "obra con clasificación pedida C2-3 y la empresa tiene C2-4: encaja")
ok(grupo(lic(**dict(obra, req={"clas": ["G4-3"]})), perfil(**pc, clasificacion=["si"], clas_codigos=["C2-4"]))
   == E.CONDICIONES, "piden G4-3 y tiene C2-4: con condiciones")
r = E.evaluar(lic(**obra), perfil(**pc, clasificacion=["si"]), AHORA)[0]
ok(r["grupo"] == E.CONDICIONES and "compruebe" in r["condiciones"][0], "dice que sí pero sin códigos: compruebe")
ok(grupo(lic(**dict(obra, presupuesto=400_000, valor_estimado=400_000)), perfil(**pc)) == E.ENCAJA,
   "obra de 400k: no hace falta clasificación")
ok(grupo(lic(**dict(obra, presupuesto=30_000_000, valor_estimado=30_000_000)),
         perfil(cpv=["45"], facturacion=["150k-300k"], trabajadores=["1-5"])) == E.CONDICIONES,
   "obra de 30 millones, 5 personas y 300k, sin cifra en el anuncio: con condiciones (revise la solvencia)")
ok(grupo(lic(**dict(obra, presupuesto=30_000_000, valor_estimado=30_000_000, req={"umbral_eco": 45_000_000})),
         perfil(cpv=["45"], facturacion=["150k-300k"], trabajadores=["1-5"])) == E.FUERA,
   "la misma obra con la cifra en el anuncio: fuera de alcance")

# --- trabajadores: solo aviso
r = E.evaluar(lic(presupuesto=90_000), perfil(facturacion=[">10M"], trabajadores=["1-5"]), AHORA)[0]
ok(r["grupo"] == E.ENCAJA, "plantilla pequeña no cambia el grupo")
r = E.evaluar(lic(presupuesto=900_000), perfil(facturacion=[">10M"], trabajadores=["1-5"]), AHORA)[0]
ok(r["grupo"] == E.ENCAJA and any("plantilla puede quedarse corta" in a for a in r["avisos"]),
   "VAM 900k con 5 personas: aviso «puede quedarse corta», sigue encajando")

# --- lotes
lotes = [{"id": "1", "titulo": "Lote pequeño", "presupuesto": 50_000, "cpvs": ["90910000"], "nuts": "ES620"},
         {"id": "2", "titulo": "Lote grande", "presupuesto": 2_000_000, "cpvs": ["90910000"], "nuts": "ES620"}]
res = E.filtrar([lic(presupuesto=2_050_000, valor_estimado=2_050_000, lotes_detalle=lotes)], perfil(), AHORA)
ok(len(res[E.ENCAJA]) == 1 and res[E.ENCAJA][0]["lote"] == "1", "lote pequeño encaja")
ok(len(res[E.CONDICIONES]) == 1 and res[E.CONDICIONES][0]["lote"] == "2" and not res[E.FUERA],
   "lote grande sin cifra en el anuncio: con condiciones")
lotes[1]["req"] = {"umbral_eco": 3_000_000}
res = E.filtrar([lic(presupuesto=2_050_000, valor_estimado=2_050_000, lotes_detalle=lotes)], perfil(), AHORA)
ok(len(res[E.FUERA]) == 1 and res[E.FUERA][0]["lote"] == "2", "lote grande con la cifra en su lote: fuera de alcance")
res = E.filtrar([lic(presupuesto=2_050_000, valor_estimado=2_050_000, lotes_detalle=[dict(l) for l in lotes[:1]]
                     + [{k: v for k, v in lotes[1].items() if k != "req"}], req={"umbral_eco": 3_000_000})],
                perfil(), AHORA)
ok(not res[E.FUERA], "cifra solo del contrato entero (no del lote): no cuenta para el lote, no queda fuera")

# --- orden por fecha límite dentro del grupo
res = E.filtrar([lic(id="B", fin_plazo="2026-11-25 10:00", presupuesto=10_000),
                 lic(id="A", fin_plazo="2026-11-10 10:00", presupuesto=10_000)], perfil(), AHORA)
ok([r["id"] for r in res[E.ENCAJA]] == ["A", "B"], "ordenadas por fecha límite")

# --- página
h = E.responder("GET", {}, lambda: [], AHORA)
ok("Sector de actividad" in h and 'method="post"' in h, "GET: formulario por POST")
h = E.responder("POST", {"cpv": ["90"], "ambito": ["murcia"], "facturacion": ["150k-300k"], "trabajadores": ["1-5"],
                         "clasificacion": ["no"]}, lambda: [lic(titulo="<script>x</script>")], AHORA)
ok("<script>x</script>" not in h and "&lt;script&gt;" in h, "títulos escapados")
ok("encajan con condiciones" in h and 'id="fuera"' in h, "resultado con los tres grupos")

print("FALLOS:", len(fallos))
sys.exit(1 if fallos else 0)
