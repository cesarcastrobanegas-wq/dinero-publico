# encoding: utf-8
"""
Prueba SIN RED de que el repositorio (público) no lleva datos personales ni secretos en el código, las pruebas, las
plantillas, la documentación ni los workflows (06-11-2026). Revisa todos los ficheros de texto que sigue git, salvo
los datos oficiales de cargos públicos y los ficheros de más de 3 MB, y falla si encuentra:

  - un DNI o NIE con la letra de control correcta, salvo los inventados de las pruebas apuntados uno a uno, con su
    origen, en backend/dni_inventados_pruebas.txt (08-11-2026; nunca ficheros ni carpetas enteras);
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
# DNI/NIE inventados de las pruebas (y alguna referencia que cumple la letra por casualidad): lista explícita, valor a
# valor y con su origen, en un único fichero. Nunca se excluyen ficheros ni carpetas enteras.
EXCEPCIONES_FICHERO = os.path.join(RAIZ, "backend", "dni_inventados_pruebas.txt")
RE_EXCEPCION = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])\s+#\s*\S")

RE_DNI = re.compile(r"(?<![\w-])(\d{8})[- ]?([A-Z])(?!\w)")
RE_NIE = re.compile(r"(?<![\w-])([XYZ])(\d{7})[- ]?([A-Z])(?!\w)")
RE_TEL = [re.compile(r"(?<![\w.,])\+34[ .]?[6789]\d{2}[ .]?\d{3}[ .]?\d{3}(?![\d.,])"),
          re.compile(r"(?<![\w.,])[6789]\d{2} \d{3} \d{3}(?![\d.,])"),
          re.compile(r"(?<![\w.,])[6789]\d{2} \d{2} \d{2} \d{2}(?![\d.,])")]
RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CORREO_PERMITIDO = re.compile(
    r"(dinero-publico\.com|^x@y\.es$|ejemplo\.(test|com|es|org)|example\.(com|org|net)|\.test$|@test\.|@prueba\.|"
    r"noreply@anthropic\.com|users\.noreply\.github\.com|onboarding@resend\.dev|tudominio|localhost)", re.I)
def letra_correcta(valor):
    """True si el DNI (8 cifras + letra) o NIE (X/Y/Z + 7 cifras + letra) tiene la letra de control correcta."""
    num = int(valor[:-1]) if valor[0].isdigit() else "XYZ".index(valor[0]) * 10 ** 7 + int(valor[1:-1])
    return LETRAS[num % 23] == valor[-1]


def leer_excepciones(ruta=EXCEPCIONES_FICHERO):
    """{valor} del fichero de excepciones. Falla si una línea no es «VALOR  # de dónde sale» o la letra no cuadra."""
    out = set()
    with open(ruta, encoding="utf-8") as fh:
        for n, linea in enumerate(fh, 1):
            if not linea.strip() or linea.lstrip().startswith("#"):
                continue
            m = RE_EXCEPCION.match(linea.strip())
            if not m or not letra_correcta(m.group(1)):
                raise ValueError(f"{os.path.basename(ruta)}:{n}: tiene que ser «DNI-o-NIE  # de dónde sale», con la "
                                 "letra correcta (si no cumple la letra, no hace falta apuntarlo)")
            out.add(m.group(1))
    return frozenset(out)


EXCEPCIONES = leer_excepciones()

RE_SECRETO = re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|gho_\w{20,}|re_[A-Za-z0-9]{8,}_[A-Za-z0-9_]{8,}|"
                        r"sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[bp]-[\w-]{10,})|-----BEGIN [A-Z ]*PRIVATE KEY")


def ficheros():
    salida = subprocess.run(["git", "-C", RAIZ, "ls-files"], capture_output=True, text=True, encoding="utf-8").stdout
    for f in salida.splitlines():
        if not f.endswith(TEXTO) or f in DATOS_OFICIALES:
            continue
        ruta = os.path.join(RAIZ, f)
        if os.path.isfile(ruta) and os.path.getsize(ruta) <= MAX_BYTES:
            yield f, ruta


def hallazgos(lineas, excepciones=None):
    """[(número de línea, tipo)] sin el dato. excepciones: los valores del fichero de excepciones (por defecto)."""
    excepciones = EXCEPCIONES if excepciones is None else excepciones
    out = []
    for i, l in enumerate(lineas, 1):
        for m in RE_DNI.finditer(l):
            v = m.group(1) + m.group(2)
            if letra_correcta(v) and v not in excepciones and int(m.group(1)) >= 100:  # 00000000T...: de ejemplo
                out.append((i, "DNI"))
        for m in RE_NIE.finditer(l):
            v = m.group(1) + m.group(2) + m.group(3)
            if letra_correcta(v) and v not in excepciones:
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
        # datos INVENTADOS, escritos a trozos para que este fichero no tenga que quedarse fuera de la revisión:
        # 12345678Z es el DNI de ejemplo de toda la vida (letra correcta), el teléfono es de ficción
        lineas = ["dni 12345678Z", "nie X" + "0000000T", "tel. 600 123 " + "456", "+34 " + "912345678",
                  "escribe a alguien@" + "correo.es", "token ghp_" + "a" * 30]
        tipos = [t for _, t in hallazgos(lineas, excepciones=frozenset())]
        self.assertEqual(tipos, ["DNI", "NIE", "teléfono", "teléfono", "correo", "clave o token"])

    def test_excepciones_solo_valor_a_valor(self):
        # lo apuntado en el fichero no salta, en ninguna forma; cualquier otro con la letra correcta, sí
        exc = frozenset({"12345678Z", "X1234567L"})
        self.assertEqual(hallazgos(["12345678Z", "12345678-Z", "12345678 Z", "ES" + "X1234567L"], exc), [])
        otro_dni = "87654321" + LETRAS[87654321 % 23]          # inventado, pero no apuntado
        otro_nie = "Y" + "7654321" + LETRAS[(10 ** 7 + 7654321) % 23]
        self.assertEqual([t for _, t in hallazgos([otro_dni, "tests: " + otro_nie], exc)], ["DNI", "NIE"])

    def test_fichero_de_excepciones(self):
        self.assertTrue({"12345678Z", "X1234567L"} <= EXCEPCIONES, EXCEPCIONES)
        for v in EXCEPCIONES:
            self.assertTrue(letra_correcta(v), v)
        # una línea sin «# de dónde sale» o con la letra mal no vale
        import tempfile
        for malo in ("12345678Z\n", "12345678A   # letra mal\n", "backend/   # una carpeta\n"):
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
                fh.write(malo)
            try:
                with self.assertRaises(ValueError, msg=malo):
                    leer_excepciones(fh.name)
            finally:
                os.unlink(fh.name)

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
