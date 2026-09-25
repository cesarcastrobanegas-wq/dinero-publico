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
