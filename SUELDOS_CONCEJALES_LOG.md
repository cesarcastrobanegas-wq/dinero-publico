# Sueldos de concejales — bitácora de lotes

Encargo de César (2026-09-26, noche, autónomo con commit y push automático **solo esta noche**): sueldos de
concejales (no solo alcaldes) publicados en la web oficial de cada ayuntamiento o comunidad autónoma — portal de
transparencia, sede electrónica, BOP/boletín oficial o la propia web municipal. **Nunca agregadores ni prensa.**

**Registro válido** = nombre del concejal + cargo/concejalía + importe + URL de la fuente oficial (y la base del
importe —bruto anual, mensual…— tal como la fuente la dice). Si falta cualquiera, o la fuente/base es ambigua: se
salta y se anota aquí. No se adivina, no se estima, no se convierte (mensual→anual).

**Garantías técnicas** (`backend/actualizar_sueldos_concejales.py`): cada registro se verifica contra el texto
crudo de la fuente (el importe debe aparecer y, en una ventana junto a él, todos los tokens del nombre); el
cargador de `app.py` descarta cualquier registro incompleto; el bloque de la ficha muestra el importe tal cual, con
su base y periodo, y enlaza a la fuente en cada fila.

**Orden**: por comunidad autónoma según población (Andalucía, Cataluña, Madrid, C. Valenciana, Galicia, Castilla y
León, País Vasco, Canarias, Castilla-La Mancha, Murcia, Aragón, Baleares, Extremadura, Asturias, Navarra, Cantabria,
La Rioja) y, dentro de cada una, por población del municipio. Commit y push tras cada comunidad o lote de ~20-30
municipios.

---

## Lote 0 — infraestructura (2026-09-26)

- `sueldos_concejales.json` (vacío), cargador validado y bloque desplegable en la ficha (`sueldos_concejales_html`),
  script de conectores con verificación contra el texto de la fuente. Probado: rechaza importe ausente, nombre no
  cercano al importe, base vacía y URL no https; escapa HTML; no muestra nada si no hay datos; ficha completa
  renderiza (Santiago con registro de prueba, A Coruña sin datos).

---

## Lote 1 — Andalucía (parcial: 4 municipios con datos) — 2026-09-26

**Añadidos: 87 concejales** (Sevilla 45, Málaga 13, Cádiz 12, Huelva 17). Todos verificados contra el texto crudo de la fuente.

| Municipio | Fuente oficial | Qué se guarda |
|---|---|---|
| Sevilla | Portal de Transparencia > Régimen de retribuciones > "Retribuciones percibidas por los concejales en 2024" (PDF) | columna RETRIBUCIONES (por posición); base "retribuciones percibidas en el año", 2024 |
| Málaga | Portal de Transparencia > Altos cargos > Excel "Régimen de dedicación y retribuciones 2023-2027" | TENIENTE ALCALDE y CONCEJAL DELEGADO al 100 %: importe = retribución anual del cargo de la tabla "Retribuciones 2026" del mismo libro |
| Cádiz | Portal de Transparencia > ¿Quién es quién? > Concejales (una ficha por persona) | "Importe anual (en 14 pagas)" + cargo y delegaciones de la ficha |
| Huelva | Portal de Transparencia > Cargos representativos > "Retribuciones cargos representativos 2024" (PDF) | importe **NETO** anual 2024 (así lo rotula la fuente), cargo completo |

**Saltados (y por qué)**
- **Córdoba**: la web publica la escala por cargo (alcalde 71.317,92 €, teniente 64.613,75 €, etc.) pero no importes por persona. Sin nombre+importe en una misma fuente.
- **Granada**: el BOP (edicto del 13/07/2023) da los nombres por categoría (tenientes, delegados) y el importe está en el acuerdo de Pleno aparte; unir documentos exigiría interpretar.
- **Jerez**: acuerdos por cargo (11/07/2023) y régimen de dedicación de delegados (17/07/2023) en documentos separados, sin importe por persona.
- **Marbella**: la sede electrónica (`marbella.sedelectronica.es/employees`) exige identificarse con Cl@ve.
- **Almería, Dos Hermanas, Jaén, Algeciras**: no se localizó un documento oficial con importes (Algeciras: la página `transparencia/retribuciones` da 404; Jaén y Dos Hermanas sin resultados del propio ayuntamiento).
- **Mijas**: existe un PDF oficial ("Retribuciones miembros de la corporación y personal eventual", 2024) pero el servidor no responde (timeout ×3). **Reintentar más tarde.**

**Convenciones y anomalías (revisar por la mañana)**
1. **Cargo genérico "Concejal/a" en Sevilla**: el PDF no dice la concejalía de cada persona; el título lo identifica como "concejales". El alcalde (Sanz Ruiz, 95.684,88 €) figura entre ellos como "Concejal/a" porque la fuente no lo distingue y el fichero del Ministerio no cubre Andalucía.
2. **Importes pequeños en Sevilla** (p. ej. 43,66 €, 163,95 €): son lo "percibido en 2024" que declara el PDF por concejales sin dedicación o de paso; se muestran tal cual, con la base "retribuciones percibidas en el año".
3. **Málaga es una unión cargo→importe dentro del mismo libro oficial**, no un importe junto al nombre. Se saltaron portavoces (el importe depende de si el grupo es de gobierno u oposición y el documento no lo dice por persona), dedicaciones parciales (la tabla no da importe), cargos "/ SECRETARIO" (llevan complemento) y el alcalde.
4. **Cádiz**: 9 fichas saltadas (7 concejales con "importe anual (12 pagas, máximo)" = tope de asistencias, no retribución; el alcalde; una sin importe). Cargo = "tipo. delegaciones" tal como lo escribe la ficha.
5. **Huelva es NETO** (no bruto). El PDF también trae asistencias a plenos y atrasos 2023 pagados en 2024: no se usan.
6. **Bug encontrado y corregido antes de subir datos**: `SUELDOS_CONCEJALES` se cargaba antes de definir `normalizar()`; con el fichero vacío no se notaba y con datos habría tumbado el arranque. Ahora se carga después. El commit de infraestructura (f205bf2, fichero vacío) era inocuo.
7. Mejora de calidad: `nuevo_registro` rechaza nombres de una sola palabra (un parseo de Huelva devolvió apellidos sueltos y la verificación por texto no lo detectaba).

**Pendiente en Andalucía**: Mijas (reintento), Fuengirola, Estepona, Benalmádena, Torremolinos, Vélez-Málaga, Chiclana, El Puerto, Roquetas, El Ejido, Motril, Linares, Alcalá de Guadaíra… (siguientes por población).

---

## Lote 2 — Cataluña, Madrid, C. Valenciana, Galicia, La Rioja, Murcia, Canarias (2026-09-26, madrugada)

**Añadidos: 243 concejales en 11 municipios**

| CCAA | Municipio | N | Fuente oficial | Qué se guarda |
|---|---|---|---|---|
| Cataluña | L'Hospitalet de Llobregat | 16 | Seu electrònica > Retribucions de càrrecs electes (tablas HTML) | retribució bruta anual 2025 (exclusiva/parcial) + càrrec |
| Cataluña | Terrassa | 15 | Govern Obert > Retribucions dels càrrecs electes | **mensual bruta (14 pagues)** 2026, sin convertir; cargo genérico "Regidor/a" |
| Cataluña | Sabadell | 18 | PDF "Retribucions de l'alcaldessa i els regidors" (Ple 11/10/2024) | retribució bruta anual + càrrec |
| Cataluña | Lleida | 14 | La Paeria > Cartipàs > Retribucions càrrecs electes (PDF, act. 17/08/2026) | retribució anual (mensual × 14, comprobado) |
| Cataluña | Girona | 10 | Seu electrònica (seu-e.cat) > cargos electos: fichas individuales | "Retribució anual bruta: Any 2026" |
| Cataluña | Mataró | 13 | Portal de Transparència > Excel "Retribució i dedicació ... 2025" | retribució anual 2025 a 31/12 |
| Madrid | Madrid | 60 | Portal de Transparencia > "Retribuciones brutas percibidas en nómina por cargos electos 2025" (PDF) | **suma de las mensualidades brutas publicadas** de 2025 (aritmética sobre cifras oficiales; la base indica cuántas mensualidades) |
| C. Valenciana | Elche | 21 | Portal de Transparencia > Sueldos públicos | "Dedicación exclusiva/75 %/50 % (Anual 2026)" y cargo/concejalía |
| Galicia | Vigo | 14 | Portal de Transparencia > Retribuciones de los cargos electos (Resolución de la Alcaldía, julio 2023) | retribución anual, dedicación exclusiva y parcial |
| La Rioja | Logroño | 18 | Ayuntamiento > Corporación local > Retribuciones (PDF, act. 4/06/2026) | retribución anual + cargo + grupo |
| Murcia | Murcia | 28 | Ayuntamiento > Dedicación y retribuciones de la Corporación (PDF febrero 2024) | retribución anual + puesto |
| Canarias | Santa Cruz de Tenerife | 16 | Portal de Transparencia > Retribuciones > Altos cargos (tabla 2024) | retribución percibida en 2024 (año completo) |

**Saltados (y por qué)**
- **Barcelona**: su API de datos de cargos (`cards-export`) devuelve "API timeout error" (fuente caída, comprobado dos veces en la noche). **Reintentar.**
- **Badalona / Manresa / Sant Boi / Vilanova / Cornellà**: la ficha del cargo no trae importe (remite a un documento aparte) o la web publica escalas por cargo; Badalona enlaza un BOP de julio de 2023 por categorías; Cornellà devuelve 403 y su PDF es del mandato 2019-2023.
- **Móstoles**: tabla con nombre, cargo y "RETRIBUCIONES" pero sin decir si es anual o mensual → base ambigua, saltado.
- **Zaragoza, Getafe, Pinto, València, Valladolid, Córdoba**: publican la escala por cargo (con nº de puestos) sin nombres.
- **Burgos, Oviedo**: documentos mensuales hasta agosto 2025 / resoluciones sueltas por grupo; sin tabla única nombre-importe.
- **Las Palmas de Gran Canaria**: el PDF con nombres es de octubre 2022 (mandato anterior); la página 2025 no carga sin JavaScript.
- **Écija**: Excel por años, pero el de 2023 es parcial por el cambio de mandato → no comparable.
- **Sin fuente localizada**: Bilbao, Vitoria, Donostia, Palma, Alicante, Torrevieja, Gijón, Santander, Cartagena, Pamplona, Albacete, Badajoz, Sant Cugat (retribución solo en la ficha de cada regidor, sin listado accesible), Leganés (fichas individuales sin comprobar).
- **Reus**: la URL del portal ha cambiado (404). **Alcalá de Henares**: la web no responde. Reintentar ambas.

**Convenciones y anomalías (revisar por la mañana)**
1. **Madrid es una suma**: cada persona aparece 12 veces en el PDF (una por mes) y guardo la suma; 54 de 60 tienen las 12 mensualidades, 6 son parciales (1, 3, 4, 8 y 9 meses) y la base lo dice. Hay importes muy bajos de concejales sin responsabilidad de gestión (p. ej. 67,83 € en 1 mensualidad): son lo que publica el PDF.
2. **Elche**: un primer parseo atribuía a una concejala el importe de otra (un concejal sin línea de importe dejaba texto en el buffer y la verificación por cercanía no lo detecta). Corregido tomando como nombre la última línea que no parece un cargo; el concejal sin importe publicado (Miguel Serna Castillejos) queda fuera.
3. **Mataró**: se saltaron 1 portavoz cuyo cargo dice "Assistència a Plens" (dietas) y 1 regidor al 75 % con solo 8.791 € (periodo parcial); regla: importes < 20.000 € con dedicación no son comparables.
4. **Lleida**: una fila (Jordina Freixanet) se salta porque la fuente escribe "60,300,10 €" y no cuadra con 4.307,15 × 14; la comprobación mensual × 14 se aplica a todas.
5. **Terrassa** es mensual (14 pagas) y **no se convierte**; **Vigo** y **Murcia** son documentos fechados (julio 2023 / febrero 2024): el periodo lo dice y los importes pueden haberse actualizado después.
6. **Sabadell**: el propio PDF oficial escribe "Regidor" para mujeres y "Regidora" para hombres en varias filas; se respeta la fuente.
7. **Logroño**: 8 concejales con "Indemnización asistencias" (dietas) saltados. **Santa Cruz de Tenerife**: solo filas con año completo; las de 2023 (periodos parciales, celdas combinadas) no se usan.
8. **Alcalde**: se excluye cuando el Ministerio lo identifica (Cataluña, Murcia) o el documento lo rotula "Alcalde".
9. **Mejoras de infraestructura**: escritura atómica y guardado tras cada municipio (varias ejecuciones en paralelo sin pisarse); `nuevo_registro` acepta importes de Excel escritos "49777.7"; conector genérico para la plataforma seu-e.cat (43 municipios catalanes sondeados: la mayoría no publica el importe en la ficha; los resultados irán en el lote siguiente).

---

## Lote 3 — Madrid (Majadahonda), Murcia (Molina de Segura), Castilla y León (Palencia), Baleares (Eivissa) (2026-09-27)

**Añadidos: 56 concejales en 4 municipios** (total acumulado: 386 registros en 20 municipios).

| CCAA | Municipio | N | Fuente oficial | Qué se guarda |
|---|---|---|---|---|
| Madrid | Majadahonda | 15 | Portal de Transparencia > "Retribuciones de la Alcaldesa y Concejales 2025" (Excel) | retribución bruta anual 2025 + cargo |
| Murcia | Molina de Segura | 14 | Portal de Transparencia > "Las retribuciones percibidas anualmente" (tabla HTML, revisada 24/09/2026) | retribución bruta anual + dedicación |
| Castilla y León | Palencia | 13 | Ayuntamiento > Retribuciones corporación > "Retribuciones íntegras ... dedicación exclusiva o parcial año 2025" (PDF) | retribuciones íntegras percibidas en 2025 |
| Baleares | Eivissa | 14 | Ayuntamiento > Retribuciones regidores (tabla HTML) | retribución anual 2025 + dedicación |

**Sondeo de la plataforma seu-e.cat (43 municipios catalanes)**: solo **Girona** rellena "Retribució anual bruta" en la ficha del cargo. En los otros 42 la ficha no trae el importe (remite a un documento aparte) o el listado no expone fichas (Olot, Salt, Calafell, Sitges, Argentona; Castellbisbal dio timeout). Resultado: 0 registros adicionales.

**Saltados (y por qué)**
- **Torrent**: publica las nóminas mensuales completas (con IRPF, cotizaciones, base…) de cada concejal; son importes mensuales dentro de un recibo con datos que no corresponde reproducir, y no hay tabla anual → saltado.
- **Calvià**: solo el acuerdo de Pleno (categorías). **Palma**: el PDF enlazado es de marzo 2023 (anterior al mandato). **Lugo**: por categoría y nº de puestos, sin nombres. **Pontevedra**: mandato 2019-2023 (la sede no expone el 2023-2027). **Santa Lucía de Tirajana**: líneas de presupuesto sin nombres. **Aranda de Duero**: escala por cargo. **Villajoyosa**: "Próximamente".
- **Marbella y Orihuela**: la sede electrónica (`*.sedelectronica.es/employees`) exige Cl@ve.
- **Estepona, Benalmádena**: cifras solo en noticias/bases de ejecución del presupuesto, sin tabla nominal en el portal. **Fuengirola**: la web no responde. **Cartagena, Reus (URL cambiada), Alcalá de Henares (SSL)**: pendientes de reintentar.

**Convenciones y anomalías**
1. **Eivissa**: la fuente escribe algunos importes como "63.407.63 €" (punto de millar y punto decimal). Acepto solo ese patrón exacto (3 grupos, 2 cifras finales; inequívoco y coherente con el resto de filas) y lo señalo aquí para revisión; cualquier otra rareza se salta. Los "-" son concejales sin retribución (no se guardan). El propio cargo trae inconsistencias de género en origen.
2. **Majadahonda**: 3 personas con dos filas por cambio de cargo a mitad de año (Silván, Montón, Rodríguez) se saltan por ambiguas; las de "régimen de asistencia" (0 €) tampoco.
3. **Palencia**: 1 concejal con 8.237,42 € (año parcial) se muestra tal cual. Nombre y cargo van seguidos en mayúsculas en el PDF: se separan en la primera palabra ALCALD*/CONCEJAL*.
4. **Infraestructura**: cabecera `Accept` en las peticiones (varios ayuntamientos bloqueaban la petición sin ella: Molina de Segura, Palencia); `main()` guarda tras cada municipio y `_escribir` es atómico.

**Backfill de PLACE (paralelo)**: tandas 3 (+251) y 4 (+63) desplegadas tras probar cada una contra la copia real de producción (commits f8c9a56 y c835ddf); el fichero llega a 971 contratos (meses 202407-202609). La tanda 5 (202406→202309) sigue corriendo; el tope es 202109. El generador se paró en 202409 y 202407 por el vigilante de tiempo (carga de otros procesos; suspensión del equipo de ~21 h), no por datos ni memoria.

---

## Lote 4 — reintentos, Cartagena y notas públicas (2026-09-27)

**Añadidos: 17 concejales** (Cartagena, Murcia). Total acumulado: **403 registros en 21 municipios**.

- **Cartagena**: PDF "Retribuciones de la corporación municipal y del personal eventual" (actualizado a 29/05/2026), sección "Alcaldesa y
  concejales. Legislatura 2023-2027". 9 concejales con "ASIST. PLENOS" (asistencias) saltados; la alcaldesa excluida; los nombres
  partidos en dos líneas se recomponen (verificado a ojo, p. ej. "Maria Cristina Mora Menendez de la Vega"). El PDF trae rótulos con errores
  de escritura ("C0MPLETA" con cero) que el parser acepta como jornada completa.

**Reintentos pedidos (resultado)**
- **Barcelona**: su API de cargos (`cards-export`) sigue devolviendo "timeout" (tercera comprobación) → sigue pendiente.
- **Reus**: la página vigente de "Retribució dels càrrecs electes" es una tabla por cargo ("Alcaldessa", "Regidor/a delegat/ada Àrea de ...") con la
  remuneración 2026, sin nombres → aparcado.
- **Alcalá de Henares**: la web tiene un certificado SSL inválido (se pudo leer sin verificar el certificado, solo lectura de un dato público):
  publica cuantías por categoría y el reparto de dedicaciones por grupo, sin importe por persona → aparcado.

**Notas públicas (nuevo, petición de César)**: cada ficha con datos muestra una nota con las salvedades de su fuente (`_NOTAS_SUELDOS_CONCEJALES`);
las fichas de 12 municipios aparcados (Córdoba, Granada, Jerez, Zaragoza, València, Valladolid, Bilbao, Alicante, Palma, Barcelona, Reus, Alcalá) muestran
un aviso con el motivo (`_SUELDOS_CONCEJALES_SIN_TABLA`). Motivos verificados en crudo: Valladolid (PDF de diciembre 2023 por cargo con nº de puestos),
Reus, Alcalá, Zaragoza, Córdoba, Granada y Jerez (ver lotes 1-2); Bilbao y Alicante son "no localizado", y así lo dice el aviso.
Además, las fichas gallegas muestran un aviso sobre el backfill de PLACE (el mes de inicio se lee del propio fichero desplegado).

---

## Lote 5 — más ciudades por población (2026-09-27)

**Añadidos: 101 concejales** (Castellón de la Plana 25, Vitoria-Gasteiz 26, Móstoles 26, Almería 24). Total acumulado: **504 registros en 25 municipios**.

| Municipio | Fuente oficial | Qué se guarda / salvedad |
|---|---|---|
| Castellón de la Plana | castello.es > "Las retribuciones percibidas anualmente por altos cargos..." > PDF `Retribuciones_Cargos_Electos_2024` (una tabla por grupo) | fila "Salario" (bruto), total anual acumulado de 2024; cargo = Concejal/a + grupo + % dedicación. 1 concejala con meses a 0,00 (año parcial) saltada; alcaldesa excluida |
| Vitoria-Gasteiz | vitoria-gasteiz.org > Portal de transparencia > Retribuciones de los altos cargos > XLS "Salario mensual según puesto y dedicación" (actualizado a 19/03/2025) | importe MENSUAL tal cual (no se anualiza); solo puestos 2102/2104/2106/2108 (tenientes de alcalde, delegados de área, delegación especial, portavoces); eventuales, directivos y alcaldesa fuera. La fuente rotula todos los tenientes como "teniente alcaldesa" |
| Móstoles | mostoles.es > Corporación municipal > Remuneraciones 2023-2027 (acuerdo plenario 2/242 de 8/01/2026), dos tablas HTML | importe por persona; la tabla no dice el periodo, no se llama "anual". Alcalde excluido |
| Almería | almeriaciudad.es > Transparencia > Retribuciones de los cargos electos > PDF "Retribuciones y régimen de dedicación miembros Corporación 2026" | retribuciones íntegras ANUALES + régimen (exclusiva / parcial %). Certificado SSL del servidor con cadena incompleta: descarga sin verificar certificado (solo lectura de un documento público). Alcaldesa excluida |

**Saltados y por qué (comprobado en crudo)**
- **León**: PDF oficial "Retribuciones concejales 2024" con cargo e importe pero solo **iniciales** (M.A.C., J.A.S...), no el nombre → no cumple "nombre".
- **Getafe**: cuadros por cargo (número de puestos y retribución anual) sin nombres; las nóminas mensuales son documentos aparte.
- **Oviedo**: el xlsx nominal es de la corporación 2019-2023 (estimación); para el mandato actual solo hay resoluciones de dedicación por grupo, sin tabla de importes.
- **Burgos**: PDF mensual/anual por corporativo (dedicación/asistencias) sin cargo (la alcaldesa es un corporativo más); habría que inferir el cargo → saltado.
- **Leganés**: un PDF por persona con cargo y cuantía, **sin nombre dentro del PDF** (solo en la página que lo enlaza); en la carpeta 109054 los enlaces de declaraciones llevan el nombre de otra persona distinta al cargo del PDF → asociación no fiable.
- **A Coruña**: solo el acuerdo plenario (certificado) por cargo, sin nombres.
- **Toledo**: xlsx "salarios y dietas corporación 2025" por tipo de puesto, sin nombres.
- **Santander**: la página "A.2.4 Retribuciones percibidas anualmente" no devuelve contenido consultable.
- **Las Palmas de G.C.**: el portal de transparencia carga la tabla de miembros electos con un visor que no se lee sin navegador.
- **Fuenlabrada, Alcobendas, Rivas-Vaciamadrid, La Rinconada, Osuna** (comprobados antes del lote): sin tabla nombre + importe utilizable (escala BOCM/BOP o acuerdos plenarios por cargo; Alcobendas, open data 403; Rivas solo nombres).
- Sin verificar a fondo (solo búsqueda, no se afirma nada en la web): Gijón, Salamanca, Alcorcón, Marbella, Dos Hermanas, Guadalajara, Badajoz, Albacete, Pamplona.

Avisos públicos añadidos (`_SUELDOS_CONCEJALES_SIN_TABLA`): León, Getafe, Oviedo, Burgos, Leganés, A Coruña, Toledo, Santander, Las Palmas, Fuenlabrada, Alcobendas, Rivas. Notas públicas para los 4 municipios nuevos.

---

## Lote 6 — Las Rozas de Madrid y más saltos (2026-09-27)

**Añadidos: 14 concejales** (Las Rozas de Madrid). Total acumulado: **518 registros en 26 municipios**.

| Municipio | Fuente oficial | Qué se guarda / salvedad |
|---|---|---|
| Las Rozas de Madrid | transparencia.lasrozas.es > "Dedicación, retribución, indemnizaciones, compatibilidades y delegaciones" (acuerdo con efectos desde 1/08/2023) | "Retribución bruta anual" por cargo y persona (cada fila = 3 encabezados HTML: cargo, nombre, importe). 10 concejales con "VARIABLE POR ASISTENCIAS" saltados (sin importe fijo); alcalde excluido. La fuente dice que las cantidades se incrementan con las Leyes de Presupuestos sin nuevo acuerdo → pueden ser mayores hoy. Cuadra con el propio acuerdo: 15 dedicaciones exclusivas (alcalde + 14) |

**Saltados y por qué (comprobado en crudo)**
- **Donostia / San Sebastián**: PDF oficial con cargo, grupo, % dedicación y salario anual bruto (2025) pero **sin nombres**; los nombres de los cargos están en otro documento (declaraciones en el BOG) → cruce entre documentos, no se hace.
- **Lugo**: importes por tipo de dedicación y grupo ("6 PSOE, 2 PP y 1 Lugonovo: 3.172,40 €"), sin nombres.
- **Pontevedra**: la página de retribuciones es del mandato 2019-2023.
- **Ourense**: los PDF de retribuciones de la corporación y de dedicación exclusiva son imágenes escaneadas (0 caracteres de texto) → no verificables contra el texto de la fuente.
- **Santiago de Compostela**: el portal `transparencia.santiagodecompostela.gal` rechazó la conexión desde aquí (pendiente de reintento, no se afirma nada en la web).
- **Pozuelo de Alarcón**: cambios de régimen de dedicación en sucesivos BOCM y decretos, sin tabla consolidada de nombre e importe.
- **Benidorm**: PDF mensual con total bruto por corporativo y "Dedicación exclusiva/Asistencias" como único dato de cargo (mezcla asistencias con sueldo, sin concejalía) → mismo criterio que Burgos.
- **Torrejón de Ardoz**: documento "Retribuciones anuales Gobierno y Corporación" por cargo, sin nombres.
- Sin comprobar a fondo (solo búsqueda): Torrevieja (Gobierto), Talavera, Cáceres.

Avisos públicos añadidos: Donostia, Lugo, Pontevedra, Ourense, Pozuelo de Alarcón, Benidorm, Torrejón de Ardoz. Nota pública para Las Rozas.

---

## Lote 7 — Huesca y Ciudad Real (2026-09-27)

**Añadidos: 21 concejales** (Huesca 6, Ciudad Real 15). Total acumulado: **539 registros en 28 municipios**.

| Municipio | Fuente oficial | Qué se guarda / salvedad |
|---|---|---|
| Huesca | huesca.es > Recursos humanos > Retribuciones (2026, actual) > "2. Retribuciones alcalde y concejales/as con dedicación exclusiva y parcial" (acuerdo BOP 27/06/2023) | tabla NOMBRE / GRUPO / DEDICACIÓN / IMPORTE BRUTO ANUAL; cargo = "Concejal/a (grupo)" (la tabla no da concejalía). La alcaldesa se excluye porque su resolución es "BOP dedicacion exclusiva Alcaldesa.pdf". Personal eventual (3.ª tabla) fuera |
| Ciudad Real | ciudadreal.es > Transparencia > `7.-Retribuciones_Concejales_024.3.pdf` ("Retribuciones anuales miembros de la Corporación 2.024", actualizado a 30/12/2024) | columna TOTAL RETRIB. (se comprueba = S.BASE + P.EXTRA; la cotización de la empresa no cuenta). Nombre con apellidos primero y sin coma: se deja en el orden de la fuente (dividirlo sería adivinar). Alcalde excluido |

**Saltados y por qué (comprobado en crudo)**
- **Segovia**: acuerdo de Pleno de 23/12/2025 con importe por tipo de cargo y dedicación (6 delegados al 100 %, 4 portavoces al 60 %...), sin nombres.
- **Guadalajara**: BOP de 14/08/2023 con el número de cargos y reglas de reparto por grupo, sin nombres ni importes por persona.
- **Pinto**: retribución 2026 por cargo y dedicación, con nº de cargos por partido, sin nombres.
- **Aranda de Duero**: bases de ejecución por cargo, sin nombres. **Villajoyosa**: la página dice "Próximamente".
- **Ávila**: solo publica percepciones NETAS de la corporación (no bruto); no se toca sin decidir con César si se admiten netas (Huelva ya usa netas y lo dice).
- **Teruel** (503 del servidor de su sede) y **Mérida** (la URL de la página da 404; solo un PDF suelto por persona): pendientes de reintento, no se afirma nada en la web.
- **Barcelona** (cuarta comprobación): su página renderiza "API timeout error or wrong group ID" en cada bloque de cargos electos → sigue pendiente.

Avisos públicos añadidos: Segovia, Guadalajara, Pinto. Notas públicas para Huesca y Ciudad Real.

---

## Lote 8 — Salamanca (2026-09-27)

**Añadidos: 27 miembros de la Corporación** (Salamanca). Total acumulado: **566 registros en 29 municipios**.

| Municipio | Fuente oficial | Qué se guarda / salvedad |
|---|---|---|
| Salamanca | aytosalamanca.es > Transparencia > Transparencia activa y organización > "Retribuciones percibidas" > PDF "Retribuciones percibidas por los miembros de la Corporación municipal en el ejercicio 2025" | APELLIDOS, NOMBRE + importe percibido en 2025 (11 filas con `*` = dedicación exclusiva/parcial). **El PDF no da concejalía ni distingue al alcalde**: cargo = "Miembro de la Corporación" (+ dedicación si lleva `*`); el alcalde figura entre ellos y no se puede separar con la propia fuente. No se afirma qué conceptos incluye (los importes pequeños de los no marcados parecen asistencias, pero el PDF no lo dice). Mismo criterio que Sevilla (cargo genérico) con nota pública |

**Saltados y por qué (comprobado en crudo)**
- **Jaén**: el PDF "retribuciones corporación" de su portal es una imagen escaneada (sin capa de texto) → no verificable.
- **Pamplona/Iruña**: la página de transparencia enlaza organigrama y decretos de organización, sin tabla de nombre e importe → "no localizado".
- **Fuenlabrada** (recomprobado con la página "Retribuciones percibidas por los cargos electos"): tres documentos (marco retributivo, régimen de dedicación, BOCM de los no-gobierno) separados; sin nombre + importe en el mismo documento.
- **Algeciras** y **Motril**: las URL de retribuciones dan 404 (las búsquedas las mencionan, no se pudo leer nada). **Fuengirola, Estepona, Roquetas, Gijón, Albacete, Marbella, Dos Hermanas**: sin tabla localizada o sin acceso; no se afirma nada en la web.

Avisos públicos añadidos: Jaén, Pamplona. Nota pública para Salamanca.

---

## Lote 9 — Telde (2026-09-27)

**Añadidos: 16 concejales** (Telde). Total acumulado: **582 registros en 30 municipios**.

| Municipio | Fuente oficial | Qué se guarda / salvedad |
|---|---|---|
| Telde | telde.es > Hacienda > Intervención > "Retribuciones Cargos Electos, altos cargos y personal directivo" (información del año 2025; tabla HTML) | RETRIBUCIÓN ANUAL BRUTA (x14) por persona; cargo = tenencia de alcaldía (si la tiene) + concejalía, o "Concejal de la oposición con dedicación exclusiva (grupo)". La nota de la página dice que todos son dedicación exclusiva salvo una persona (parcial), y así se anota en la base. Alcalde excluido (fila sin importe mensual). 8 tenientes + 6 delegados + 2 de la oposición |

**Saltados y por qué (comprobado en crudo)**
- **Torrent (Valencia)**: publica **recibos de nómina individuales** mensuales (con retenciones y cotizaciones) → no se procesan (datos personales que no hacen falta; categoría solo "CONCEJAL"). Además la clave "torrent" de la base pertenece a un municipio de Girona, así que tampoco se añade aviso (saldría en la ficha equivocada).
- **Gandia**: la página de retribuciones no devuelve contenido legible (carga dinámica).
- **Sant Cugat, Cornellà**: plataforma seu-e.cat (ya sondeada: solo Girona rellena importes).
- Comprobación previa a este lote: las 25 claves de notas y las 36 de avisos caen en el municipio esperado de la base (ninguna homónima en otra provincia).

Nota pública para Telde.

