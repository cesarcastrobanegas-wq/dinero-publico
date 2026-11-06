# encoding: utf-8
"""
Prueba SIN RED de que el repositorio (público) no lleva datos personales ni secretos en el código, las pruebas, las
plantillas, la documentación ni los workflows (06-11-2026). Revisa todos los ficheros de texto que sigue git, salvo
los datos oficiales de cargos públicos y los ficheros de más de 3 MB, y falla si encuentra:

  - un DNI o NIE con la letra de control correcta;
  - un teléfono móvil o fijo español escrito con espacios o con +34 (el teléfono de contacto llega por parámetro);
  - un correo que no sea de Dinero Público, de dominios de ejemplo o de servicios conocidos;
  - una clave o un token (GitHub, Resend, OpenAI, AWS, Slack) o una clave privada.

Los nombres de personas no se pueden detectar con una expresión: eso se revisa a mano (ver la rama
wip/limpieza-privacidad). No imprime nunca el dato encontrado: solo el fichero, la línea y el tipo.

    python backend/sin_datos_personales_prueba.py
"""
import os
import re
import subprocess
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEXTO = (".py", ".yml", ".yaml", ".html", ".md", ".txt", ".po", ".json", ".bat", ".js", ".css", ".gitignore",
         ".gitattributes")
# datos oficiales de cargos públicos y de entidades (nombres de alcaldes y concejales sacados de fuentes oficiales)
DATOS_OFICIALES = {"backend/alcaldes_concejales.json", "backend/sueldos_concejales.json", "backend/hacienda_eell.json"}
MAX_BYTES = 3_000_000
LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
# referencias de expediente de una fuente que, por casualidad, cumplen la letra de control de un DNI
NO_SON_DNI = {"20226433A"}

RE_DNI = re.compile(r"(?<![\w-])(\d{8})[- ]?([A-Z])(?!\w)")
RE_NIE = re.compile(r"(?<![\w-])([XYZ])(\d{7})[- ]?([A-Z])(?!\w)")
RE_TEL = [re.compile(r"(?<![\w.,])\+34[ .]?[6789]\d{2}[ .]?\d{3}[ .]?\d{3}(?![\d.,])"),
          re.compile(r"(?<![\w.,])[6789]\d{2} \d{3} \d{3}(?![\d.,])"),
          re.compile(r"(?<![\w.,])[6789]\d{2} \d{2} \d{2} \d{2}(?![\d.,])")]
RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CORREO_PERMITIDO = re.compile(
    r"(dinero-publico\.com|^x@y\.es$|ejemplo\.(test|com|es|org)|example\.(com|org|net)|\.test$|@test\.|@prueba\.|"
    r"noreply@anthropic\.com|users\.noreply\.github\.com|onboarding@resend\.dev|tudominio|localhost)", re.I)
RE_SECRETO = re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|gho_\w{20,}|re_[A-Za-z0-9]{8,}_[A-Za-z0-9_]{8,}|"
                        r"sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[bp]-[\w-]{10,})|-----BEGIN [A-Z ]*PRIVATE KEY")


def ficheros():
    salida = subprocess.run(["git", "-C", RAIZ, "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout
    for f in salida.splitlines():
        if not f.endswith(TEXTO) or f in DATOS_OFICIALES or f == "backend/sin_datos_personales_prueba.py":  # sus ejemplos
            continue
        ruta = os.path.join(RAIZ, f)
        if os.path.isfile(ruta) and os.path.getsize(ruta) <= MAX_BYTES:
            yield f, ruta


def hallazgos(lineas):
    """[(número de línea, tipo)] sin el dato."""
    out = []
    for i, l in enumerate(lineas, 1):
        for m in RE_DNI.finditer(l):
            if (LETRAS[int(m.group(1)) % 23] == m.group(2) and m.group(1) + m.group(2) not in NO_SON_DNI
                    and int(m.group(1)) >= 100):          # 00000000T, 00000001R...: los de ejemplo de las pruebas
                out.append((i, "DNI"))
        for m in RE_NIE.finditer(l):
            if LETRAS[("XYZ".index(m.group(1)) * 10 ** 7 + int(m.group(2))) % 23] == m.group(3):
                out.append((i, "NIE"))
        for r in RE_TEL:
            for m in r.finditer(l):
                cifras = re.sub(r"\D", "", m.group(0))[-9:]
                if cifras[3:].strip("0"):           # 600 000 000, 968 000 000: de ejemplo
                    out.append((i, "teléfono"))
        for m in RE_CORREO.finditer(l):
            v = m.group(0)
            if not CORREO_PERMITIDO.search(v) and not re.search(r"\.(png|svg|js|css|py|json)$", v):
                out.append((i, "correo"))
        if RE_SECRETO.search(l):
            out.append((i, "clave o token"))
    return out


class Detector(unittest.TestCase):
    def test_detecta_lo_que_debe(self):
        # datos INVENTADOS: 12345678Z es el DNI de ejemplo de toda la vida (letra correcta), el teléfono es de ficción
        lineas = ["dni 12345678Z","nie X0000000T", "tel. 600 123 456", "+34 912345678", "escribe a alguien@correo.es",
                  "token ghp_" + "a" * 30]
        tipos = [t for _, t in hallazgos(lineas)]
        self.assertEqual(tipos, ["DNI", "NIE", "teléfono", "teléfono", "correo", "clave o token"])

    def test_no_salta_con_lo_normal(self):
        lineas = ["NIF 00000000T y 00000001R (de ejemplo)", "Bizum al 600 000 000", "Tel. 968 000 000", "correo=x@y.es",
                  "importe 751.410.000 €", "viewBox=\"0 0 700 642.727\"", "contacto@dinero-publico.com",
                  "x@ejemplo.test", "B12345678", "CPV 45000000", "expediente 20226433A", "2026-11-06T00:00:00Z"]
        self.assertEqual(hallazgos(lineas), [])


class Repositorio(unittest.TestCase):
    def test_ningun_dato_personal_ni_secreto(self):
        malos, n = [], 0
        for f, ruta in ficheros():
            n += 1
            with open(ruta, encoding="utf-8", errors="replace") as fh:
                for linea, tipo in hallazgos(fh.read().split("\n")):
                    malos.append(f"{f}:{linea} ({tipo})")
        print(f"  {n} ficheros revisados", flush=True)
        self.assertEqual(malos, [], "Datos personales o secretos (sin copiar el dato):\n" + "\n".join(malos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
