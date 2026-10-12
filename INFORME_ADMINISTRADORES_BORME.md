# Administradores de empresas adjudicatarias a nivel nacional — informe de la noche del 30-09 al 01-10-2026

> **Estado: probado en local, NO desplegado.** Rama `wip/administradores-borme`. Espera la confirmación de César:
> es la primera vez que se mostrarían nombres de personas reales a esta escala.

## 1. Resumen

| | Antes (producción hoy) | Después (rama) |
|---|---:|---:|
| Adjudicatarios con administrador o directivo real | 31.320 (25,9 %) | **37.104 (30,7 %)** |
| …de ellos, del BORME (fechado, con documento de origen) | — | 11.493 (9,5 %) |
| Falsas "personas físicas" mostradas (empresas con su propio nombre como autónomo) | 3.713 | 0 |
| Importe de los contratos con administrador real | 52,3 % | **70,9 %** |

Datos: copia de producción del 25-09 (120.709 adjudicatarios distintos, formales y menores, 27,4 mil M€) y BORME
del 01-01-2021 al 30-09-2026 (1.499 días laborables).

## 2. Diagnóstico: cómo funciona hoy el enriquecimiento

- Cadena (`buscar_directivo` en app.py): heurística de **persona física** por el nombre → **empresia.es** (eventos del
  BORME) → buscador de anuncios del BORME en boe.es → búsqueda web (DuckDuckGo). einforma se quitó en agosto (404).
  Resultado en la tabla `directores` de cache.db, con caducidad de 90 días (7 si no encontró nada).
- Cobertura real (copia del 25-09): 51,3 % de los adjudicatarios **nunca consultados**; 25,9 % con administrador;
  18,5 % "persona física" por heurística; 4,1 % no encontrados.
- **Fallo serio en producción**: la heurística decide "persona física" solo por la forma del nombre (2-4 palabras sin
  sufijo) e ignora el NIF. Resultado: empresas mostradas con su propio nombre como si fueran un autónomo. Con la
  detección ampliada (NIF de sociedad, forma jurídica, SCP, GmbH, fundaciones, asociaciones, UTE, comunidades de
  bienes…) son **3.713** adjudicatarios, el **31,7 % del importe total** del sitio: ENDESA ENERGÍA S.A.U.
  ("Endesa Energia Sa Unipersonal"), Aigües de Barcelona ("Agbar Sle"), Cruz Roja ("Creu Roja"), Iberdrola Clientes…

## 3. OpenData Registradores (sede.registradores.org / opendata.registradores.org): descartado como fuente automática

- El portal de datos abiertos tiene un **Directorio de sociedades** (datos gratuitos del art. 17.5 del Código de
  Comercio, Ley 11/2023), pero **cada búsqueda exige resolver un CAPTCHA** ("gire la imagen hasta que aparezca en
  posición vertical") y el sitio está detrás de una protección antibots (F5/TSPD). El resto de la sede (nota
  informativa mercantil, certificaciones) es de pago.
- Sus **términos de uso** prohíben "copiar, reproducir, comunicar públicamente… la totalidad o parte de los contenidos…
  para propósitos públicos o comerciales, si no se cuenta con autorización previa, expresa y por escrito" de CORPME, y
  "manipular… los dispositivos técnicos de protección".
- Automatizarlo con Playwright exigiría saltarse el CAPTCHA y republicar sin autorización: **no se ha hecho**.
- Propuesta: pedir a CORPME acceso o autorización de reutilización (borrador en el anexo A). Si lo conceden, encaja
  como fuente principal delante del BORME sin cambiar la integración (mismo fichero de administradores).

## 4. Lo construido: índice propio del BORME (datos abiertos del BOE)

- `backend/borme_actos.py`: descarga la **sección A del BORME** (actos inscritos) día a día y provincia a provincia
  desde la API de datos abiertos del BOE (sumario diario + versión en texto de cada documento), de lo más reciente
  hacia atrás, con 3 peticiones simultáneas y pausa entre ellas. Separa por sociedad los actos (nombramientos,
  reelecciones, ceses/dimisiones, cancelaciones de oficio, revocaciones, cambio de órgano, cambio de denominación,
  extinción…) y guarda el texto comprimido para re-analizar sin volver a descargar. Reanudable.
  Periodo descargado esta noche: del 01-01-2021 al 30-09-2026 (1.499 días laborables) (42.925 documentos, 3.295.218 anuncios, 1.596.788
  sociedades). Ocupa 1,9 GB en local (`backend/borme_actos.db`, fuera del repositorio).
- `backend/administradores_borme.py`: recorre los actos de cada sociedad en orden cronológico siguiendo los cambios
  de denominación y calcula el **órgano de administración vigente** (administrador único, solidarios, mancomunados,
  consejero delegado, presidente, liquidador). Cruza con los adjudicatarios por **denominación social normalizada**
  (el BORME no publica NIF; las denominaciones son únicas por ley) y escribe `administradores_borme.json` con nombre,
  cargo, fecha del nombramiento y documento BORME de origen.
- Reglas: un nuevo administrador único sustituye al anterior; un cambio de órgano de administración borra el
  anterior; un "consejero" suelto **no** se muestra como administrador (del consejo solo se conoce lo publicado en el
  periodo); apoderados y auditores no cuentan como administradores; sociedades extinguidas no se sobrescriben.

## 5. Integración en la app (rama, sin desplegar)

- El administrador del BORME **manda al mostrar** (`_directivo_contrato`, `_dir_cache_get`): ficha de municipio
  (contratos formales y menores), fondos UE, rankings de empresas, buscador por directivo, API y el componente
  "directivo identificado" del Índice de Transparencia. **Nunca se escribe en los contratos guardados**: quitar el
  fichero deja el sitio exactamente como estaba.
- La heurística de persona física ya no se aplica a sociedades (`_parece_sociedad`), y las falsas personas físicas ya
  guardadas dejan de mostrarse y se vuelven a buscar.
- El detector de coincidencias con alcaldes y concejales prueba ahora el orden "Apellidos Nombre" del BORME.
- Probado en local sobre la copia de producción: ficha, rankings, búsqueda, API e Índice sin errores; Agbar y Cruz
  Roja ya no salen como personas (sin dato hasta encontrar su administrador); ENDESA ENERGÍA pasa a "Armani Gianni
  Vittorio — Presidente del Consejo" (BORME 14-05-2026), FCC Medio Ambiente a Iñigo Sanz Pérez y Urbaser a Mary Ann
  Sigler; un caso real ("Orizon Underwriters S L" guardado como su propia persona física)
  pasa a "Marsh Risk Consulting SL — Administrador Único" según el BORME.

## 6. Lo que queda sin resolver

- **61.472 adjudicatarios (50,9 %) siguen sin administrador**, pero solo pesan el 12,3 % del importe. La mayoría no
  están en el BORME por naturaleza: personas físicas (18.676 se siguen mostrando como "Autónomo / Persona física",
  ahora solo cuando lo parecen de verdad), UTE, administraciones y organismos públicos, asociaciones y fundaciones,
  empresas extranjeras.
- **18.393 sociedades están en el BORME pero sin nombramiento de administrador en 2021-2026**: su órgano se nombró
  antes y no ha cambiado (frecuente en SL con cargo indefinido). Se resolvería descargando 2009-2020 (unas 12 horas
  más de descarga con el mismo script, reanudable).
- **Cruce por denominación**: un adjudicatario escrito sin forma jurídica, con abreviaturas o con otra grafía que la
  del Registro no casa. No se ha medido cuántos de los 90.526 adjudicatarios sin ningún anuncio en el periodo son
  fallos de cruce y cuántos simplemente no tuvieron actos.
- **Consejos de administración**: solo se muestra presidente o consejero delegado; la composición completa solo se
  conoce si se renovó entera en el periodo. **Administradores solidarios/mancomunados**: si solo uno se nombró en el
  periodo, solo se conoce ese. **Administradores que son sociedades**: el BORME-A no da su representante persona
  física.
- **2.244 casos en que el BORME da otra persona que el enriquecimiento antiguo**: manda el BORME (fechado y más
  reciente). Verificados a mano 8 al azar más ENDESA ENERGÍA, Urbaser y FCC Medio Ambiente: correctos; el resto no se
  ha revisado uno a uno. Otros 1.144 tenían guardado un apoderado en lugar del administrador.
- **Formato de los nombres**: el BORME escribe "APELLIDOS NOMBRE"; se muestra así (igual que la mayoría de lo ya
  guardado), con mayúscula inicial.
- **Índice de Transparencia**: el componente "directivo identificado" sube (media 22,5 → 25,4 en los 5.280 municipios
  donde está disponible), así que las notas del índice cambiarían al desplegar.
- **Sin actualización automática todavía**: hace falta añadir la descarga diaria al cron (ver §7).

## 7. Decisiones que necesita César antes de desplegar

1. **Nombres de personas a escala nacional**: son datos de una fuente oficial pública (BORME), pero el RGPD sigue
   aplicando. Propuesta mínima: mostrar solo el órgano de administración (no apoderados), con fecha y enlace al
   documento BORME de cada nombramiento, y un canal visible de rectificación/oposición.
2. **El fichero con los nombres y el repositorio público**: `administradores_borme.json` está en `.gitignore`. Para
   producción hay que decidir si va al repositorio (público en GitHub) o se sube solo al disco de Render.
3. **Cadencia**: el BORME sale cada día laborable; habría que añadir la descarga incremental al cron (unos segundos
   al día) y regenerar el fichero.
4. **Ampliar el histórico** (2009-2020) para cubrir administradores nombrados antes de 2021 sin actos posteriores.

## 8. Otros hallazgos de la noche (fuera de esta pieza)

- **El "importe adjudicado" de PLACE suele ser el presupuesto.** Medido sobre el ZIP oficial de agosto de 2026
  (23.564 licitaciones adjudicadas): el importe que guarda la app (el del resumen del Atom) coincide con lo adjudicado
  solo en el 32,3 %; en el **65,6 %** es mayor (presupuesto de licitación o suma de todos los lotes); mediana +6 %,
  percentil 90 +73 %, extremos de 404 M€ guardados frente a 66 M€ adjudicados. Además, 3.563 licitaciones tienen
  varios lotes que la app atribuye enteros a un solo adjudicatario. Afecta a fichas, rankings por importe y totales.
  Arreglo propuesto: leer `TenderResult/LegalMonetaryTotal` por lote (un registro por lote y adjudicatario) y
  reprocesar los meses.
- **Tarjeta "El mayor contrato adjudicado"**: construida y probada (rama `wip/tarjeta-mayor-contrato`) pero **no
  desplegada** por lo anterior: con los datos de producción gana València (1.204.545.454,55 €, limpieza y residuos en
  4 lotes), y la ficha oficial de PLACE confirma que es el presupuesto base de los 4 lotes, no lo adjudicado a la
  empresa que figura. Se puede publicar en cuanto el importe sea el de adjudicación.

## Anexo A. Borrador de solicitud a CORPME

> Asunto: Solicitud de acceso/autorización para reutilizar datos del Directorio de sociedades
>
> Dinero Público (dinero-publico.com) es un proyecto sin ánimo de lucro de transparencia sobre la contratación
> pública municipal en España. Mostramos, para cada contrato público, la empresa adjudicataria y, cuando consta, su
> órgano de administración, citando siempre la fuente oficial.
>
> Querríamos consultar de forma automatizada los datos gratuitos del Directorio de sociedades (art. 17.5 del Código
> de Comercio) de las aproximadamente 25.000 sociedades adjudicatarias de contratos municipales, con una cadencia
> mensual y un volumen de peticiones moderado, y mostrar públicamente la denominación y el órgano de administración
> con mención expresa a los Registradores de España como fuente.
>
> Les solicitamos: (1) autorización expresa para esa reutilización, y (2) si existe, acceso a un servicio de consulta
> (API o fichero) que no requiera resolver el CAPTCHA del buscador, en las condiciones que ustedes establezcan.
>
> Quedamos a su disposición. César Castro Banegas — Dinero Público.

## 9. Puesta al día de la noche del 01 al 02-10 (rama `wip/administradores-borme-v2`, SIN desplegar)

- La rama original (`wip/administradores-borme`) chocaba con lo desplegado el 01-10 (arreglo de las falsas personas
  físicas, importe adjudicado de PLACE, autónomos de Murcia, DNI enmascarados). La v2 parte del `main` actual y solo
  añade lo propio del BORME: carga de `administradores_borme.json`, `_administrador_borme`, su prioridad al mostrar el
  directivo y el detector de coincidencias con cargos probando el orden "Apellidos Nombre". La rama original se
  conserva sin tocar.
- **Propuesta mínima de RGPD del §7.1, ya montada para poder verla**: junto a cada administrador que sale del BORME se
  muestra "Según el BORME, dd/mm/aaaa", un enlace al anuncio oficial en boe.es y "Pedir rectificación" (correo a
  contacto@dinero-publico.com con el asunto relleno). En la ficha (contratos formales y menores), /rankings y la
  portada. Solo órgano de administración, nunca apoderados (como antes).
- Los autónomos (personas físicas) no pasan por el BORME: siguen mostrándose como "Autónomo / persona física".
- Probado en la copia de producción: Archena 12 administradores con fuente BORME, Cartagena 34, /rankings 22; sin
  errores. Quitar `administradores_borme.json` deja el sitio exactamente como `main`.
- Sigue faltando decidir el §7 (nombres a escala, fichero en el repositorio o en el disco de Render, cron diario,
  histórico 2009-2020). La API (/api/buscar) devuelve el nombre del BORME pero aún no la fecha ni el anuncio.

## 10. Decisiones de César del 04-10 y rama `wip/administradores-borme-v3` (sobre `main` 7473813, SIN desplegar)

- §7.1 RGPD: aprobado tal como está (órgano de administración, fecha, enlace al anuncio, canal de rectificación).
- §7.2 El fichero vive en el disco de Render (`DATA_DIR/administradores_borme.json`), nunca en el repositorio; sigue en
  `.gitignore` y no está en el historial de ninguna rama. Se sube con `POST /admin/administradores-borme?token=...`
  (JSON o JSON en gzip): comprueba el token ANTES de leer el cuerpo (tope 100 MB), valida (>= 1.000 sociedades, con
  nombre y cargo), escribe de forma atómica y recarga sin reiniciar. Solo devuelve y registra recuentos.
- Los nombres del BORME solo se aplican al mostrar: el enriquecimiento ya no los lee para guardar
  (`_dir_cache_get_registro`) y salta las sociedades que ya tienen administrador en el BORME. Así, quitar a alguien del
  fichero (rectificación) lo quita de todo el sitio.
- §7.3 Cron diario: `.github/workflows/administradores-borme-diario.yml`, días laborables 09:30 UTC. Índice del BORME en
  la caché de Actions (la primera vez, descarga completa 2021-hoy: varias horas); días nuevos; base de producción por la
  descarga reanudable; regenera; sube. Sin artefactos y sin nombres en los registros. `borme_actos.py` ya no da por
  descargado un día que falló por red, ni un día reciente sin documentos (puede no haber salido aún).
- §7.4 Histórico 2009-2020: no por ahora.
- Probado en local con la copia de producción del 03-10: 71.716 sociedades (periodo 01-01-2021 a 02-10-2026), +11 MB
  de memoria; ficha, /rankings, portada, /gl/ y /ca/ con fecha, anuncio y rectificación; mismos tiempos con y sin el
  fichero; ningún nombre del BORME escrito en la base (tabla `directores` idéntica; contratos guardados sin cambios de
  directivo).
