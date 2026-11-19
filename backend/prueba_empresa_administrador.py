# encoding: utf-8
"""Prueba del administrador en la ficha de empresa (16-11-2026): las tres reglas de _empresa_administrador y la lista
«nif_sin_confirmar» del fichero del BORME. Sociedades, NIF y personas INVENTADOS; base vacía en una carpeta temporal.

    python backend/prueba_empresa_administrador.py      (proceso pesado: importa la web; de uno en uno, ~2 min)
"""
import json
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def reg(nombre, fuente, sociedad, extinguida=False):
    return {"nombre": nombre, "cargo": "Administrador único", "desde": "20240101", "fuente": fuente,
            "sociedad_borme": sociedad, "extinguida": extinguida}


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="empresa_adm_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
    import app
    import administradores_borme as ab
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    propia = reg("PERSONA INVENTADA UNO", "BORME-A-2024-1-28", "ASEGURADORA INVENTADA SA")
    ajena = reg("PERSONA INVENTADA DOS", "BORME-A-2024-2-28", "CORREDURIA INVENTADA SA")
    grande = reg("PERSONA INVENTADA TRES", "BORME-A-2024-3-28", "ELECTRICA INVENTADA SA")
    cerrada = reg("PERSONA INVENTADA CUATRO", "BORME-A-2024-4-28", "CERRADA INVENTADA SA", extinguida=True)
    adm = {
        "A00000001": propia, "aseguradora inventada sa": propia,
        "B00000002": ajena, "correduria inventada sa": ajena,                     # la ajena tiene su NIF
        "electrica inventada sau": grande, "electrica inventada, s.a.u.": grande, "electrica inventada sa": grande,
        "B00000003": grande,                                                       # errata del NIF de la eléctrica
        "A00000009": cerrada,
    }
    datos = {"generado": "2026-11-16 20:00:00", "periodo": ["20090101", "20261113"], "resumen": {},
             "nif_sin_confirmar": ["W0000001H"], "administradores": adm}
    with open(app.ADMINISTRADORES_BORME_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    app.ADMINISTRADORES_BORME = app._cargar_administradores_borme()
    comprobar(app.ADMINISTRADORES_BORME_META["nif_sin_confirmar"] == frozenset({"W0000001H"}),
              "no se carga nif_sin_confirmar")
    n_de = {"A00000001": 500, "B00000002": 800, "B00000003": 3, "A00000005": 1000, "B00000007": 2}
    cd = lambda x: n_de.get(x, 0)
    fuente = lambda r: r[0] and r[0]["fuente"]
    ea = app._empresa_administrador

    # Regla 1: NIF sin confirmar -> nada, ni por el nombre principal ni por variantes
    r = ea("CORREDURIA INVENTADA SA", "W0000001H", [("CORREDURIA INVENTADA SA", 1), ("ASEGURADORA INVENTADA SA", 99)],
           100, cd)
    comprobar(r == (None, ""), f"regla 1: {fuente(r)}")
    # NIF en el fichero: su registro
    comprobar(fuente(ea("ASEGURADORA INVENTADA SA", "A00000001", [], 500, cd)) == "BORME-A-2024-1-28", "NIF propio")
    comprobar(ea("CERRADA INVENTADA SA", "A00000009", [], 5, cd) == (None, ""), "extinguida con administrador")

    # Regla 2: NIF que no está en el fichero (A00000004), 100 contratos
    v = [("EMPRESA SIN BORME SL", 60), ("CORREDURIA INVENTADA SA", 1), ("ASEGURADORA INVENTADA SA", 39)]
    comprobar(ea("EMPRESA SIN BORME SL", "A00000004", v, 100, cd) == (None, ""),
              "regla 2: variante con menos de la mitad aceptada")
    v = [("ASEGURADORA INVENTADA SA", 50), ("OTRA GRAFIA", 50)]
    comprobar(fuente(ea("OTRA GRAFIA", "A00000004", v, 100, cd)) is None, "regla 2: con la mitad justa... (ver abajo)")
    # la mitad justa vale, pero el registro está asignado a A00000001 con 500 contratos >= 100: regla 3 lo descarta
    v = [("ASEGURADORA INVENTADA SA", 90), ("OTRA", 10)]
    comprobar(ea("ASEGURADORA INVENTADA SA", "A00000004", v, 100, cd) == (None, ""),
              "regla 3: registro de otro NIF con más contratos aceptado (aunque sea el nombre principal)")
    # grafías que llevan al mismo registro se suman (30 + 25 = 55 de 100); su NIF «otro» es una errata con 3
    v = [("ELECTRICA INVENTADA SAU", 30), ("ELECTRICA INVENTADA, S.A.U.", 25), ("RESTO DE NOMBRES", 45)]
    r = ea("RESTO DE NOMBRES", "A00000005", v, 100, cd)
    comprobar(fuente(r) == "BORME-A-2024-3-28" and r[1] == "ELECTRICA INVENTADA SAU",
              f"regla 2: grafías del mismo registro no sumadas o regla 3 sin peso: {r}")
    v = [("ELECTRICA INVENTADA SAU", 30), ("RESTO DE NOMBRES", 70)]
    comprobar(ea("RESTO DE NOMBRES", "A00000005", v, 100, cd) == (None, ""), "regla 2: 30 % aceptado")
    # el nombre principal vale aunque no llegue a la mitad (si la regla 3 no lo descarta)
    v = [("ELECTRICA INVENTADA SA", 10), ("X", 45), ("Y", 45)]
    comprobar(fuente(ea("ELECTRICA INVENTADA SA", "A00000005", v, 100, cd)) == "BORME-A-2024-3-28",
              "regla 2: el nombre principal no vale")
    # Regla 3 sin contratos_de: cualquier otro NIF descarta
    v = [("ELECTRICA INVENTADA SAU", 60), ("Z", 40)]
    comprobar(ea("Z", "A00000005", v, 100) == (None, ""), "regla 3 sin contratos_de")
    # El caso de los ejemplos: una sola variante con el nombre de otra sociedad
    v = [("ASEGURADORA INVENTADA SA", 702), ("CORREDURIA INVENTADA SA", 1)]
    r = ea("ASEGURADORA INVENTADA SA", "W0000002H", v, 703, cd)
    comprobar(r[0] is None or r[0]["fuente"] != "BORME-A-2024-2-28", "una variante ajena da su administrador")

    # Grafías sin forma social y erratas de UNA letra (solo nombres de 15 caracteres o más)
    tel = reg("PERSONA INVENTADA CINCO", "BORME-A-2024-5-28", "TELECOMUNICACIONES INVENTADAS DE ESPAÑA SA")
    app.ADMINISTRADORES_BORME["telecomunicaciones inventadas de espana, s.a."] = tel
    app._BORME_NOMBRES_REG["base"] = app._BORME_NIFS_REG["base"] = None
    v = [("TELECOMUNICACIONES INVENTADAS DE ESPAÑA, S.A.", 30),
         ("TELECOMUNICACIONES INVENTADAS DE ESPAÑA, S.A. SOCIEDAD UNIPERSONAL", 15),     # forma social distinta
         ("TELECOMUNICACIONES INVENTADAS DE ESPEÑA, S.A.U.", 10),                       # una letra
         ("OTROS", 45)]
    r = ea("OTROS", "A00000006", v, 100, cd)
    comprobar(fuente(r) == "BORME-A-2024-5-28", f"grafías y errata no sumadas: {r}")
    v = [("TELECOMUNICACIONES INVENTADAS DE ESPAÑA, S.A.", 30), ("TELECOMUNICACIONES INVENTADAS DE ESPXXA SA", 25),
         ("OTROS", 45)]
    comprobar(ea("OTROS", "A00000006", v, 100, cd) == (None, ""), "errata de dos letras sumada")
    comprobar(app._una_errata("abcdefghijklmnop", "abcdefghijklmnoq") and app._una_errata("abcdef", "abcxdef")
              and app._una_errata("abcdef", "abcdf") and not app._una_errata("abcdef", "abcdef")
              and not app._una_errata("abcdef", "abxdey"), "_una_errata")
    # nombre corto (menos de 15 sin la forma): la errata no cuenta
    corto = reg("PERSONA INVENTADA SEIS", "BORME-A-2024-6-28", "CORTA SA")
    app.ADMINISTRADORES_BORME["corta sa"] = corto
    app._BORME_NOMBRES_REG["base"] = app._BORME_NIFS_REG["base"] = None
    comprobar(ea("OTROS", "A00000008", [("CORTA SA", 40), ("CORTE SA", 20), ("OTROS", 40)], 100, cd) == (None, ""),
              "errata en un nombre corto sumada")
    comprobar(fuente(ea("OTROS", "A00000008", [("CORTA SA", 40), ("Corta, S.L.U.", 20), ("OTROS", 40)], 100, cd))
              == "BORME-A-2024-6-28", "misma clave sin forma social no sumada")

    # NIF enmascarado: el registro de un NIF que encaja con la máscara vale
    comprobar(app._borme_nif_encaja("****0000*", "A00000001") and not app._borme_nif_encaja("****0002*", "A00000001"),
              "máscara")
    # Sin NIF: como antes (cualquier variante)
    r = ea("NOMBRE SUELTO", "", [("NOMBRE SUELTO", 9), ("CORREDURIA INVENTADA SA", 1)], 10, cd)
    comprobar(fuente(r) == "BORME-A-2024-2-28", "sin NIF: ha cambiado")

    # Generador: solo NIF de sociedad, nunca un DNI/NIE
    adj = {"W0000001H": {"nif": "W0000001H"}, "B0000000X": {"nif": "b00000007"}, "12345678Z": {"nif": "12345678Z"},
           "X1234567L": {"nif": "X1234567L"}, "A00000001": {"nif": "A00000001"}}
    sit = {"W0000001H": "NIF sin confirmar (solo por nombre)", "B0000000X": "NIF sin confirmar (solo por nombre)",
           "12345678Z": "NIF sin confirmar (solo por nombre)", "X1234567L": "NIF sin confirmar (solo por nombre)",
           "A00000001": "con administrador"}
    comprobar(ab.nif_sin_confirmar(adj, sit) == ["B00000007", "W0000001H"], f"generador: {ab.nif_sin_confirmar(adj, sit)}")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
