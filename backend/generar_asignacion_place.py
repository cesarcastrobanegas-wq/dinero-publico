"""Fase 2 de cobertura, paso 3: recorre los ZIP mensuales de contratos formales de PLACE (sindicación 643) y calcula,
para cada licitación adjudicada de una entidad local, su destino con asignador_place.AsignadorPlace (jerarquía oficial
y DIR3) frente al que le da hoy el patrón por nombre.

Pensado para GitHub Actions (no para el PC): tarda horas y descarga 62 ZIP. No toca producción ni ninguna base.

Deja en --salida:
  reg/AAAAMM.json.gz        una fila por licitación local adjudicada (órgano, DIR3, jerarquía, destino de hoy). Sin
                            adjudicatarios. Sirve para reanudar: un mes ya hecho no se vuelve a descargar.
  contratos/AAAAMM.json.gz  los contratos completos (formato de la app) de las licitaciones que HOY no van a ningún
                            municipio: los necesitará el paso 4. Llevan adjudicatarios: NO se publican como artefacto.
  asignacion_place.json.gz  resultado: {id de licitación: destino} para las que ganan municipio y para las entidades
                            propias. Solo identificadores, municipios y nombres de entidades públicas.
  asignacion_place_resumen.txt   recuentos (sin adjudicatarios).
  prov/<provincia>.json.gz  paso 4: {"municipios": {municipio: [contratos]}} con los contratos de las licitaciones que
                            GANAN municipio, en el formato de backfill_formales_place_prov (lo aplica la web con
                            _aplicar_backfill_formales_place). Llevan adjudicatarios: NO van en el artefacto en claro.

Se procesa del mes más reciente al más antiguo: de cada licitación vale su estado más reciente.

Uso (desde backend/):
    python generar_asignacion_place.py 202610 202109 --salida ../asignacion_place [--zip-local place_cache] [--minutos 300]"""
import argparse
import collections
import gzip
import json
import os
import sys
import tempfile
import time
import zipfile


def leer(ruta):
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        return json.load(f)


def escribir(ruta, datos):
    tmp = ruta + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ruta)


def meses_atras(desde, hasta):
    a, m = int(desde[:4]), int(desde[4:])
    while f"{a}{m:02d}" >= hasta:
        yield f"{a}{m:02d}"
        m -= 1
        if m == 0:
            a, m = a - 1, 12


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip ya descargados")
    ap.add_argument("--minutos", type=int, default=0, help="no empezar un mes nuevo pasado este tiempo")
    args = ap.parse_args()
    t_ini = time.time()
    salida = os.path.abspath(args.salida)
    zip_local = os.path.abspath(args.zip_local) if args.zip_local else ""
    for d in ("reg", "contratos"):
        os.makedirs(os.path.join(salida, d), exist_ok=True)
    out = sys.stdout

    def log(*a):
        print(*a, file=out, flush=True)

    # `import app` reasigna sys.argv, escribe mucho y, sin esto, abriría la base de producción o saldría a la red.
    tmp = tempfile.mkdtemp(prefix="asignacion_place_")
    os.environ["DATA_DIR"] = tmp
    os.environ["DINERO_HILOS_EN_POST_FORK"] = "1"
    proxies = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY")}
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    sys.stdout = open(os.devnull, "w")
    import app as A
    import actualizar_contratos_menores_place as M
    import asignador_place as AP
    import generar_backfill_nombres_place as G
    sys.stdout = out
    for k, v in proxies.items():                       # la red hace falta para bajar los ZIP
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    G.DESCARGA_PLAZO_S = 7200
    asg = AP.AsignadorPlace(A)
    log(f"app importada ({time.time() - t_ini:.0f} s)")

    ruta_reg = lambda mes: os.path.join(salida, "reg", f"{mes}.json.gz")
    ruta_con = lambda mes: os.path.join(salida, "contratos", f"{mes}.json.gz")
    todos = list(meses_atras(args.desde, args.hasta))
    vistos = set()
    for mes in todos:
        if os.path.exists(ruta_reg(mes)):
            vistos.update(r["id"] for r in leer(ruta_reg(mes)))
    pendientes = [m for m in todos if not os.path.exists(ruta_reg(m))]
    log(f"{len(todos) - len(pendientes)} meses ya hechos ({len(vistos):,} licitaciones); {len(pendientes)} pendientes")

    completo = True
    for mes in pendientes:
        if args.minutos and time.time() - t_ini > args.minutos * 60:
            log(f"fuera de plazo antes de {mes}; al relanzar continúa donde lo dejó.")
            completo = False
            break
        ruta, propio = "", False
        cand = os.path.join(zip_local, f"place_{mes}.zip") if zip_local else ""
        if cand and os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
            ruta = cand
        t0 = time.time()
        if not ruta:
            ruta, estado = G.descargar(mes, os.path.join(tmp, f"place_{mes}.zip"))
            propio = True
            if not ruta or not zipfile.is_zipfile(ruta):
                log(f"{mes}: ZIP no disponible ({estado}); paro. Al relanzar continúa donde lo dejó.")
                completo = False
                break
        t_desc, t0 = time.time() - t0, time.time()
        mb = os.path.getsize(ruta) / 1048576
        regs, contratos, ya = {}, {}, 0
        with zipfile.ZipFile(ruta) as z:
            for nombre in z.namelist():
                x = z.read(nombre).decode("utf-8", "replace")
                for e in x.split("<entry>")[1:]:
                    if "<cac:WinningParty>" not in e:
                        continue
                    e = "<entry>" + e.split("</entry>")[0] + "</entry>"
                    r = M.parsear(e)
                    if not asg.es_local(r):
                        continue
                    if r["id"] in vistos:
                        ya += 1
                        continue
                    prev = regs.get(r["id"])
                    if prev and prev["updated"] > r["updated"]:
                        continue
                    cs = A._entry_to_contratos(e)
                    if not cs:
                        continue
                    act = sorted(set().union(*(asg.por_nombre(c) for c in cs)))
                    regs[r["id"]] = {
                        "id": r["id"], "updated": r["updated"], "organo": r["organo"], "dir3": r["dir3"],
                        "nif_org": r["nif_org"], "ciudad": r["ciudad"], "padres": r["padres"], "fecha": r["fecha"],
                        "cs": [{"organo": c.get("organo", ""), "cp": c.get("cp", "")} for c in cs], "n": len(cs),
                        "imp": round(sum(c["importe_num"] for c in cs if isinstance(c.get("importe_num"), (int, float))), 2),
                        "act": [list(a) for a in act]}
                    if act:
                        contratos.pop(r["id"], None)
                    else:
                        contratos[r["id"]] = cs
                del x
        if propio:
            os.remove(ruta)
        escribir(ruta_con(mes), contratos)
        escribir(ruta_reg(mes), list(regs.values()))       # el registro, lo último: marca el mes como hecho
        vistos.update(regs)
        log(f"{mes}: ZIP de {mb:.0f} MB, descarga {t_desc:.0f} s, lectura {time.time() - t0:.0f} s | +{len(regs):,} licitaciones "
            f"locales adjudicadas ({ya:,} ya vistas en meses posteriores) | hoy sin municipio: {len(contratos):,} | "
            f"acumulado {len(vistos):,} | {(time.time() - t_ini) / 60:.0f} min")

    hechos = [m for m in todos if os.path.exists(ruta_reg(m))]
    if not completo or len(hechos) < len(todos):
        log(f"INCOMPLETO: {len(hechos)} de {len(todos)} meses. No se genera el resultado todavía.")
        return 2

    # ---- resultado: dos pasadas (la segunda, con los órganos aprendidos de la jerarquía) ----
    t0 = time.time()
    regs = [r for m in hechos for r in leer(ruta_reg(m))]
    res = {r["id"]: asg.asignar(r, r["cs"]) for r in regs}
    n_apr = asg.aprender((r, res[r["id"]]) for r in regs)
    segunda = 0
    for r in regs:
        if res[r["id"]]["via"] != "jerarquía oficial":
            nuevo = asg.asignar(r, r["cs"])
            segunda += nuevo != res[r["id"]]
            res[r["id"]] = nuevo
    municipios, entidades = {}, {}
    est = collections.Counter()
    vias, tipos, gana, imp_gana = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
    ents = collections.defaultdict(lambda: [0, 0.0])
    det = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))   # para revisar a mano
    cambian, pierden, sin_destino = collections.Counter(), collections.Counter(), collections.Counter()
    entes = collections.defaultdict(lambda: [0, 0.0])     # entes asignados a un municipio (para revisar a mano)
    for r in regs:
        x, act = res[r["id"]], {tuple(a) for a in r["act"]}
        nuevo = (x["prov"], x["muni"]) if x["destino"] == "municipio" else None
        if nuevo and not x["aplica"]:
            est["de provincias con fuente propia (no se tocan)"] += 1
            continue
        est["licitaciones locales adjudicadas"] += 1
        est["hoy asignadas a un municipio"] += bool(act)
        est["con el asignador nuevo, a un municipio"] += bool(nuevo)
        if nuevo:
            vias[x["via"]] += 1
            if x["via"] == "ente con su municipio en la jerarquía":
                k = ((r["padres"][0] if r["padres"] else r["organo"]).strip(), nuevo[0], nuevo[1])
                entes[k][0] += 1
                entes[k][1] += r["imp"]
            if act == {nuevo}:
                est["mismo municipio"] += 1
            elif act:
                cambian[(r["organo"][:80], str(sorted(act)), f"{nuevo[1]} ({nuevo[0]})", x["via"])] += 1
            else:
                est["ganan municipio"] += 1
                est["contratos que ganan municipio"] += r["n"]
                gana[nuevo] += 1
                imp_gana[nuevo] += r["imp"]
                municipios[r["id"]] = [nuevo[0], nuevo[1], x["via"]]
        elif x["destino"] == "entidad":
            tipos[x["tipo"]] += 1
            ents[(x["tipo"], x["entidad"])][0] += 1
            ents[(x["tipo"], x["entidad"])][1] += r["imp"]
            entidades[r["id"]] = [x["tipo"], x["entidad"], r["dir3"]]
            d = det[(x["tipo"], x["entidad"])]
            for campo, valor in (("organos", r["organo"]), ("jerarquia", " / ".join(r["padres"])), ("ciudad", r["ciudad"]),
                                 ("dir3", r["dir3"]), ("nif", r["nif_org"])):
                if valor:
                    d[campo][valor] += 1
            if act:
                pierden[(r["organo"][:80], str(sorted(act)), x["tipo"])] += 1
        else:
            sin_destino[(r["organo"][:80], " / ".join(r["padres"][:3])[:80])] += 1
            if act:
                pierden[(r["organo"][:80], str(sorted(act)), "sin destino")] += 1
    escribir(os.path.join(salida, "asignacion_place.json.gz"),
             {"generado": time.strftime("%Y-%m-%d"), "meses": sorted(hechos), "municipios": municipios, "entidades": entidades})
    # paso 4: contratos de las que ganan municipio, un fichero por provincia
    por_prov = collections.defaultdict(lambda: collections.defaultdict(list))
    n_con = 0
    for m in hechos:
        for id_lic, cs in leer(ruta_con(m)).items():
            if id_lic in municipios:
                prov, muni_app = municipios[id_lic][:2]
                por_prov[prov][muni_app].extend(cs)
                n_con += len(cs)
    dir_prov = os.path.join(salida, "prov")
    os.makedirs(dir_prov, exist_ok=True)
    for viejo in os.listdir(dir_prov):
        os.remove(os.path.join(dir_prov, viejo))
    for prov, munis in por_prov.items():
        escribir(os.path.join(dir_prov, f"{prov}.json.gz"), {"municipios": munis})
    log(f"paso 4: {n_con:,} contratos de {len(municipios):,} licitaciones en {len(por_prov)} provincias")
    del por_prov
    with open(os.path.join(salida, "asignacion_place_entidades.json"), "w", encoding="utf-8") as f:
        json.dump([{"tipo": k[0], "entidad": k[1], "licitaciones": v[0], "importe": round(v[1], 2),
                    **{campo: [a for a, _ in det[k][campo].most_common(3)] for campo in ("organos", "jerarquia", "ciudad", "dir3", "nif")}}
                   for k, v in sorted(ents.items(), key=lambda kv: -kv[1][0])], f, ensure_ascii=False, indent=0)
    with open(os.path.join(salida, "asignacion_place_entes_municipales.json"), "w", encoding="utf-8") as f:
        json.dump([{"ente": k[0], "provincia": k[1], "municipio": k[2], "licitaciones": v[0], "importe": round(v[1], 2)}
                   for k, v in sorted(entes.items(), key=lambda kv: -kv[1][0])], f, ensure_ascii=False, indent=0)
    with open(os.path.join(salida, "asignacion_place_resumen.txt"), "w", encoding="utf-8") as f:
        w = lambda *a: print(*a, file=f)
        w(f"meses: {hechos[-1]}..{hechos[0]} ({len(hechos)}) | órganos aprendidos: {n_apr:,} | cambian en la segunda pasada: {segunda:,}")
        for k, v in est.items():
            w(f"{v:9,}  {k}")
        w(f"{sum(imp_gana.values()) / 1e6:9,.0f}  M€ de las que ganan municipio, en {len(gana):,} municipios")
        w("\nvía de las asignadas a un municipio:")
        for k, v in vias.most_common():
            w(f"{v:9,}  {k}")
        w("\nentidades propias, por tipo (licitaciones | entidades distintas):")
        for k, v in tipos.most_common():
            w(f"{v:9,}  {k} | {sum(1 for e in ents if e[0] == k):,}")
        w("\nmunicipios que más ganan:")
        for (prov, m), v in gana.most_common(150):
            w(f"{v:9,}  {m} ({prov}) | {imp_gana[(prov, m)] / 1e6:,.1f} M€")
        w(f"\nCAMBIAN de municipio: {sum(cambian.values()):,}")
        for k, v in cambian.most_common(200):
            w(f"{v:9,}  {' | '.join(k)}")
        w(f"\nPIERDEN municipio: {sum(pierden.values()):,}")
        for k, v in pierden.most_common(200):
            w(f"{v:9,}  {' | '.join(k)}")
        w(f"\nSIN DESTINO: {sum(sin_destino.values()):,}")
        for k, v in sin_destino.most_common(200):
            w(f"{v:9,}  {' | '.join(k)}")
    log(f"FIN: {len(regs):,} licitaciones | ganan municipio {len(municipios):,} | entidades propias {len(entidades):,} | cambian "
        f"{sum(cambian.values()):,} | pierden {sum(pierden.values()):,} | sin destino {sum(sin_destino.values()):,} | "
        f"resultado en {time.time() - t0:.0f} s; total {(time.time() - t_ini) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    codigo = main()
    sys.stdout.flush()
    os._exit(codigo)
