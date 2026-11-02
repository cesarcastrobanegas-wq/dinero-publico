# encoding: utf-8
"""
Embudo de licitaciones (/licitaciones/filtro), encargo nocturno de César del 2026-11-01: una empresa rellena un
formulario corto y ve SOLO las licitaciones abiertas a las que de verdad puede optar ("no podemos ofrecer una licitación
de 30 millones a una empresa con 5 trabajadores").

Diferencias con el filtro del PR #6 (filtro_formulario.py, perfiles guardados en socios.db y correo semanal):
- Aquí NO se guarda nada: el formulario va por POST, la respuesta se calcula con lo que viene en la petición y se
  olvida. Sin cookies, sin socios.db, sin correo. Cache-Control: no-store.
- Seis preguntas y tres grupos de resultado: ENCAJA / ENCAJA CON CONDICIONES / FUERA DE ALCANCE.
- Reutiliza las piezas del motor (filtro_licitaciones.py): lotes uno a uno, lugar por NUTS/CP, clasificación, sumario
  y la columna `requisitos` de la tabla `licitaciones` (la misma de /convocatorias y de las alertas).

Criterios (la página los explica en lenguaje llano, ver CRITERIOS_HTML):
1. Interés de la empresa (lo que no encaja aquí ni se cuenta como "fuera de alcance"; se dice cuántas son): plazo de
   presentación abierto, sector (división CPV de 2 cifras de alguno de los CPV del contrato o del lote), ámbito
   (provincia o comunidad del lugar de ejecución; "toda España" lo admite todo) y rango de importe (si lo pone).
2. Solvencia económica (art. 87.3.a LCSP): el órgano puede pedir como mucho una facturación anual de 1,5 veces el valor
   anual medio (VAM) del contrato. VAM = presupuesto sin IVA del lote o del contrato / duración en años (mínimo 1).
   Si el anuncio trae la cifra exigida (ThresholdQuantity), manda esa. Facturación por tramos: si el límite bajo del
   tramo ya llega -> encaja; en medio -> CON CONDICIONES. Si ni el límite alto llega: FUERA DE ALCANCE solo cuando la
   cifra viene del anuncio ("El anuncio exige X €"); si es el tope legal calculado por nosotros, CON CONDICIONES (el
   pliego puede pedir menos), salvo que no llegue ni a la mitad del tope (0,75 x VAM): FUERA DE ALCANCE con la
   etiqueta "Desproporcionado (estimación nuestra)" (decisiones de César, 02-11-2026). Abierto
   simplificado sumario (art. 159.6 LCSP) no pide solvencia. Clasificación que cubre la exigida sustituye a la
   solvencia.
3. Obras de valor estimado >= 500.000 EUR (art. 77.1.a LCSP): sin clasificación -> CON CONDICIONES "requiere
   clasificación"; nunca se ocultan por esto solo.
4. Trabajadores: solo un aviso orientativo ("su plantilla puede quedarse corta") si el VAM pasa de 100.000 EUR por
   persona del límite alto de su tramo. No cambia el grupo.
5. Orden: ENCAJA, CON CONDICIONES, FUERA DE ALCANCE; dentro de cada grupo por fecha límite.
Lo que no se puede aplicar por falta de datos está en el informe (INFORME_FILTRO_LICITACIONES.md), no inventado.
"""
import html
import re
from datetime import datetime

try:
    from . import filtro_licitaciones as F
    from . import licitaciones_place as LIC
except ImportError:
    import filtro_licitaciones as F
    import licitaciones_place as LIC

RUTA = "/licitaciones/filtro"
ENCAJA = "ENCAJA"
CONDICIONES = "ENCAJA CON CONDICIONES"
FUERA = "FUERA DE ALCANCE"
GRUPOS = (ENCAJA, CONDICIONES, FUERA)
MAX_FICHAS = 60                          # por grupo en la página (las demás se cuentan)
DIAS_AVISO_CIERRE = 2                    # "cierra pronto" si quedan menos de estos días
# Sin cifra en el anuncio: fuera de alcance si la facturación no llega ni a la mitad del máximo legal (0,75 x VAM)
FACTOR_DESPROPORCION = F.FACTOR_SOLVENCIA / 2
DESPROPORCIONADO = "Desproporcionado (estimación nuestra)"

# Tramos de facturación: los mismos cortes que el motor (60.000 es el del sumario)
TRAMOS_FACTURACION = F.TRAMOS_FACTURACION
TRAMOS_FACTURACION_TEXTO = F.TRAMOS_TEXTO
# Tramos de plantilla (personas): (límite bajo, límite alto)
TRAMOS_TRABAJADORES = {
    "1-5": (1, 5), "6-10": (6, 10), "11-25": (11, 25), "26-50": (26, 50), "51-250": (51, 250),
    ">250": (251, float("inf")),
}
TRAMOS_TRABAJADORES_TEXTO = {
    "1-5": "de 1 a 5 personas", "6-10": "de 6 a 10", "11-25": "de 11 a 25", "26-50": "de 26 a 50",
    "51-250": "de 51 a 250", ">250": "más de 250",
}
TODA_ESPANA = "toda"

# comunidad de la app -> sus provincias (de las tablas NUTS del lector de PLACE)
PROVINCIAS_DE_COMUNIDAD = {}
for _n, _p in LIC.NUTS_PROVINCIA.items():
    _c = LIC.NUTS_COMUNIDAD.get(_n[:4])
    if _c:
        PROVINCIAS_DE_COMUNIDAD.setdefault(_c, set()).add(_p)
PROVINCIAS_DE_COMUNIDAD = {c: sorted(ps, key=lambda p: F.NOMBRE_PROVINCIA.get(p, p))
                           for c, ps in PROVINCIAS_DE_COMUNIDAD.items()}
COMUNIDADES_ORDEN = sorted(PROVINCIAS_DE_COMUNIDAD, key=lambda c: F.NOMBRE_COMUNIDAD.get(c, c))
TODAS_PROVINCIAS = sorted({p for ps in PROVINCIAS_DE_COMUNIDAD.values() for p in ps})


# ─── lectura del formulario ─────────────────────────────────────────────────────────────────────────────────────
def _lista(params, nombre):
    return [v.strip() for v in params.get(nombre, []) if v and v.strip()]


def _uno(params, nombre):
    v = _lista(params, nombre)
    return v[0] if v else ""


def _euros(txt):
    """"1.500.000" / "1500000" / "1,5" -> float; "" -> None; texto raro -> ValueError."""
    t = re.sub(r"[\s€]", "", txt or "")
    if not t:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):        # formato español con puntos de miles
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    v = float(t)
    if v < 0:
        raise ValueError
    return v


def leer(params):
    """(perfil, errores) a partir de los parámetros del envío (dict de listas, como parse_qs). El perfil solo vive
    durante la petición."""
    err = []
    divisiones = [d for d in _lista(params, "cpv") if d in LIC.CPV_DIVISIONES]
    if not divisiones:
        err.append("Sector: marca al menos un sector de actividad.")
    ambito = _lista(params, "ambito")
    toda = TODA_ESPANA in ambito
    provincias = set()
    for a in ambito:
        if a in PROVINCIAS_DE_COMUNIDAD:
            provincias.update(PROVINCIAS_DE_COMUNIDAD[a])
        elif a.startswith("p:") and a[2:] in TODAS_PROVINCIAS:
            provincias.add(a[2:])
    if toda:
        provincias = set(TODAS_PROVINCIAS)
    if not provincias:
        err.append("Ámbito: marca «Toda España» o al menos una comunidad o provincia.")
    facturacion = _uno(params, "facturacion")
    if facturacion not in TRAMOS_FACTURACION:
        err.append("Facturación: elige un tramo.")
    trabajadores = _uno(params, "trabajadores")
    if trabajadores not in TRAMOS_TRABAJADORES:
        err.append("Trabajadores: elige un tramo.")
    tiene_clas = _uno(params, "clasificacion") == "si"
    codigos = [c for c in re.split(r"[\s,;]+", _uno(params, "clas_codigos").upper()) if c]
    if not tiene_clas:
        codigos = []
    malos = [c for c in codigos if not (F._clas(c) and F._clas(c)[2])]
    if malos:
        err.append("Clasificación: escribe cada una como grupo, subgrupo y categoría, por ejemplo C2-4 "
                   f"(no se entiende: {', '.join(malos[:3])}).")
    imp_min = imp_max = None
    try:
        imp_min = _euros(_uno(params, "importe_min"))
        imp_max = _euros(_uno(params, "importe_max"))
    except ValueError:
        err.append("Importe: escribe solo cifras en euros (por ejemplo 50000).")
    if imp_min is not None and imp_max is not None and imp_min > imp_max:
        err.append("Importe: el mínimo es mayor que el máximo.")
    perfil = {
        "divisiones": divisiones, "toda_espana": toda, "provincias": sorted(provincias),
        "ambito_marcado": ambito, "facturacion": facturacion, "trabajadores": trabajadores,
        "tiene_clasificacion": tiene_clas, "clasificacion": codigos,
        "importe_min": imp_min, "importe_max": imp_max,
    }
    return perfil, err


# ─── evaluación ─────────────────────────────────────────────────────────────────────────────────────────────────
def _perfil_motor(perfil):
    """El perfil en la forma que esperan las piezas del motor (_lugar)."""
    return {"provincias": perfil["provincias"], "incluir_sin_provincia": True}


def evaluar(lic, perfil, ahora):
    """Lista de resultados de una licitación (uno por lote o por contrato) que entran en el interés de la empresa
    (plazo, sector, ámbito e importe), cada uno con grupo, condiciones y avisos. Vacía si no le interesa."""
    fin = lic.get("fin_plazo") or ""
    if not fin or fin < ahora.strftime("%Y-%m-%d %H:%M"):
        return []
    prefijos = perfil["divisiones"]
    pm = _perfil_motor(perfil)
    lo_f, hi_f = TRAMOS_FACTURACION[perfil["facturacion"]]
    hi_t = TRAMOS_TRABAJADORES[perfil["trabajadores"]][1]
    perfil_clas = [c for c in map(F._clas, perfil["clasificacion"]) if c]
    ve = lic.get("valor_estimado") or lic.get("presupuesto") or 0
    tipo = lic.get("tipo") or ""
    obras = tipo in F.TIPOS_OBRAS
    sumario = (lic.get("procedimiento") == F.PROCEDIMIENTO_SIMPLIFICADO and 0 < ve
               < F.SUMARIO_MAX["obras" if obras else "otros"])
    dur = lic.get("duracion_meses")
    anios = max(dur / 12, 1) if dur else 1
    req_c = lic.get("req") or {}
    con_lotes = bool(lic.get("lotes_detalle"))
    dias = (datetime.strptime(fin, "%Y-%m-%d %H:%M") - ahora).total_seconds() / 86400
    res = []
    for lote, importe, cpvs, nuts, req_l in F._unidades(lic):
        if not F._encaja_cpv(cpvs, prefijos):
            continue
        provincia, entra = F._lugar(nuts, lic, pm)
        if perfil["toda_espana"]:
            entra = True
        if not entra:
            continue
        importe = importe or ve
        if not importe:
            continue
        if perfil["importe_min"] is not None and importe < perfil["importe_min"]:
            continue
        if perfil["importe_max"] is not None and importe > perfil["importe_max"]:
            continue
        fuera, cond, avisos, bien = [], [], [], []
        etiqueta = ""
        vam = importe / anios
        req = dict(req_c, **req_l) if req_l else dict(req_c)
        if con_lotes and "umbral_eco" not in req_l:
            req.pop("umbral_eco", None)          # en un contrato con lotes puede ser la cifra del total
        clas_exig = [c for c in map(F._clas, req.get("clas") or []) if c]
        clas_sustituye = bool(clas_exig and perfil_clas
                              and all(F._cumple_clasificacion(c, perfil_clas) for c in clas_exig))

        # --- clasificación obligatoria en obras (art. 77.1.a LCSP)
        if obras and ve >= F.UMBRAL_CLASIFICACION_OBRAS and not sumario:
            pedida = ("; ".join(map(F.clas_llano, req["clas"])) if clas_exig
                      else f"categoría {F._categoria_obras(vam)} o superior; el anuncio no dice el grupo")
            if clas_sustituye:
                bien.append(f"Tiene la clasificación de contratista que piden ({pedida}).")
            elif perfil["tiene_clasificacion"] and not perfil_clas:
                cond.append(f"Requiere clasificación de contratista ({pedida}): compruebe que la suya la cubre.")
            elif perfil_clas and not clas_exig and any(c[2] >= F._categoria_obras(vam) for c in perfil_clas):
                cond.append(f"Requiere clasificación de contratista ({pedida}): compruebe que el grupo de la suya es "
                            "el que piden.")
            elif perfil_clas:
                cond.append(f"Requiere clasificación de contratista ({pedida}) y la que ha indicado no la cubre.")
            else:
                cond.append(f"Requiere clasificación de contratista ({pedida}) y su empresa no la tiene "
                            "(art. 77 LCSP). Puede pedirla o presentarse en UTE con otra empresa clasificada.")

        # --- solvencia económica (art. 87.3.a LCSP)
        umbral = req.get("umbral_eco")
        exigida = umbral or F.FACTOR_SOLVENCIA * vam
        pide = (f"Piden facturar al año {F.eur(exigida)} (según el anuncio)" if umbral else
                f"Pueden pedir facturar al año hasta {F.eur(exigida)} (1,5 veces lo que vale el contrato al año; "
                "cálculo nuestro, el anuncio no da la cifra)")
        if sumario:
            bien.append("Procedimiento abierto simplificado sumario: no piden demostrar solvencia económica.")
        elif clas_sustituye:
            bien.append("Su clasificación de contratista le sirve para demostrar la solvencia económica.")
        elif lo_f >= exigida:
            bien.append(pide + ": su empresa la cubre.")
        elif hi_f < exigida and umbral:
            fuera.append(f"El anuncio exige {F.eur(umbral)} de facturación anual: su empresa no llega.")
        elif not umbral and hi_f < FACTOR_DESPROPORCION * vam:
            # sin cifra en el anuncio, ni con la mitad del máximo legal llegaría (decisión de César, 02-11-2026)
            etiqueta = DESPROPORCIONADO
            fuera.append(f"Aunque el pliego pidiera la mitad del máximo legal ({F.eur(FACTOR_DESPROPORCION * vam)} "
                         "al año), su empresa no llegaría; solo sería viable en UTE (art. 69 LCSP) o apoyándose en la "
                         "solvencia de otra empresa (art. 75 LCSP).")
        elif hi_f < exigida:
            # sin la cifra del anuncio solo sabemos el tope legal: el pliego puede pedir menos
            cond.append(pide + ": su empresa no llega a ese tope, pero puede que el pliego pida menos: revise la "
                        "solvencia en el pliego.")
        else:
            cond.append(pide + ": depende de su cifra exacta de facturación, que está en ese tramo.")

        # --- avisos orientativos (no cambian el grupo)
        if vam > F.VAM_POR_TRABAJADOR * hi_t:
            avisos.append(f"Su plantilla puede quedarse corta: el contrato mueve unos {F.eur(vam)} al año "
                          f"(orientativo, no excluye).")
        if not sumario and "OXR-PLANTILLA" in (req.get("tec") or []):
            avisos.append("El anuncio pide un número mínimo de personas en plantilla: mírelo en el pliego.")
        if not dur:
            avisos.append("El anuncio no dice cuánto dura el contrato: hemos supuesto un año.")
        if provincia == F.SIN_LUGAR:
            avisos.append("El anuncio no dice dónde se hace el trabajo.")
        if not sumario and "OSR-COMPTASK" in (req.get("tec") or []):
            avisos.append("Piden haber hecho trabajos parecidos en los últimos años.")
        if not sumario and req.get("cert"):
            avisos.append("Piden certificados: " + ", ".join(sorted({F.cert_llano(c) for c in req["cert"]})) + ".")
        if dias < DIAS_AVISO_CIERRE:
            avisos.append("Cierra en menos de 2 días.")

        grupo = FUERA if fuera else CONDICIONES if cond else ENCAJA
        res.append({
            "grupo": grupo, "id": lic.get("id"), "titulo": lic.get("titulo"), "organo": lic.get("organo"),
            "url": lic.get("url"), "fin_plazo": fin, "provincia": provincia, "tipo": tipo,
            "lote": (lote or {}).get("id"), "titulo_lote": (lote or {}).get("titulo"),
            "importe": importe, "vam": round(vam), "solvencia_exigida": round(exigida),
            "solvencia_del_anuncio": bool(umbral), "sumario": sumario,
            "etiqueta": etiqueta, "fuera": fuera, "condiciones": cond, "avisos": avisos, "bien": bien,
            # para F.agrupar_lotes (lotes iguales de una misma licitación en una sola ficha)
            "motivos": fuera + cond + avisos + bien,
        })
    return res


def filtrar(licitaciones, perfil, ahora):
    """{grupo: [fichas ordenadas por fecha límite]} y el número de licitaciones abiertas que se han mirado."""
    salida = {g: [] for g in GRUPOS}
    for lic in licitaciones:
        for r in evaluar(lic, perfil, ahora):
            salida[r["grupo"]].append(r)
    for g in GRUPOS:
        salida[g] = F.agrupar_lotes(salida[g])           # ya las ordena por fin de plazo
    return salida


# ─── páginas ────────────────────────────────────────────────────────────────────────────────────────────────────
def _e(t):
    return html.escape(str(t if t is not None else ""), quote=True)


CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#f5f6f8;color:#1c2333;margin:0;
line-height:1.45;font-size:16px}
.fe{max-width:820px;margin:0 auto;padding:16px}
.marca{font-weight:700;color:#1b2f5c;margin-bottom:12px}.marca a{text-decoration:none;color:inherit}
h1{font-size:1.45rem;margin:.2em 0 .3em}h2{font-size:1.15rem;margin:1.2em 0 .4em}
.sub{color:#4a5468;margin:0 0 14px}
fieldset{background:#fff;border:1px solid #d9dde5;border-radius:10px;margin:0 0 14px;padding:12px 14px 14px;min-width:0}
legend{font-weight:700;padding:0 6px;font-size:1.02rem}
.ayuda{color:#5b6477;font-size:.88rem;margin:2px 0 8px}
.lista{max-height:320px;overflow-y:auto;border:1px solid #eef0f4;border-radius:8px;padding:4px 8px}
.lista label,.opc label{display:flex;gap:8px;align-items:flex-start;padding:6px 0;cursor:pointer}
.lista input,.opc input{margin-top:3px;width:18px;height:18px;flex:none}
.lista .cod{color:#5b6477;font-variant-numeric:tabular-nums;min-width:1.6em}
.ccaa{border-top:1px solid #eef0f4}.ccaa:first-child{border-top:0}
.ccaa>label{font-weight:600}
.provs{padding-left:26px;display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:0 10px}
.campo{margin:6px 0 10px}.campo label{display:block;font-weight:600;margin-bottom:4px}
input[type=text],input[type=search],select{width:100%;font-size:16px;padding:10px;border:1px solid #b9c0cc;
border-radius:8px;background:#fff}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.opc{display:flex;gap:18px;flex-wrap:wrap}
.oculto{display:none}
.errores{background:#fde8e8;border:1px solid #d9534f;border-radius:8px;padding:10px 14px;margin:0 0 14px}
.errores ul{margin:6px 0 0 18px;padding:0}
button{width:100%;font-size:1.05rem;font-weight:700;padding:14px;border:0;border-radius:10px;background:#1b2f5c;
color:#fff;cursor:pointer}
.priv{font-size:.86rem;color:#4a5468;margin:10px 0 0}
.resumen{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 10px}
.cifra{background:#fff;border:2px solid #d9dde5;border-radius:10px;padding:8px 10px;font-size:.9rem}
.cifra b{display:block;font-size:1.5rem}
.cifra.g1{border-color:#1e7a46}.cifra.g2{border-color:#b7791f}.cifra.g3{border-color:#8a93a6}
.grupo{margin:18px 0 8px;padding:8px 12px;color:#fff;border-radius:8px;font-weight:700}
.grupo.g1{background:#1e7a46}.grupo.g2{background:#8a5a12}.grupo.g3{background:#5b6477}
.ficha{background:#fff;border:1px solid #c6ccd6;border-radius:10px;padding:10px 12px;margin:0 0 10px}
.ficha .cab{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:.88rem;color:#3a4356}
.ficha h3{font-size:1rem;margin:6px 0 4px;overflow-wrap:anywhere}
.ficha h3 a{color:#1b2f5c}
.ficha ul{margin:4px 0 4px 18px;padding:0}.ficha li{margin:2px 0}
.ficha .dato{font-size:.92rem;color:#3a4356}
.etiqueta{display:inline-block;margin:6px 0 0;padding:1px 8px;border:1px solid #9b2c2c;border-radius:4px;color:#9b2c2c;font-size:.82rem;font-weight:700}
li.no{color:#9b2c2c}li.cond{color:#8a5a12;font-weight:600}li.aviso{color:#3a4356}li.ok{color:#1e5a3a}
details{margin:0 0 12px}summary{cursor:pointer;font-weight:700;padding:8px 0}
.criterios{background:#fff;border:1px solid #d9dde5;border-radius:10px;padding:4px 14px;font-size:.93rem}
.criterios li{margin:4px 0}
.volver{display:inline-block;margin:6px 0 12px}
.nota{font-size:.88rem;color:#4a5468}
@media (max-width:480px){.resumen{grid-template-columns:1fr}.dos{grid-template-columns:1fr}}
"""

CRITERIOS_HTML = """
<details class="criterios" id="criterios"><summary>Cómo decidimos si una licitación encaja</summary>
<ul>
<li><b>Solo licitaciones abiertas</b>: con el plazo para presentar ofertas sin cerrar, de la Plataforma de
Contratación del Sector Público (las mismas que ve en «Licitaciones abiertas»).</li>
<li><b>Sector y zona</b>: miramos los códigos CPV del contrato (o de cada lote) y el lugar donde se hace el trabajo.
Lo que no es de su sector, de su zona o de su rango de importe no aparece en ningún grupo.</li>
<li><b>Lotes</b>: cada lote se mira por separado. Un lote pequeño de un contrato grande puede encajar aunque el
contrato entero no.</li>
<li><b>Solvencia económica</b>: la ley permite pedir como mucho una facturación anual de 1,5 veces lo que vale el
contrato al año (art. 87.3.a de la Ley de Contratos del Sector Público). Si el anuncio dice la cifra exacta, usamos
esa. Si su facturación no llega ni en lo más alto de su tramo a la cifra que dice el anuncio, la licitación queda
<b>fuera de alcance</b>. Si el anuncio no da la cifra, solo sabemos el máximo que permite la ley y el pliego puede
pedir menos: entonces <b>encaja con condiciones</b> («revise la solvencia»), salvo que su empresa no llegue ni a la
mitad de ese máximo: entonces queda <b>fuera de alcance</b> con la etiqueta «Desproporcionado (estimación nuestra)»,
porque solo sería viable en UTE (art. 69 de la misma ley) o apoyándose en la solvencia de otra empresa (art. 75). También si la cifra está dentro de su
tramo. En el procedimiento simplificado sumario no se pide solvencia.</li>
<li><b>Clasificación de contratista</b>: en obras de 500.000 € o más es obligatoria (art. 77 de la misma ley). Si no la
tiene, se la enseñamos igual como <b>«encaja con condiciones: requiere clasificación»</b>, porque puede pedirla o ir
en unión temporal (UTE) con otra empresa.</li>
<li><b>Trabajadores</b>: solo es una orientación («su plantilla puede quedarse corta»). Nunca quitamos una licitación
por el tamaño de la plantilla.</li>
<li><b>Importes sin IVA</b>, como en el resto de la web.</li>
<li><b>Es una ayuda, no un informe jurídico</b>: lo que manda es el pliego de cada licitación. Muchos requisitos
(experiencia, medios, certificados) solo están en el pliego y no los podemos comprobar.</li>
</ul></details>
"""

PRIVACIDAD = ("No guardamos nada de lo que escribe aquí: lo usamos para calcular esta página y lo olvidamos. Sin "
              "cookies y sin cuentas.")

JS = """
<script>
(function(){
  var b=document.getElementById('buscar-cpv');
  if(b){b.addEventListener('input',function(){
    var q=b.value.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');
    document.querySelectorAll('#lista-cpv label').forEach(function(l){
      var t=l.getAttribute('data-t');l.style.display=(!q||t.indexOf(q)>=0)?'':'none';});
  });}
  var toda=document.getElementById('amb-toda');
  function pintar(){var on=toda&&toda.checked;
    document.getElementById('lista-ambito').classList.toggle('oculto',!!on);}
  if(toda){toda.addEventListener('change',pintar);pintar();}
  document.querySelectorAll('input[data-ccaa]').forEach(function(c){
    c.addEventListener('change',function(){
      document.querySelectorAll('input[data-de="'+c.value+'"]').forEach(function(p){p.checked=c.checked;});});
  });
  var si=document.getElementById('clas-si'),no=document.getElementById('clas-no'),cod=document.getElementById('clas-cod');
  function clas(){if(cod)cod.classList.toggle('oculto',!(si&&si.checked));}
  if(si){si.addEventListener('change',clas);no.addEventListener('change',clas);clas();}
})();
</script>
"""


def _sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def _check(nombre, valor, texto, marcado, extra=""):
    return (f'<label><input type="checkbox" name="{nombre}" value="{_e(valor)}"{" checked" if marcado else ""}'
            f'{extra}> <span>{texto}</span></label>')


def _radio(nombre, valor, texto, actual, extra=""):
    return (f'<label><input type="radio" name="{nombre}" value="{_e(valor)}"{" checked" if actual == valor else ""}'
            f'{extra}> <span>{_e(texto)}</span></label>')


def formulario_html(v=None, errores=()):
    v = v or {}
    div = set(v.get("divisiones") or [])
    amb = set(v.get("ambito_marcado") or [])
    partes = []
    if errores:
        partes.append('<div class="errores" role="alert"><b>Revise estos datos:</b><ul>'
                      + "".join(f"<li>{_e(x)}</li>" for x in errores) + "</ul></div>")
    cpv = "".join(
        f'<label data-t="{_e(_sin_tildes(n + " " + c))}"><input type="checkbox" name="cpv" value="{c}"'
        f'{" checked" if c in div else ""}> <span class="cod">{c}</span> <span>{_e(n)}</span></label>'
        for c, n in sorted(LIC.CPV_DIVISIONES.items()))
    ccaa = []
    for c in COMUNIDADES_ORDEN:
        provs = PROVINCIAS_DE_COMUNIDAD[c]
        cab = _check("ambito", c, _e(F.NOMBRE_COMUNIDAD.get(c, c)), c in amb, f' data-ccaa="1"')
        if len(provs) > 1:
            sub = "".join(_check("ambito", "p:" + p, _e(F.NOMBRE_PROVINCIA.get(p, p)),
                                 ("p:" + p) in amb or c in amb, f' data-de="{c}"') for p in provs)
            ccaa.append(f'<div class="ccaa">{cab}<div class="provs">{sub}</div></div>')
        else:
            ccaa.append(f'<div class="ccaa">{cab}</div>')
    fact = "".join(f'<option value="{_e(k)}"{" selected" if v.get("facturacion") == k else ""}>{_e(t)}</option>'
                   for k, t in TRAMOS_FACTURACION_TEXTO.items())
    trab = "".join(f'<option value="{_e(k)}"{" selected" if v.get("trabajadores") == k else ""}>{_e(t)}</option>'
                   for k, t in TRAMOS_TRABAJADORES_TEXTO.items())
    clas = "si" if v.get("tiene_clasificacion") else "no"
    def _num(x):
        return "" if x is None else f"{x:.0f}"
    partes.append(f"""
<form method="post" action="{RUTA}" autocomplete="off">
<fieldset><legend>1. Sector de actividad</legend>
<p class="ayuda">Marque uno o varios. Son las divisiones de la clasificación CPV que usan los anuncios.</p>
<input type="search" id="buscar-cpv" placeholder="Buscar sector (por ejemplo: limpieza, software, obras)"
 aria-label="Buscar sector">
<div class="lista" id="lista-cpv">{cpv}</div>
</fieldset>
<fieldset><legend>2. Dónde puede trabajar</legend>
<div class="opc">{_check("ambito", TODA_ESPANA, "<b>Toda España</b>", TODA_ESPANA in amb, ' id="amb-toda"')}</div>
<p class="ayuda">O marque comunidades (todas sus provincias) o provincias sueltas.</p>
<div class="lista" id="lista-ambito">{"".join(ccaa)}</div>
</fieldset>
<fieldset><legend>3. Facturación anual</legend>
<p class="ayuda">El volumen anual de negocio del mejor de los tres últimos años, sin IVA.</p>
<select name="facturacion" aria-label="Facturación anual"><option value="">Elija un tramo</option>{fact}</select>
</fieldset>
<fieldset><legend>4. Personas en plantilla</legend>
<select name="trabajadores" aria-label="Personas en plantilla"><option value="">Elija un tramo</option>{trab}</select>
</fieldset>
<fieldset><legend>5. ¿Tiene clasificación de contratista?</legend>
<p class="ayuda">La que da el Registro Oficial de Licitadores (ROLECE) o el de su comunidad.</p>
<div class="opc">{_radio("clasificacion", "no", "No", clas, ' id="clas-no"')}{_radio("clasificacion", "si", "Sí", clas, ' id="clas-si"')}</div>
<div class="campo" id="clas-cod"><label for="clas_codigos">Grupo, subgrupo y categoría (opcional)</label>
<input type="text" name="clas_codigos" id="clas_codigos" value="{_e(" ".join(v.get("clasificacion") or []))}"
 placeholder="Por ejemplo: C2-4, G6-3" autocapitalize="characters">
<p class="ayuda">Si no los pone, le avisaremos para que compruebe si su clasificación cubre lo que piden.</p></div>
</fieldset>
<fieldset><legend>6. Importe que le interesa (opcional)</legend>
<p class="ayuda">En euros, sin IVA. Puede dejar uno o los dos en blanco.</p>
<div class="dos"><div class="campo"><label for="importe_min">Desde</label>
<input type="text" inputmode="numeric" name="importe_min" id="importe_min" value="{_num(v.get("importe_min"))}"
 placeholder="0"></div>
<div class="campo"><label for="importe_max">Hasta</label>
<input type="text" inputmode="numeric" name="importe_max" id="importe_max" value="{_num(v.get("importe_max"))}"
 placeholder="Sin límite"></div></div>
</fieldset>
<button type="submit">Ver las licitaciones a las que puedo optar</button>
<p class="priv">{_e(PRIVACIDAD)}</p>
</form>""")
    partes.append(CRITERIOS_HTML)
    return "".join(partes)


def _fecha(fin):
    try:
        d = datetime.strptime(fin, "%Y-%m-%d %H:%M")
        return d.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return fin


_CLASE = {ENCAJA: "g1", CONDICIONES: "g2", FUERA: "g3"}


def _ficha_html(r):
    lugar = F.lugar_txt(r["provincia"])
    tipo = F.TIPO_TXT.get(r["tipo"], "")
    if r.get("lotes_juntos") and len(r["lotes_juntos"]) > 1:
        lote = "Lotes " + ", ".join(_e(l[0]) for l in r["lotes_juntos"])
    elif r["lote"]:
        lote = "Lote " + _e(r["lote"]) + (": " + _e(r["titulo_lote"]) if r["titulo_lote"] else "")
    else:
        lote = ""
    lis = ("".join(f'<li class="no">{_e(m)}</li>' for m in r["fuera"])
           + "".join(f'<li class="cond">{_e(m)}</li>' for m in r["condiciones"])
           + "".join(f'<li class="ok">{_e(m)}</li>' for m in r["bien"])
           + "".join(f'<li class="aviso">{_e(m)}</li>' for m in r["avisos"]))
    enlace = (f'<a href="{_e(r["url"])}" rel="noopener noreferrer" target="_blank">{_e(r["titulo"])}</a>'
              if r.get("url", "").startswith("https://") else _e(r["titulo"]))
    return (f'<div class="ficha"><div class="cab"><span>Cierra el <b>{_fecha(r["fin_plazo"])}</b></span>'
            f'<span>{_e(lugar)}{" · " + _e(tipo) if tipo else ""}</span></div>'
            + (f'<div class="etiqueta">{_e(r["etiqueta"])}</div>' if r.get("etiqueta") else "")
            + f'<h3>{enlace}</h3>'
            f'<div class="dato">{_e(r["organo"])}</div>'
            + (f'<div class="dato">{lote}</div>' if lote else "")
            + f'<div class="dato">Importe sin IVA: <b>{F.eur(r["importe"])}</b>'
            + (" (cada lote)" if r.get("lotes_juntos") and len(r["lotes_juntos"]) > 1 else "")
            + f'</div><ul>{lis}</ul></div>')


def resultado_html(res, perfil):
    n = {g: len(res[g]) for g in GRUPOS}
    zona = ("toda España" if perfil["toda_espana"] else
            f'{len(perfil["provincias"])} provincia' + ("s" if len(perfil["provincias"]) != 1 else ""))
    partes = [f'<a class="volver" href="#formulario">Cambiar mis datos ↓</a>',
              '<div class="resumen">'
              f'<div class="cifra g1"><b>{n[ENCAJA]}</b>encajan</div>'
              f'<div class="cifra g2"><b>{n[CONDICIONES]}</b>encajan con condiciones</div>'
              f'<div class="cifra g3"><b>{n[FUERA]}</b>fuera de su alcance</div></div>',
              f'<p class="nota">Licitaciones abiertas de {len(perfil["divisiones"])} sector'
              f'{"es" if len(perfil["divisiones"]) != 1 else ""} en {_e(zona)}. Cada lote cuenta por separado; los '
              'lotes iguales de una misma licitación van juntos.</p>']
    titulos = {ENCAJA: "Encaja", CONDICIONES: "Encaja con condiciones",
               FUERA: "Fuera de alcance"}
    for g in (ENCAJA, CONDICIONES):
        partes.append(f'<div class="grupo {_CLASE[g]}">{titulos[g]} ({n[g]})</div>')
        if not res[g]:
            partes.append('<p class="nota">Ninguna ahora mismo.</p>')
        partes += [_ficha_html(r) for r in res[g][:MAX_FICHAS]]
        if n[g] > MAX_FICHAS:
            partes.append(f'<p class="nota">Y {n[g] - MAX_FICHAS} más. Afine el sector, la zona o el importe para '
                          'verlas todas.</p>')
    fichas_fuera = "".join(_ficha_html(r) for r in res[FUERA][:MAX_FICHAS])
    resto = (f'<p class="nota">Y {n[FUERA] - MAX_FICHAS} más.</p>' if n[FUERA] > MAX_FICHAS else "")
    partes.append(f'<details id="fuera"><summary class="grupo {_CLASE[FUERA]}">{titulos[FUERA]} ({n[FUERA]}) — '
                  f'ver</summary>{fichas_fuera or "<p class=nota>Ninguna.</p>"}{resto}</details>')
    return "".join(partes)


SUB = ("Cuéntenos cómo es su empresa y le enseñamos solo las licitaciones públicas abiertas a las que puede optar. "
       "Seis preguntas, menos de un minuto.")


def pagina(cuerpo, titulo="Licitaciones a las que puede optar su empresa", sub=SUB):
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{_e(titulo)} · Dinero Público</title>
<style>{CSS}</style></head>
<body><main class="fe">
<div class="marca"><a href="/">Dinero Público</a> · <a href="/convocatorias">Licitaciones abiertas</a></div>
<h1>{_e(titulo)}</h1>
<p class="sub">{_e(sub)}</p>
{cuerpo}
</main>{JS}</body></html>"""


def responder(metodo, params, licitaciones_abiertas, ahora=None):
    """HTML de la página. GET: el formulario vacío. POST: el resultado y, debajo, el formulario con los datos que ha
    puesto (para cambiarlos). licitaciones_abiertas: función sin argumentos (solo se llama si el envío es válido)."""
    ahora = ahora or datetime.now()
    if metodo != "POST":
        return pagina(f'<div id="formulario">{formulario_html()}</div>')
    perfil, errores = leer(params)
    if errores:
        return pagina(f'<div id="formulario">{formulario_html(perfil, errores)}</div>')
    res = filtrar(licitaciones_abiertas(), perfil, ahora)
    return pagina(resultado_html(res, perfil)
                  + f'<h2 id="formulario">Sus datos</h2>{formulario_html(perfil)}',
                  titulo="Licitaciones para su empresa", sub="Resultado con las licitaciones abiertas de este momento.")
