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
