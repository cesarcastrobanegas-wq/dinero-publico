# Viabilidad: cruzar concejales/alcaldes con el Registro Mercantil (2026-09-27)

Encargo de César: investigar (sin construir nada todavía) si se puede cruzar la lista de concejales/alcaldes ya
recogida (sueldos de concejales, alcaldes) con el Registro Mercantil, para detectar si tienen empresa propia y
mostrar sus últimas 5 cuentas anuales. Dos preguntas concretas: (i) fiabilidad del cruce por nombre sin DNI/NIF,
(ii) fuente de cuentas anuales gratuita o de bajo coste a la escala necesaria (miles de cargos públicos), frente a
las opciones de pago (RM directo, einforma, axesor).

Este documento es solo el informe. No se ha escrito código de producción para esto.

## Punto de partida: lo que el proyecto YA hace hoy (y por qué importa)

`backend/app.py` ya cruza **empresa → administrador** para enriquecer contratos (`buscar_directivo`, tabla
`directores` como caché persistente). La cadena real, en este orden: `empresia.es` (mirror/buscador de BORME) →
búsqueda de anuncios BORME en boe.es (`/buscar/anborme.php`) → texto plano de cada anuncio BORME
(`boe.es/diario_borme/txt.php?id=...`, oficial y gratuito) → como último recurso, una búsqueda web con dominios
de agregadores (einforma/empresia/axesor/infocif) vía DuckDuckGo. `einforma.com` se retiró de la cadena el
2026-08-26 porque devuelve 404 para la mayoría de búsquedas a este ritmo — ya hay una lección real, no teórica,
de que los agregadores gratuitos degradan con el volumen que este proyecto necesita.

Esto es la dirección **inversa** a la que pide este encargo (empresa → persona, no persona → empresa), pero
comparte toda la infraestructura de fondo (BORME/BOE, empresia.es, caché en `directores`, ritmo de peticiones,
manejo de captchas de DuckDuckGo) y ya deja aprendida una lección clave: **el texto de un anuncio BORME trae
nombre y cargo del administrador, pero NUNCA su DNI** (verificado en el propio código: `_extraer_de_borme_empresa`
solo captura nombre + cargo). El DNI de un administrador no es un dato que BORME publique en abierto — vive dentro
del Registro Mercantil, no en su boletín público. Esto no es una limitación de implementación: es un límite
estructural del dato público gratuito, y condiciona la respuesta a (i).

## (i) Fiabilidad del cruce por nombre, sin DNI/NIF

**Conclusión corta: aceptable como primer filtro con matiz, nunca como afirmación publicable sin revisión humana.**

- BORME identifica personas por **nombre y apellidos completos**, nunca por DNI, en el texto que es públicamente
  accesible sin pago. Cualquier cruce por nombre choca con este límite lo mires como lo mires — no hay forma
  gratuita de verificar por DNI con las fuentes abiertas.
- El riesgo real de falso positivo depende de cuántos "administrador con ese nombre completo" existan en toda
  España (~3,4 millones de sociedades activas, más autónomos). Un nombre + un apellido (p. ej. "Juan García") es
  altísimo riesgo. Nombre + dos apellidos (el formato habitual español, que es también el que usa
  `ALCALDES_CONCEJALES`/`SUELDOS_CONCEJALES` en este proyecto) baja mucho el riesgo, pero con apellidos frecuentes
  (García, González, López, Fernández, Martínez, Rodríguez...) sigue habiendo colisiones reales — y a la escala de
  "miles de cargos públicos" ese pequeño porcentaje se traduce en decenas o cientos de atribuciones erróneas si se
  publicaran sin filtrar.
- Señales gratuitas que SÍ reducen el riesgo, sin necesitar DNI:
  1. **Domicilio social de la empresa vs. municipio/provincia del cargo público**: BORME incluye la provincia (a
     veces la dirección completa) del Registro Mercantil donde se inscribe la sociedad. Un "Juan García López"
     administrador de una empresa inscrita en el Registro Mercantil de Lugo coincidiendo con un concejal de un
     ayuntamiento de Lugo es mucho más probable que sea la misma persona que si la empresa está en Cádiz.
  2. **Ventana temporal**: exigir que el nombramiento/alta como administrador sea coherente con la vida pública de
     la persona (no aporta certeza, pero descarta casos absurdos, p. ej. un nombramiento de 1995 cuando el
     concejal nació después).
  3. **Persistencia del cargo**: comprobar que la persona sigue activa como administrador (sin un anuncio de cese
     posterior) en vez de tomar el primer BORME que aparezca.
  4. Precedente ya existente en este mismo proyecto: `_detectar_coincidencia_cargo` (el índice de cargos públicos
     que ya se cruza contra adjudicatarios de contratos) también exige **coincidencia EXACTA de nombre completo**,
     sin DNI, y el propio proyecto documenta ese riesgo como aceptado — pero ahí el coste de un error es "se
     resalta un contrato que no era del cargo público"; aquí el coste de un error sería "se afirma que una persona
     concreta tiene una empresa que no es suya", una aseveración bastante más sensible.
- **Criterio de confianza mínimo que propondría** (si algún día se construye): (a) nombre completo EXACTO
  (nombre + los dos apellidos, sin abreviar); (b) exigir además al menos UNA señal de corroboración gratuita
  (misma provincia del domicilio social, o una segunda coincidencia independiente); (c) nunca publicar la
  atribución en automático — marcarla como "coincidencia por nombre, sin verificar por DNI, pendiente de revisión"
  y pasar por una revisión manual antes de mostrarla en una ficha pública, igual que ya se hace con las anomalías
  de importe en contratos menores (`_NOTAS_CONTRATO_MENOR`, lista cerrada y revisada a mano, no una regla
  automática). Con miles de cargos públicos, la revisión manual de CADA coincidencia no escala del todo, pero sí
  escala revisar solo las que además tengan una señal de corroboración (recorta el volumen a revisar a mano).

## (ii) Fuente de cuentas anuales gratuita o de bajo coste, a escala

**Conclusión corta: existencia de empresa + administrador, sí, gratis y ya con infraestructura reutilizable.
Cuentas anuales con cifras reales (balance/PyG) de los últimos 5 años, NO gratis a esta escala — es exactamente el
terreno de los servicios de pago que se citan como alternativa.**

- **Registro Mercantil directo (depósito de cuentas)**: pedir la cuenta anual depositada de una empresa concreta
  tiene coste por solicitud (varios euros por empresa vía registradores.org/el Registro Mercantil competente) y no
  hay una API pública gratuita de descarga masiva. A la escala de miles de personas (y, si alguna tiene empresa,
  posiblemente más de una sociedad cada una), esto es inviable en coste.
- **BORME (boe.es), la misma fuente gratuita que ya usa el proyecto**: publica el ANUNCIO de que una empresa
  "depositó sus cuentas" de un ejercicio (fecha, a veces referencia del documento), pero el anuncio en sí **no
  lleva las cifras del balance ni de la cuenta de pérdidas y ganancias** — solo confirma que el depósito ocurrió.
  Gratis, pero no resuelve "cuentas anuales" en el sentido de cifras.
- **einforma / axesor / infocif** (las opciones de pago citadas en el encargo): confirmado por la propia
  experiencia de este proyecto que su capa gratuita no aguanta el volumen que necesitamos (einforma ya se
  descartó por 404 a este ritmo). Sus informes con cifras de balance/PyG son de pago, típicamente por informe
  (del orden de varios euros a bastante más por empresa según el detalle), lo que a miles de personas (y
  potencialmente más empresas que personas) puede irse a varios miles de euros para una sola pasada completa.
- **SABI (Bureau van Dijk/Informa)**: la base de datos financiera más completa de empresas españolas, pero es un
  producto de licencia institucional (universidades, consultoras) — nada "de bajo coste" a esta escala; se
  menciona solo para descartarlo explícitamente.
- **Tamaño de la empresa y qué cuentas se pueden pedir de todas formas**: la mayoría de empresas de un concejal
  (si las tiene) serán PYME/microempresa, que en España puede depositar **cuentas abreviadas** (balance y memoria
  abreviados, sin desglose de la cuenta de pérdidas y ganancias). Es decir, aunque se pagara por la cuenta anual
  real de una empresa pequeña, el contenido útil (facturación, beneficio) puede no venir desglosado igualmente —
  una limitación del propio régimen contable español para pequeñas empresas, no de la fuente de datos.
- **Vía intermedia a explorar (no verificada en esta sesión, hay que comprobar su estado real antes de apoyarse en
  ella)**: iniciativas de datos abiertos que republican el CORPUS COMPLETO de BORME en bruto para búsqueda masiva
  (p. ej. proyectos tipo "Libre BORME") permitirían buscar un nombre de persona contra TODO el histórico de BORME
  de una vez, en vez de depender de peticiones una a una contra empresia.es (el cuello de botella actual, sujeto
  a captcha de DuckDuckGo y límites de ritmo). Esto ayudaría a la parte (i) (existencia de empresa + cargo) mucho
  más rápido y sin depender de un intermediario, pero sigue sin resolver (ii) para cifras de cuentas: BORME nunca
  las lleva, venga de donde venga el mirror.

## Recomendación (para decidir, no para ejecutar ya)

1. **Fase 1, gratis, reutilizando infraestructura ya construida**: invertir el sentido de `buscar_directivo`
   (buscar por NOMBRE DE PERSONA en vez de por nombre de empresa, en empresia.es/BORME) para responder solo
   "¿esta persona aparece como administrador/a de alguna sociedad?", con nombre + cargo + empresa + fecha de
   nombramiento + provincia del domicilio social — sin cifras de cuentas. Aporta valor real de transparencia
   (algo que hoy no se muestra en ningún sitio del proyecto) con el mismo nivel de riesgo de falso positivo que ya
   se acepta en otras partes del proyecto, pero con la salvaguarda extra de exigir corroboración por
   provincia/fecha y marcarlo siempre como "coincidencia por nombre, no verificada por DNI".
2. **Fase 2, cuentas anuales**: no automatizarlo a escala nacional. O bien (a) limitarlo a los casos concretos
   que César señale como de interés periodístico (una consulta puntual de pago a einforma/axesor por esa empresa
   específica, unos pocos euros cada vez, con aprobación previa), o (b) si en el futuro aparece un presupuesto
   para un producto de pago a granel, evaluarlo entonces con cifras reales de cuántas empresas habría que
   consultar tras la Fase 1 (que dará el número real, hoy desconocido, de cargos públicos con empresa propia
   detectada).

No se ha tocado `backend/app.py` para nada de esto. Es solo este informe.
