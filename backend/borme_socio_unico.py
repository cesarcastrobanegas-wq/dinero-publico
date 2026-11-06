# encoding: utf-8
"""Busca en los índices del BORME (borme_actos.db y, si está, borme_actos_historico.db) los actos de socio único y
de unipersonalidad de unas pocas sociedades locales, para decidir si son de un solo ayuntamiento (fase 2 de
cobertura, validación de entidades de César, 2026-10-11).

Pensado para GitHub Actions, con el repositorio PÚBLICO: del socio único solo se imprime el texto cuando es una
administración o una sociedad (Ayuntamiento de X, una S.A...). Si es una persona física u otra cosa, se imprime
"(no se muestra)". No escribe nada.

Uso (desde backend/):  python borme_socio_unico.py [--db borme_actos.db] [--db borme_actos_historico.db]"""
import argparse
import json
import os
import re
import sqlite3
import sys

# (etiqueta, patrón LIKE sobre la denominación normalizada)
SOCIEDADES = [
    ("n88 Actuacions Ambientals Integrals (Gandia)", "ACTUACIONS AMBIENTALS INTEGRALS%"),
    ("n96 Parque Marítimo Santa Cruz", "PARQUE MARITIMO SANTA CRUZ%"),
    ("n176 ARDEPINSA (Belmez)", "AREA DE DESARROLLO DEL POLIGONO INDUSTRIAL SAN ANTONIO%"),
    ("n223 Aguas de Dénia", "AGUAS DE DENIA%"),
    ("n248 BUBULCA (Bollullos Par del Condado)", "BUBULCA%"),
    ("n360 Aguas de los Verdiales", "AGUAS DE LOS VERDIALES%"),
    ("n383 CODEUR (Vera)", "CODEUR S%"),
    ("EMUCESA (Granada)", "%CEMENTERIO%SERVICIOS FUNERARIOS DE GRANADA%"),
]
RE_ACTO = re.compile(r"socio|unipersonal", re.I)
RE_MOSTRABLE = re.compile(
    r"ayuntamiento|ajuntament|concello|diputaci|cabildo|consell|autoridad portuaria|junta de|generalitat|xunta|"
    r"mancomunidad|consorci|gobierno|comunidad aut|sociedad|\bS\.? ?[AL]\.?(U\.?)?\b|\bSA\b|\bSL\b|\bSAU\b|\bSLU\b", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="append")
    args = ap.parse_args()
    aqui = os.path.dirname(os.path.abspath(__file__))
    rutas = args.db or [os.path.join(aqui, "borme_actos.db"), os.path.join(aqui, "borme_actos_historico.db")]
    for ruta in rutas:
        if not os.path.exists(ruta):
            print(f"\n== {os.path.basename(ruta)}: no está ==")
            continue
        db = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        desde, hasta, n = db.execute("SELECT min(fecha), max(fecha), count(*) FROM anuncios").fetchone()
        print(f"\n== {os.path.basename(ruta)}: anuncios del {desde} al {hasta} ({n:,}) ==")
        for etiqueta, patron in SOCIEDADES:
            filas = db.execute("SELECT fecha, actos FROM anuncios WHERE soc_norm LIKE ? ORDER BY fecha", (patron,)).fetchall()
            grafias = db.execute("SELECT count(DISTINCT soc_norm) FROM anuncios WHERE soc_norm LIKE ?", (patron,)).fetchone()[0]
            hallados = []
            for fecha, actos in filas:
                try:
                    a = json.loads(actos)
                except ValueError:
                    continue
                if not isinstance(a, dict):
                    continue
                for acto, texto in a.items():
                    if RE_ACTO.search(str(acto)):
                        texto = str(texto)
                        if acto.lower().startswith("socio") and not RE_MOSTRABLE.search(texto):
                            texto = "(no se muestra)"
                        elif not acto.lower().startswith("socio"):
                            texto = ""
                        hallados.append(f"      {fecha} | {acto}{': ' + texto[:120] if texto else ''}")
            print(f"  {etiqueta}: {len(filas)} anuncios, {grafias} denominaciones | actos de socio único o unipersonalidad: {len(hallados)}")
            for h in hallados:
                print(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
