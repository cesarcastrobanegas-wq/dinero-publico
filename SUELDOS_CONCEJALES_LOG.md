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
