# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de San Cristóbal de La Laguna (~156.000 hab., Tenerife, Canarias).

Fuente OFICIAL: `aytolalaguna.es/ayuntamiento/presupuestos-y-finanzas/contratos-menores/`, con una página por
año (`.../anteriores/<año o alias>/`) que enlaza tres ficheros XLSX/ODS/PDF -- uno por cada entidad con
contratación propia: Ayuntamiento, OAAM (Organismo Autónomo de Actividades Municipales, deportes/cultura) y
OAD (Organismo Autónomo de Desarrollo, servicios sociales). Se usa el XLSX de cada entidad, con columnas
limpias y CONSISTENTES en los 5 años comprobados (2021-2025): `N. Exp. | Adjudicatario (NIF) | Nombre
adjudicatario | Importe sin IGIC | IGIC | Importe adjudicación | Tipo | Fecha adjudicación | CPV | Objeto`.

**IGIC, no IVA**: Canarias tiene su propio impuesto indirecto (Impuesto General Indirecto Canario) en vez del
IVA peninsular -- se guarda el importe SIN IGIC (misma columna que el resto de fuentes usa para "sin IVA"),
marcado en `_FUENTES_CM_SIN_IVA` de app.py con una nota que aclara que es IGIC.

**Los enlaces NO siguen un patrón de URL único entre años** (2025 usa `Contratos_Menores_Transparencia_<ENT>.
xlsx`, 2023-2024 usan `<ENT>-<año>-web.xlsx`, 2021-2022 usan rutas y nombres distintos otra vez) -- recogidos a
mano navegando cada página anual con un navegador real (curl con user-agent normal no encuentra los enlaces:
la página es una SPA/CMS moderno).

Uso (desde backend/):
    python actualizar_contratos_menores_la_laguna.py

Genera contratos_menores_la_laguna.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_la_laguna)."""
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_la_laguna.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_BASE = "https://www.aytolalaguna.es"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"

# (año, entidad) -> ruta exacta del XLSX (recogidas a mano navegando la web con Playwright, ver docstring)
FICHEROS = {
    (2021, "Ayuntamiento"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                              "contratos-menores-2021/Ayuntamiento-web.xlsx",
    (2021, "OAAM"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                     "contratos-menores-2021/OAAM-web.xlsx",
    (2021, "OAD"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                    "contratos-menores-2021/OAD-web.xlsx",
    (2022, "Ayuntamiento"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                              "contratos-menores-2022/Contratos-menores-Ayuntamiento-2022.xlsx",
    (2022, "OAAM"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                     "contratos-menores-2022/Contratos-menores-OAAM-2022.xlsx",
    (2022, "OAD"): "/CDN/files/ayuntamiento/presupuestos-y-finanzas/contratos-menores/"
                    "contratos-menores-2022/Contratos-menores-OAD-2022.xlsx",
    (2023, "Ayuntamiento"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                              "Contratos-Menores/2023/Ayuntamiento-2023-web.xlsx",
    (2023, "OAAM"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                     "Contratos-Menores/2023/OAAM-2023-web.xlsx",
    (2023, "OAD"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                    "Contratos-Menores/2023/OAD-2023-web.xlsx",
    (2024, "Ayuntamiento"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                              "Contratos-Menores/2024/Ayuntamiento-2024-web.xlsx",
    (2024, "OAAM"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                     "Contratos-Menores/2024/OAAM-2024-web.xlsx",
    (2024, "OAD"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                    "Contratos-Menores/2024/OAD-2024-web.xlsx",
    (2025, "Ayuntamiento"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                              "Contratos-Menores/2025/Contratos_Menores_Transparencia_Ayto.xlsx",
    (2025, "OAAM"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                     "Contratos-Menores/2025/Contratos_Menores_Transparencia_OAAM.xlsx",
    (2025, "OAD"): "/CDN/files/ayuntamiento/.galleries/DOCUMENTOS-Presupuestos-y-Finanzas/"
                    "Contratos-Menores/2025/Contratos_Menores_Transparencia_OAD.xlsx",
}

_NOMBRE_ENTIDAD = {
    "Ayuntamiento": "Ayuntamiento de San Cristóbal de La Laguna",
    "OAAM": "Organismo Autónomo de Actividades Municipales (OAAM) de La Laguna",
    "OAD": "Organismo Autónomo de Desarrollo (OAD) de La Laguna",
}


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _importe(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    t = re.sub(r"[^\d.,]", "", str(valor or ""))
    if not t:
        return 0.0
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return 0.0


def _fecha_iso(valor):
    import datetime
    if isinstance(valor, datetime.datetime):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return ""


def _descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    import openpyxl
    existentes = {}
    for (anio, entidad), ruta in sorted(FICHEROS.items()):
        url = _BASE + ruta
        print(f"Descargando {anio} {entidad}...", flush=True)
        try:
            crudo = _descargar(url)
        except Exception as e:
            print(f"  !! {anio} {entidad}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        try:
            wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
            ws = wb.worksheets[0]
            filas = list(ws.iter_rows(min_row=2, values_only=True))
        except Exception as e:
            print(f"  !! {anio} {entidad}: error leyendo XLSX ({type(e).__name__}: {e})", flush=True)
            continue
        registros = []
        for f in filas:
            if not f or len(f) < 10 or not f[0]:
                continue
            expediente, nif, nombre = f[0], f[1], f[2]
            if not nombre:
                continue
            fecha = _fecha_iso(f[7])
            if not fecha or fecha < MENORES_DESDE_FECHA:
                continue
            registros.append({
                "id":               f"la_laguna::{entidad}::{expediente}",
                "municipio":         "San Cristóbal de La Laguna",
                "provincia":         "santa_cruz_tenerife",
                "fuente":            "la_laguna",
                "organisme":         _NOMBRE_ENTIDAD[entidad],
                "adjudicatari":      _limpiar(nombre),
                "nif":               _limpiar(nif),
                "import_num":        round(_importe(f[3]), 2),
                "data_adjudicacio":  fecha,
                "tipus_contracte":   _limpiar(f[6]),
                "descripcio":        _limpiar(f[9]) if len(f) > 9 else "",
                "codi_cpv":          _limpiar(f[8]) if len(f) > 8 else "",
                "exercici":          fecha[:4],
            })
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio} {entidad}: {len(registros)} contratos en ventana ({len(filas)} filas brutas)", flush=True)

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de San Cristóbal de La Laguna y sus organismos "
                             "autónomos OAAM y OAD (XLSX oficiales del portal de transparencia, un fichero por "
                             "año y entidad, enlaces encontrados navegando con un navegador real). Importe SIN "
                             "IGIC (el impuesto indirecto propio de Canarias, no IVA). Ver "
                             "actualizar_contratos_menores_la_laguna.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
