"""Genera backend/ine_municipios.json: código INE de 5 cifras -> [provincia de la app, municipio de la app], a partir
de la relación oficial de municipios del INE (https://www.ine.es/daco/daco42/codmun/diccionario26.xlsx).

Lo usa asignador_place.py para asignar las licitaciones de PLACE por el código del órgano (DIR3 L01<INE> o NIF
P<INE>00) en vez de por su nombre. Se regenera a mano si cambia la lista de municipios (fusiones, segregaciones).

Uso (desde backend/):  python generar_ine_municipios.py RUTA/diccionario26.xlsx"""
import json
import os
import sys

PROVINCIAS_INE = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz", "07": "Baleares",
    "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real",
    "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara",
    "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida", "26": "La Rioja",
    "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia", "31": "Navarra", "32": "Ourense", "33": "Asturias",
    "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra", "37": "Salamanca", "38": "Santa Cruz de Tenerife",
    "39": "Cantabria", "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo",
    "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla"}


# Municipios que el INE nombra distinto que las listas de la app (comprobados a mano, 2026-10-10).
MANUAL = {"08023": ("barcelona", "Bigues i Riells"), "09023": ("burgos", "Arcos de la Llana"),
          "27002": ("lugo", "Alfoz do Castrodouro"), "49178": ("zamora", "Roales del Pan"),
          "01055": ("pais_vasco", "Valdegovia-Gaubea"), "20050": ("pais_vasco", "Leaburu-Txarama"),
          "20065": ("pais_vasco", "Soraluze"), "48001": ("pais_vasco", "la Anteiglesia de Abadiño"),
          "48002": ("pais_vasco", "Abanto Zierbena"), "48914": ("pais_vasco", "Arrazu"),
          "48902": ("pais_vasco", "la Anteiglesia de Erandio"), "48022": ("pais_vasco", "Carranza"),
          "48087": ("pais_vasco", "Trucíos")}


def main():
    import openpyxl
    aqui = os.path.dirname(os.path.abspath(__file__))
    salida = os.path.join(aqui, "ine_municipios.json")
    registro = open(os.path.join(aqui, "ine_municipios.log"), "w", encoding="utf-8")
    filas = []
    for r in openpyxl.load_workbook(sys.argv[1], read_only=True).active.iter_rows(values_only=True):
        if not r or r[1] is None or r[2] is None or not str(r[1]).strip().isdigit():
            continue
        cpro, cmun = str(r[1]).strip().zfill(2), str(r[2]).strip().zfill(3)
        if cpro in PROVINCIAS_INE:
            filas.append((r[0], cpro, cmun, r[3], str(r[4]).strip()))
    sys.stdout = open(os.devnull, "w")          # `import app` escribe mucho al arrancar
    os.environ.setdefault("DINERO_HILOS_EN_POST_FORK", "1")
    import app as A
    import actualizar_contratos_menores_place as M
    asg = M.Asignador(A)
    out, sin, sin_prov = {}, [], set()
    for _, cpro, cmun, _dc, nombre in filas:
        prov = asg.provincia(PROVINCIAS_INE[cpro])
        if not prov:
            sin_prov.add(PROVINCIAS_INE[cpro])
            continue
        m = MANUAL[cpro + cmun][1] if cpro + cmun in MANUAL else asg.nombre_a_municipio(nombre, prov)
        if m:
            out[cpro + cmun] = [prov, m]
        else:
            sin.append(f"{cpro}{cmun} {nombre} ({prov})")
    json.dump({"fuente": "INE, relación de municipios a 1 de enero de 2026", "municipios": out},
              open(salida, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    destinos = {tuple(v) for v in out.values()}
    en_app = {(p, m) for p, lst in A.MUNICIPIOS_POR_PROVINCIA.items() for m in lst}
    print(f"municipios del INE: {len(filas)} | con municipio de la app: {len(out)} | sin casar: {len(sin)} | provincias sin "
          f"clave: {sorted(sin_prov)}", file=registro)
    print(f"municipios de la app: {len(en_app)} | con código INE: {len(destinos & en_app)} | dos códigos para el mismo "
          f"municipio: {len(out) - len(destinos)}", file=registro)
    print("sin casar:", "; ".join(sin[:80]), file=registro)
    print("municipios de la app sin código:", "; ".join(f"{m} ({p})" for p, m in sorted(en_app - destinos)[:80]), file=registro)
    registro.close()
    os._exit(0)


if __name__ == "__main__":
    main()
