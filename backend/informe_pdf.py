# encoding: utf-8
"""
PDF sencillo para los informes descargables de los planes (2026-11-26). Sin dependencias: producción no tiene
reportlab (ver filtro_licitaciones_informe.py) y no se añade nada a requirements.txt. Texto de verdad (se puede
copiar y buscar), con las fuentes estándar de PDF (Helvetica y Helvetica-Bold, codificación WinAnsi: vale para el
castellano, el catalán, el gallego y el euskera) y enlaces que se pueden pulsar.

Uso:
    d = Documento("Informe de municipio", pie="Dinero Público · datos a 26/11/2026")
    d.titulo("Cehegín"); d.parrafo("..."); d.tabla(["Fecha", "Objeto", "Importe"], filas, [70, 330, 95])
    d.enlace("Fuente: PLACE", "https://...")
    pdf_bytes = d.bytes()
"""
import re
import zlib

A4 = (595.28, 841.89)
MARGEN = 50
_PIE_ALTO = 30

# Anchos (en milésimas del cuerpo) de Helvetica y Helvetica-Bold, caracteres 32-126 (métricas AFM de Adobe).
_W_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
          556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500,
          667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
          556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500,
          722, 500, 500, 500, 334, 260, 334, 584]
_W_NEG = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
          556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556,
          722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333,
          556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556,
          778, 556, 556, 500, 389, 280, 389, 584]
_W_EXTRA = {"€": 556, "«": 556, "»": 556, "·": 278, "—": 1000, "–": 556, "º": 365, "ª": 370, "¿": 611, "¡": 333,
            "‘": 222, "’": 222, "“": 333, "”": 333, "•": 350, "…": 1000, "°": 400}
_SUSTITUTOS = {"→": "->", "←": "<-", "↗": "", "≤": "<=", "≥": ">=", " ": " ",
               " ": " ", " ": " ", "‑": "-", "−": "-"}
_RE_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _limpio(texto):
    """Texto que cabe en WinAnsi: los signos que no existen se cambian o se quitan (emojis, flechas...)."""
    t = _RE_CONTROL.sub("", str(texto or ""))
    for a, b in _SUSTITUTOS.items():
        t = t.replace(a, b)
    return "".join(ch for ch in t if _cabe(ch))


def _cabe(ch):
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _ancho_car(ch, negrita):
    o = ord(ch)
    tabla = _W_NEG if negrita else _W_REG
    if 32 <= o <= 126:
        return tabla[o - 32]
    if ch in _W_EXTRA:
        return _W_EXTRA[ch]
    import unicodedata
    base = unicodedata.normalize("NFD", ch)[0]
    if 32 <= ord(base) <= 126:
        return tabla[ord(base) - 32]
    return 556


def ancho(texto, tam, negrita=False):
    return sum(_ancho_car(c, negrita) for c in texto) * tam / 1000.0


def partir(texto, tam, ancho_max, negrita=False):
    """Líneas que caben en ancho_max (corta por palabras; una palabra más larga que la línea se corta a la fuerza)."""
    lineas = []
    for parrafo in _limpio(texto).split("\n"):
        actual = ""
        for palabra in parrafo.split(" "):
            prueba = palabra if not actual else actual + " " + palabra
            if ancho(prueba, tam, negrita) <= ancho_max:
                actual = prueba
                continue
            if actual:
                lineas.append(actual)
            while ancho(palabra, tam, negrita) > ancho_max:
                corte = len(palabra)
                while corte > 1 and ancho(palabra[:corte], tam, negrita) > ancho_max:
                    corte -= 1
                lineas.append(palabra[:corte])
                palabra = palabra[corte:]
            actual = palabra
        lineas.append(actual)
    return lineas


def _pdf_texto(texto):
    b = texto.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _num(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


class Documento:
    AZUL = (0.106, 0.184, 0.361)           # #1b2f5c, el de la web
    GRIS = (0.42, 0.45, 0.50)
    NEGRO = (0.11, 0.14, 0.20)
    AMARILLO = (0.96, 0.72, 0.0)

    def __init__(self, titulo_doc, pie="", autor="Dinero Público"):
        self.titulo_doc = _limpio(titulo_doc)
        self.autor = _limpio(autor)
        self.pie = _limpio(pie)
        self.paginas = []                   # [(bytes del contenido, [anotaciones])]
        self._nueva_pagina()

    # ── páginas ──
    def _nueva_pagina(self):
        if hasattr(self, "_ops"):
            self.paginas.append((b"\n".join(self._ops), self._links))
        self._ops, self._links = [], []
        self.y = A4[1] - MARGEN

    def _cabe_alto(self, alto):
        if self.y - alto < MARGEN + _PIE_ALTO:
            self._nueva_pagina()

    def _texto(self, x, y, texto, tam, negrita=False, color=None):
        r, g, b = color or self.NEGRO
        self._ops.append(f"BT /{'F2' if negrita else 'F1'} {_num(tam)} Tf {_num(r)} {_num(g)} {_num(b)} rg "
                         f"{_num(x)} {_num(y)} Td (".encode() + _pdf_texto(texto) + b") Tj ET")

    def _linea(self, x1, y1, x2, y2, color=None, grueso=0.5):
        r, g, b = color or (0.85, 0.87, 0.9)
        self._ops.append(f"{_num(r)} {_num(g)} {_num(b)} RG {_num(grueso)} w {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S".encode())

    def _rect(self, x, y, w, h, color):
        r, g, b = color
        self._ops.append(f"{_num(r)} {_num(g)} {_num(b)} rg {_num(x)} {_num(y)} {_num(w)} {_num(h)} re f".encode())

    @property
    def ancho_util(self):
        return A4[0] - 2 * MARGEN

    # ── bloques ──
    def espacio(self, alto=8):
        self.y -= alto

    def titulo(self, texto, tam=20):
        for ln in partir(texto, tam, self.ancho_util, True):
            self._cabe_alto(tam * 1.3)
            self.y -= tam
            self._texto(MARGEN, self.y, ln, tam, True, self.AZUL)
            self.y -= tam * 0.3
        self._rect(MARGEN, self.y - 4, 60, 3, self.AMARILLO)
        self.y -= 14

    def seccion(self, texto, tam=13):
        self._cabe_alto(tam * 3)
        self.y -= 10
        for ln in partir(texto, tam, self.ancho_util, True):
            self.y -= tam
            self._texto(MARGEN, self.y, ln, tam, True, self.AZUL)
            self.y -= tam * 0.35
        self.y -= 4

    def parrafo(self, texto, tam=10, negrita=False, color=None, sangria=0):
        for ln in partir(texto, tam, self.ancho_util - sangria, negrita):
            self._cabe_alto(tam * 1.4)
            self.y -= tam
            self._texto(MARGEN + sangria, self.y, ln, tam, negrita, color)
            self.y -= tam * 0.4
        self.y -= 4

    def nota(self, texto):
        self.parrafo(texto, tam=8.5, color=self.GRIS)

    def enlace(self, texto, url, tam=9.5):
        """Una línea de texto que lleva a `url` al pulsarla (y la dirección escrita, por si se imprime)."""
        url = _limpio(url)
        lineas = partir(f"{texto}: {url}" if texto else url, tam, self.ancho_util)
        for ln in lineas:
            self._cabe_alto(tam * 1.4)
            self.y -= tam
            self._texto(MARGEN, self.y, ln, tam, False, self.AZUL)
            self._links.append((MARGEN, self.y - 2, MARGEN + ancho(ln, tam), self.y + tam, url))
            self.y -= tam * 0.4
        self.y -= 3

    def datos(self, pares, tam=10):
        """Lista «etiqueta: valor» en dos columnas."""
        col = 170
        for etiqueta, valor in pares:
            lv = partir(valor, tam, self.ancho_util - col)
            self._cabe_alto(tam * 1.4 * len(lv))
            self.y -= tam
            self._texto(MARGEN, self.y, _limpio(etiqueta), tam, True, self.GRIS)
            for i, ln in enumerate(lv):
                if i:
                    self.y -= tam * 1.35
                self._texto(MARGEN + col, self.y, ln, tam)
            self.y -= tam * 0.45
        self.y -= 4

    def tabla(self, cabecera, filas, anchos, derecha=(), tam=8.5, enlaces=None):
        """Tabla con cabecera que se repite en cada página. `derecha`: índices de columna alineados a la derecha.
        `enlaces`: lista paralela a `filas` con la URL de cada fila ("" si no tiene): se puede pulsar la fila."""
        total = sum(anchos)
        escala = self.ancho_util / total if total > self.ancho_util else 1
        anchos = [a * escala for a in anchos]
        pad = 3

        def _fila(celdas, negrita, fondo=None, url=""):
            partes = [partir(str(c), tam, w - 2 * pad, negrita) for c, w in zip(celdas, anchos)]
            alto = max(len(p) for p in partes) * tam * 1.25 + 2 * pad
            if self.y - alto < MARGEN + _PIE_ALTO:
                self._nueva_pagina()
                if not negrita:
                    _fila(cabecera, True, (0.93, 0.95, 0.98))
            if fondo:
                self._rect(MARGEN, self.y - alto, sum(anchos), alto, fondo)
            x = MARGEN
            for i, (p, w) in enumerate(zip(partes, anchos)):
                yy = self.y - pad - tam
                for ln in p:
                    xx = x + w - pad - ancho(ln, tam, negrita) if i in derecha else x + pad
                    self._texto(xx, yy, ln, tam, negrita, self.AZUL if negrita else None)
                    yy -= tam * 1.25
                x += w
            if url:
                self._links.append((MARGEN, self.y - alto, MARGEN + sum(anchos), self.y, _limpio(url)))
            self.y -= alto
            self._linea(MARGEN, self.y, MARGEN + sum(anchos), self.y)
        self._cabe_alto(tam * 6)
        _fila(cabecera, True, (0.93, 0.95, 0.98))
        for n, f in enumerate(filas):
            _fila(f, False, url=(enlaces[n] if enlaces else ""))
        self.y -= 8

    # ── salida ──
    def bytes(self):
        self.paginas.append((b"\n".join(self._ops), self._links))
        self._ops, self._links = [], []
        paginas, self.paginas = self.paginas, []
        n = len(paginas)
        objetos = {}
        # 1 catálogo, 2 páginas, 3 F1, 4 F2, 5 info; luego por página: página, contenido y sus enlaces
        sig = 6
        kids = []
        for i, (contenido, links) in enumerate(paginas):
            pie = b""
            if self.pie or n > 1:
                texto_pie = f"{self.pie}  ·  {i + 1}/{n}" if self.pie else f"{i + 1}/{n}"
                pie = (f"BT /F1 7.5 Tf {_num(self.GRIS[0])} {_num(self.GRIS[1])} {_num(self.GRIS[2])} rg "
                       f"{_num(MARGEN)} {_num(MARGEN - 18)} Td (").encode() + _pdf_texto(texto_pie) + b") Tj ET"
            datos = zlib.compress(contenido + b"\n" + pie)
            num_pag, num_cont = sig, sig + 1
            sig += 2
            annots = []
            for (x1, y1, x2, y2, url) in links:
                objetos[sig] = (f"<< /Type /Annot /Subtype /Link /Rect [{_num(x1)} {_num(y1)} {_num(x2)} {_num(y2)}] "
                                f"/Border [0 0 0] /A << /S /URI /URI (").encode() + _pdf_texto(url) + b") >> >>"
                annots.append(sig)
                sig += 1
            objetos[num_cont] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(datos) + datos + b"\nendstream"
            anot = (" /Annots [" + " ".join(f"{a} 0 R" for a in annots) + "]") if annots else ""
            objetos[num_pag] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(A4[0])} {_num(A4[1])}] "
                                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {num_cont} 0 R{anot} >>").encode()
            kids.append(num_pag)
        objetos[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
        objetos[2] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {n} >>".encode()
        objetos[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        objetos[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        objetos[5] = b"<< /Title (" + _pdf_texto(self.titulo_doc) + b") /Producer (" + _pdf_texto(self.autor) + b") >>"
        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posiciones = {}
        for num in sorted(objetos):
            posiciones[num] = len(salida)
            salida += f"{num} 0 obj\n".encode() + objetos[num] + b"\nendobj\n"
        xref = len(salida)
        total = max(objetos) + 1
        salida += f"xref\n0 {total}\n0000000000 65535 f \n".encode()
        for num in range(1, total):
            salida += f"{posiciones[num]:010d} 00000 n \n".encode()
        salida += f"trailer\n<< /Size {total} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(salida)
