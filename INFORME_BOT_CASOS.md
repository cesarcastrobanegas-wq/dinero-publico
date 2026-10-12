# Informe de viabilidad: "bot de casos automáticos" (cola de revisión interna)

Fecha: 05-10-2026. Encargo de César: un proceso que analice periódicamente los datos ya cargados y deje candidatos en
una cola de revisión **interna**. Nunca se publica nada automáticamente: César decide qué se convierte en caso y con
qué texto. **No se ha implementado nada**: solo mediciones de solo lectura sobre la copia de producción del 03-10.

---

## 1. Marco legal: umbrales vigentes y lo que de verdad prohíbe la ley

**Umbrales del contrato menor (art. 118.1 de la Ley 9/2017, LCSP), sin cambios desde su entrada en vigor el
09-03-2018 y vigentes en 2026:**

| Tipo | Contrato menor si el valor estimado es inferior a |
|---|---|
| Obras | **40.000 €** |
| Servicios y suministros | **15.000 €** |

- Son **valor estimado sin IVA** (art. 101 LCSP), no importe con IVA. Esto es decisivo para la regla 2 (§3).
- Navarra tiene ley propia (Ley Foral 2/2018) con los mismos importes para sus contratos de menor cuantía.
- Duración máxima de un menor: 1 año, sin prórroga (art. 29.8).
- Excepción: los pagos por anticipo de caja fija de hasta 5.000 € no necesitan el informe del art. 118.2 (art.
  118.5).

**Cambio importante de 2020 que afecta a la regla 1.** La redacción original del art. 118.3 obligaba a comprobar que
el contratista no había firmado otros menores que, juntos, superasen el umbral. Algunas juntas consultivas la leían
como "como mucho un menor por empresa, tipo y año". El **Real Decreto-ley 3/2020** (BOE 05-02-2020) **suprimió esa
exigencia**. Hoy la ley pide un informe que justifique "que no se está alterando el objeto del contrato para evitar la
aplicación de los umbrales" (art. 118.2) y prohíbe fraccionar un contrato "con la finalidad de disminuir su cuantía"
(art. 99.2).

Consecuencia práctica: **que varios menores a la misma empresa sumen más del umbral NO es ilegal por sí mismo**.
Puede tratarse de necesidades distintas (reparaciones independientes, suministros diferentes...). Lo ilegal es partir
un mismo objeto (una misma obra, un mismo servicio continuado) en trozos. Por eso la regla 1 tiene que buscar **indicios
de objeto partido**, no solo sumas, y la cola debe presentar cada candidato como "posible fraccionamiento a revisar",
nunca como "fraccionamiento".

Fuentes:
- [Art. 118 LCSP, texto vigente (Gobierto)](https://contratos.gobierto.es/normativa/ley-contratos-sector-publico/118)
- [Análisis de la modificación del RDL 3/2020 (Andersen)](https://es.andersen.com/la-modificacion-del-contrato-menor/)
- [Contratos menores 2026: umbrales sin cambios (Tendios)](https://tendios.com/blog/contratos-menores-2026-umbrales-obligaciones-y-novedades)

---

## 2. ¿Tenemos los datos necesarios? Sí para ambas reglas, con tres limitaciones serias

Base de cálculo: la tabla de contratos menores (`contratos_menors_locales`), con **1.983.283 contratos** de 58 fuentes,
de septiembre de 2021 a hoy.

| Campo necesario | Cobertura | Comentario |
|---|---|---|
| Fecha de adjudicación | ~99 % | Faltan en 3 fuentes pequeñas (Las Palmas, Toledo, Arona). En algunas fuentes es la fecha de publicación o de factura, no de adjudicación (ya documentado en /metodologia). 58 fechas en el futuro y 1 imposible. |
| Importe | ~99 % | Ver la limitación 1: la **base del IVA**. |
| Tipo de contrato (obras, servicios, suministros) | 93 % reconocible | 143.000 sin tipo o con tipo "privado/otros": no evaluables. Hay que normalizar ~40 grafías (Servicios, 5. SERVEIS, SERV...). |
| Organismo | 100 % | |
| Adjudicatario | 100 % (nombre) | |
| NIF del adjudicatario | Irregular | **Ninguno en las cuatro provincias catalanas** (RPC, ~650.000 contratos), Murcia capital, Valladolid, Burgos y otras: se agrupa por nombre normalizado (ver limitación 2). |
| Descripción del objeto | ~100 % | Imprescindible para la regla 1 (objeto parecido). |
| Procedimiento | No hace falta | Toda la tabla son menores por definición de la fuente. |

**Limitación 1, la base del IVA (crítica para la regla 2).**
- Solo está verificado que el importe va **sin IVA** en el feed de PLACE (849.000 contratos), Governalia y unas pocas
  fuentes propias: ~45 % del total.
- Mula, San Pedro del Pinatar, Cartagena (portal propio) y otras publican **con IVA**; del resto no está verificado.
- Un servicio de 15.000 € sin IVA son 18.150 € con IVA: con la base mal leída, un menor perfectamente legal parece "mal
  etiquetado".
- Propuesta: la regla 2 solo considera indicio claro lo que supera el umbral **en fuentes sin IVA**, o lo que lo supera
  **incluso descontando un 21 % de IVA** en las demás.

**Limitación 2, empresas sin NIF.** Agrupar por nombre puede juntar dos empresas distintas con nombres parecidos, o
separar una misma empresa escrita de dos formas. Un candidato sin NIF lleva una marca visible de "agrupado por nombre".

**Limitación 3, duplicados entre fuentes.** El feed de PLACE y la fuente propia del ayuntamiento pueden traer el mismo
contrato dos veces. La carga ya los empareja (±7 días, importe compatible), pero no es perfecta. Un duplicado inflaría la
suma de la regla 1, así que la regla deduplica de nuevo dentro de cada grupo (misma fecha e importe parecido).

**Subvenciones.** Lo que cargamos de la BDNS son **convocatorias**, no concesiones a beneficiarios: no sirven para
estas dos reglas. Las concesiones están en la BDNS y permitirían reglas de fase 2 (el mismo beneficiario recibiendo
muchas ayudas del mismo órgano), pero contienen datos personales de personas físicas y su aviso legal limita la
reutilización al "control de la actuación de los gestores públicos". Queda para la fase 2, con análisis aparte.

---

## 3. Reglas de fase 1 y volumen medido

### Regla 1: posible fraccionamiento (prioridad 1)

**Versión literal del encargo**: misma empresa + mismo organismo + mismo tipo, varios menores (cada uno bajo el umbral)
cuya suma en una ventana móvil de 12 meses supera el umbral.
- **Medido: 45.638 grupos** (30.000 en fuentes sin IVA). La mayoría tienen 2-3 contratos.
- Es inmanejable a mano y, tras el RDL 3/2020, en su mayoría no es ninguna irregularidad.

**Versión propuesta, con indicios de objeto partido** (todas las condiciones a la vez):
- al menos 2 menores a la misma empresa, del mismo organismo y del mismo tipo, en **30 días**;
- cada uno por encima del **40 % del umbral** (descarta compras pequeñas recurrentes);
- descripciones que comparten alguna **palabra significativa** (un mismo objeto: "pista", "alumbrado", "fiestas
  patronales"...);
- suma por encima del umbral.

**Medido: 6.944 grupos** (4.908 en fuentes sin IVA): 1.350 de obras, 4.445 de servicios y 1.149 de suministros.

Sigue siendo mucho para revisar uno a uno, así que la cola se **ordena por puntuación** y muestra primero lo más claro.
La puntuación sube con:
- suma / umbral (2× pesa más que 1,1×);
- importes "pegados" al umbral (varios de 14.500-14.999 €, el patrón clásico);
- mismo día o días consecutivos;
- descripciones casi idénticas (por ejemplo "fase 1 / fase 2", "lote I / lote II");
- fuente sin IVA y NIF presente (más fiable).

Propuesta: la cola enseña las 50-100 mejores de cada pasada; el resto se queda archivado, consultable con filtros.

### Regla 2: menor "mal etiquetado" (prioridad 2)

Un contrato de la tabla de menores cuyo importe ya iguala o supera el umbral de su tipo en la fecha de adjudicación.

| | Fuentes sin IVA | Fuentes con IVA o sin verificar |
|---|---|---|
| Supera el umbral | 2.278 | 14.836 |
| Lo supera incluso descontando un 21 % de IVA | **932** | **914** |

Propuesta: solo entran en la cola las **1.846** de la última fila. En las otras la explicación más probable es el IVA,
no una irregularidad.

También pueden ser errores de origen (un importe de 71 millones en un menor, ya contado en /casos), tipos mal puestos
en la fuente, o contratos que no son menores pero que la fuente publica en su lista de menores. Por eso el candidato
enseña la fuente y el enlace al registro oficial.

### Fase 2 (solo mencionada, no se implementa)

- Concentración anómala: una empresa que se lleva una parte desproporcionada de los menores de un organismo
  (porcentaje sobre el total del organismo y comparación con municipios parecidos).
- Licitador único recurrente: necesita el número de ofertas recibidas. PLACE lo publica en las adjudicaciones
  formales (`ReceivedTenderQuantity`); hoy no lo guardamos, pero se puede extraer del mismo feed.
- Precios atípicos: mismo CPV y unidad, precio muy por encima de la mediana. Exige más campos (unidades, CPV
  completo) y mucho cuidado con las comparaciones.
- Subvenciones: concesiones de la BDNS, con el análisis de datos personales del §2.

---

## 4. Cola de revisión (diseño propuesto)

**Acceso.** Una página `/admin/revision` que no aparece en ningún menú, con `noindex` y bloqueada en robots.
- Entrada con contraseña (el ADMIN_TOKEN) en un formulario, que deja una **cookie de sesión** firmada, HttpOnly,
  Secure y SameSite=Strict, válida unas horas.
- No con `?token=` en la URL, como hacen hoy los endpoints de administración: la URL con el token queda en los
  registros de Render y en el historial del navegador. Para algo que guarda nombres de empresas junto a la palabra
  "revisar", conviene hacerlo mejor.

**Datos.** Una tabla `revision_candidatos` en la base:
- regla, versión de la regla y huella del grupo (para no repetir el mismo candidato en cada pasada);
- municipio, organismo, empresa y NIF, tipo, número de contratos, suma, ventana y puntuación;
- los contratos que lo disparan (ids, fecha, importe, descripción, fuente y enlace);
- estado: pendiente, descartado (con motivo), en seguimiento o convertido en caso;
- nota libre de César, fechas de detección y de revisión.

**Pantalla mínima.**
- Lista ordenada por puntuación, con filtros por regla, comunidad, tipo y estado.
- Cada fila se despliega con los contratos que la disparan, su fuente, su enlace oficial y los avisos de calidad del
  dato ("agrupado por nombre", "base de IVA sin verificar").
- Botones: **Descartar** (motivo: legítimo, error de datos, duplicado...), **Seguir** y **Convertir en caso**.
  Este último crea un borrador en el sistema de casos que ya existe, con los datos copiados y **sin texto**: el texto lo
  escribes tú.

**Esfuerzo aproximado** (sesiones como las de estos días):

| Pieza | Esfuerzo |
|---|---|
| Reglas 1 y 2, normalización de tipos, deduplicación, puntuación | 1,5 |
| Ejecución semanal (ver §5) y subida de candidatos | 0,5 |
| Login con cookie + pantalla de la cola + acciones | 1,5 |
| Pruebas con la copia de producción y ajuste de umbrales de la puntuación contigo | 0,5-1 |
| **Total** | **~4-4,5** |

---

## 5. Frecuencia: semanal, y fuera de Render

- **Semanal mejor que diaria.** La mayoría de fuentes de menores publican por meses o trimestres, así que pasarlo cada
  noche repetiría casi siempre lo mismo. Una pasada semanal (por ejemplo, domingo de madrugada) es suficiente, y la
  cola solo añade lo nuevo gracias a la huella de cada grupo.
- **Fuera de la web.** La medición recorre ~2 millones de contratos y agrupa 634.000 combinaciones: cientos de MB de
  memoria. Dentro del proceso de Render (2 GB, ya en 1-1,5 GB en las noches pesadas) es un riesgo innecesario.
  Propuesta: el mismo patrón que el BORME. GitHub Actions descarga la base con la descarga reanudable, calcula,
  y sube a la web solo los candidatos nuevos (unos cientos, pocos KB), con los registros mostrando solo recuentos.
- **Coste:** cero (Actions es gratis en repositorio público).

---

## 6. Riesgos legales y cómo mitigarlos

1. **Honor y difamación** (LO 1/1982), el principal. Una lista interna con nombres de empresas y alcaldías marcadas como
   "sospechosas" es dañina si se filtra o si se publica con prisa.
   - **Lenguaje neutro en todo el sistema**: "indicador", "candidato a revisar", "posible fraccionamiento"; nunca
     "sospechoso", "fraude" ni "irregular".
   - Nada se publica sin tu revisión. Antes de publicar un caso: comprobar el dato en la fuente oficial y **pedir la
     versión del ayuntamiento** (el informe del art. 118.2 puede justificarlo).
   - El caso publicado cuenta hechos verificados ("estos cinco contratos, en estas fechas, con este objeto"), no la
     conclusión del algoritmo.
2. **Protección de datos (RGPD).** Muchos adjudicatarios son autónomos, es decir, personas físicas. Marcarlos en una
   lista es un tratamiento de datos personales, y puede considerarse elaboración de perfiles (art. 4.4 RGPD).
   - **Base legal:** interés legítimo y finalidad de control de la gestión pública y de información (art. 6.1.f y art.
     85 RGPD). Conviene dejar por escrito una evaluación breve del interés legítimo y una entrada en el registro de
     actividades de tratamiento.
   - **Minimización:**
     - el foco es el organismo que contrata, no la persona;
     - en la cola, los autónomos aparecen con el DNI enmascarado, como ya hace la web;
     - los candidatos descartados se borran pasado un plazo (por ejemplo, 6 meses), dejando solo la huella para no
       volver a mostrarlos.
   - No hay decisiones automáticas con efectos sobre nadie (art. 22): la decisión es tuya.
3. **Falsos positivos por la calidad del dato** (IVA, tipos mal puestos, fechas de publicación, duplicados, agrupación
   por nombre). Se mitigan con:
   - las condiciones de §3;
   - la puntuación que prioriza los datos fiables;
   - avisos visibles en cada candidato;
   - el enlace a la fuente oficial de cada contrato.
4. **Interpretación jurídica.** Tras el RDL 3/2020, sumar menores al mismo contratista no es ilegal. La ayuda de la
   pantalla y cualquier caso publicado deben explicar que lo que prohíbe la ley es partir el objeto (arts. 99.2 y
   118.2), y que el indicador solo señala dónde mirar.
5. **Seguridad de la cola.** Login con cookie (no token en URL), sin enlaces públicos, `noindex`, y un registro de
   quién ha cambiado el estado de cada candidato. El código de las reglas puede estar en el repositorio público; los
   **candidatos no**: viven solo en la base de Render, como los administradores del BORME.
6. **Sesgo de cobertura.** Las comunidades con más datos (Cataluña, País Vasco, PLACE) generarán más candidatos que las
   que publican poco. Un caso nunca debe presentarse como "el municipio que más fracciona": solo se puede hablar de lo
   que se ve.

---

## 7. Decisiones pendientes para César

1. **Regla 1:** ¿versión estricta (≈6.900 grupos, ordenados por puntuación) o la literal (≈45.600)? Recomiendo la
   estricta, y ajustar sus parámetros (30 días, 40 % del umbral, objeto parecido) contigo tras ver 20-30 ejemplos
   reales.
2. **Regla 2:** ¿solo las que superan el umbral incluso descontando IVA (≈1.850), como recomiendo?
3. **Cuántos candidatos por pasada** en la cola (recomiendo 50-100) y si quieres un correo semanal con el resumen
   (necesitaría configurar Resend; hoy no lo está).
4. **Dónde se calcula:** GitHub Actions semanal (recomendado) o dentro de Render.
5. **Acceso a la cola:** login con cookie (recomendado), aunque cueste media sesión más que reutilizar el `?token=`.
6. **Autónomos:** ¿incluirlos en la cola con el DNI enmascarado, o excluirlos de la fase 1 y quedarse solo con
   sociedades? Recomiendo incluirlos enmascarados: el foco está en el organismo que contrata.
7. **Plazo de borrado de los descartados** (recomiendo 6 meses).
8. **Revisión jurídica:** antes de publicar el primer caso salido de este sistema, una lectura de un abogado sobre la
   redacción tipo y sobre la evaluación del interés legítimo. No para la cola interna; sí para lo que se publique.
