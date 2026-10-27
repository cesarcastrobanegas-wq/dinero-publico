# encoding: utf-8
"""
Prueba del motor del filtro de licitaciones (fase 1) con tres perfiles INVENTADOS: ni formulario ni empresas reales.

Lee uno o varios ZIP mensuales de PLACE, se queda con la última versión de cada entrada, pasa cada licitación por el
mismo camino que la tabla (requisitos_json -> desde_fila) y clasifica las abiertas para cada perfil.

Uso:  python backend/filtro_licitaciones_prueba.py place_202609.zip place_202610.zip
No toca la base de datos ni la web.
"""
import os
import sys
import zipfile
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filtro_licitaciones as F            # noqa: E402
import licitaciones_place as LIC           # noqa: E402

PERFILES = {
    "Limpieza, 5 personas, Murcia": {
        "cpvs": ["909"], "provincias": ["murcia"], "trabajadores": 5, "facturacion": "150k-300k",
        "clasificacion": [], "ute": True, "experiencia_publica": False, "certificados": ["ISO9001"],
        "tipos": ["servicios"], "anio_constitucion": 2012,
    },
    "Constructora, 40 personas, clasificada": {
        "cpvs": ["45"], "provincias": ["murcia", "alicante", "albacete", "almeria"], "trabajadores": 40,
        "facturacion": "3M-10M", "clasificacion": ["C2-4", "C4-3", "C6-3", "G4-3", "G6-4", "E1-3", "I9-2"],
        "ute": True, "experiencia_publica": True, "certificados": ["ISO9001", "ISO14001", "ISO45001"],
        "tipos": ["obras"], "anio_constitucion": 1998,
    },
    "Consultora informática, 2 personas": {
        "cpvs": ["72", "48"], "provincias": ["murcia", "madrid", "alicante", "valencia"], "trabajadores": 2,
        "facturacion": "60k-150k", "clasificacion": [], "ute": False, "experiencia_publica": False,
        "certificados": ["ENS"], "tipos": ["servicios"], "anio_constitucion": 2023,
    },
}


def cargar(zips):
    ultimas = {}
    for ruta in zips:
        with zipfile.ZipFile(ruta) as z:
            for nombre in sorted(x for x in z.namelist() if x.endswith(".atom")):
                raw = z.read(nombre)
                for e in LIC.entradas(raw):
                    r = LIC.analizar_entrada(e)
                    if r and (r["id"] not in ultimas or r["actualizado"] >= ultimas[r["id"]]["actualizado"]):
                        ultimas[r["id"]] = r
                for ref, cuando in LIC.borradas(raw):
                    if ref not in ultimas or cuando >= ultimas[ref]["actualizado"]:
                        ultimas[ref] = {"id": ref, "actualizado": cuando, "estado": "BORRADA"}
                del raw
    filas = []
    for r in ultimas.values():
        if r["estado"] not in LIC.ESTADOS_ABIERTOS:
            continue
        # el mismo camino que la tabla: columnas + requisitos en JSON
        fila = {k: r.get(k) for k in ("id", "fin_plazo", "titulo", "url", "organo", "ambito", "provincia", "cpv",
                                      "tipo", "procedimiento", "presupuesto", "valor_estimado")}
        fila["requisitos"] = LIC.requisitos_json(r)
        filas.append(F.desde_fila(fila))
    return filas


def main():
    ahora = datetime.now()
    filas = cargar(sys.argv[1:])
    abiertas = [f for f in filas if (f.get("fin_plazo") or "") >= ahora.strftime("%Y-%m-%d %H:%M")]
    print(f"Licitaciones en PUB: {len(filas)}; con plazo abierto ahora: {len(abiertas)}")
    print(f"  con lotes: {sum(1 for f in abiertas if f.get('lotes_detalle'))}; "
          f"con duración: {sum(1 for f in abiertas if f.get('duracion_meses'))}; "
          f"con clasificación: {sum(1 for f in abiertas if (f.get('req') or {}).get('clas'))}; "
          f"con importe de solvencia: {sum(1 for f in abiertas if (f.get('req') or {}).get('umbral_eco'))}")
    for nombre, perfil in PERFILES.items():
        errores = F.validar_perfil(perfil, ahora)
        if errores:
            sys.exit(f"Perfil «{nombre}» no válido: {errores}")
        res = F.filtrar(abiertas, perfil, ahora)
        print(f"\n=== {nombre} ===")
        nuevas = [r for g in F.GRUPOS for r in res[g] if any("nueva creación" in m for m in r["motivos"])]
        if nuevas:
            print(f"  con motivo de nueva creación: {len(nuevas)} "
                  f"({sum(1 for r in nuevas if r['grupo'] == F.PUEDE)} en PUEDE OPTAR)")
            for r in nuevas[:2]:
                print(f"   - [{r['grupo']}] {r['titulo'][:80]} | {r['importe']:,.0f} EUR | "
                      f"{'; '.join(r['motivos'])}")
        for g in F.GRUPOS + (F.DESCARTADA,):
            lic = len({r["id"] for r in res[g]})
            lotes = sum(1 for r in res[g] if r["lote"])
            sumarios = sum(1 for r in res[g] if r["sumario"])
            print(f"  {g:26s} {len(res[g]):4d} resultados ({lic} licitaciones, {lotes} lotes, {sumarios} sumarios)")
        for g in F.GRUPOS:
            vistos, ejemplos = set(), []
            for r in sorted(res[g], key=lambda r: (not r["sumario"], not r["lote"], r["fin_plazo"])):
                if r["id"] not in vistos:
                    vistos.add(r["id"])
                    ejemplos.append(r)
            # tres ejemplos variados: un sumario si lo hay, un lote si lo hay, y el que cierre antes
            elegidos = []
            for criterio in (lambda r: r["sumario"], lambda r: r["lote"], lambda r: True):
                for r in ejemplos:
                    if criterio(r) and r not in elegidos:
                        elegidos.append(r)
                        break
            for r in ejemplos:
                if len(elegidos) >= 3:
                    break
                if r not in elegidos:
                    elegidos.append(r)
            print(f"\n  -- {g}: ejemplos")
            for r in elegidos[:3]:
                lote = f" | LOTE {r['lote']}: {(r['titulo_lote'] or '')[:60]}" if r["lote"] else ""
                print(f"   * {r['titulo'][:90]}{lote}")
                print(f"     {r['organo'][:70]} | {r['provincia'] or 'sin provincia'} | cierra {r['fin_plazo']} | "
                      f"importe {r['importe']:,.0f} EUR | VAM {r['vam']:,.0f} | "
                      f"{'SUMARIO' if r['sumario'] else 'solvencia ' + format(r['solvencia_exigida'], ',')}")
                print(f"     motivos: {'; '.join(r['motivos'])}")
                print(f"     {r['url']}")


if __name__ == "__main__":
    main()
