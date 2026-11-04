# encoding: utf-8
"""
Textos legales NUEVOS de Dinero Público (BORRADOR para revisión jurídica, 2026-11-04): aviso legal, política de
privacidad y condiciones de contratación de los servicios por correo (alertas y «Licitaciones para tu empresa»).

NO ESTÁN PUBLICADOS. app.py los sirve en /legal/aviso-legal, /legal/privacidad y /legal/condiciones solo con la
variable de entorno TEXTOS_LEGALES_NUEVOS=1 (sin ella, 404), siempre con noindex, fuera del sitemap y sin ningún enlace
desde otras páginas. El aviso legal que ve hoy la gente sigue siendo /aviso-legal (render_aviso_legal_html, en app.py).

Lo que va entre [corchetes] es un hueco: lo tiene que rellenar o decidir el titular o el abogado. Mientras quede alguno
no se debe encender la variable en producción. Las dudas para el abogado NO están aquí (el repositorio es público):
van aparte, en los .docx del borrador.

Todo lo que dicen los textos sobre lo que hace la web está sacado del código (socios.py, filtro_formulario.py,
alertas.py, cargos_suprimidos.py, revision_privacidad.py, app.py y los flujos de .github/workflows). Lo que describe el
pago del filtro (pagado_hasta, 7 días de cortesía, avisos de vencimiento) es lo de la rama wip/filtro-pagado-hasta
(PR #13), que todavía NO está fusionada: los textos lo dicen.

PENDIENTE: traducir al gallego, catalán y euskera cuando el castellano esté aprobado (hoy solo castellano; bajo /gl/,
/ca/ y /eu/ se sirve el castellano). No llevan _t() a propósito: no deben entrar en los catálogos .po hasta que el
abogado dé el texto por bueno.

Formato: cada documento es una lista de bloques ("h2", texto, ancla), ("p", texto) o ("ul", [textos]). Texto plano:
la página lo escapa, enlaza el correo de contacto y resalta los huecos entre corchetes.
"""
import html
import re

BORRADOR = True     # mientras sea True, la página y los .docx llevan la marca de borrador
MARCA_BORRADOR = "BORRADOR PARA REVISIÓN JURÍDICA — NO PUBLICAR"
CONTACTO = "contacto@dinero-publico.com"
DOMINIO = "https://dinero-publico.com"
VERSION = "Versión de [FECHA DE PUBLICACIÓN]"
TITULAR = "[NOMBRE Y APELLIDOS O RAZÓN SOCIAL DEL TITULAR]"


def _h(texto, ancla=""):
    return ("h2", texto, ancla)


def _p(texto):
    return ("p", texto)


def _ul(*items):
    return ("ul", list(items))


# ─── 1. AVISO LEGAL ─────────────────────────────────────────────────────────────────────────────────────────────────
AVISO_LEGAL = [
    _h("1. Titular del sitio web", "titular"),
    _p("En cumplimiento del artículo 10 de la Ley 34/2002, de 11 de julio, de servicios de la sociedad de la "
       "información y de comercio electrónico (LSSI), estos son los datos del titular de este sitio web:"),
    _ul(f"Titular: {TITULAR}.",
        "NIF: [NIF DEL TITULAR].",
        "Domicilio: [DOMICILIO].",
        f"Correo electrónico de contacto: {CONTACTO}.",
        f"Sitio web: {DOMINIO} («Dinero Público»).",
        "[DATOS DE INSCRIPCIÓN EN UN REGISTRO PÚBLICO, SI PROCEDEN]."),
    _h("2. Qué es Dinero Público", "actividad"),
    _p("Dinero Público es una plataforma de transparencia que reúne en un solo sitio datos públicos y oficiales sobre "
       "el gasto del sector público en España: contratos públicos y sus adjudicatarios, licitaciones y subvenciones "
       "abiertas, fondos europeos, deuda y cuentas de las entidades locales, y alcaldes y concejales con sus "
       "retribuciones. Cubre las 17 comunidades autónomas y las 2 ciudades autónomas, con distinto grado de detalle "
       "según la provincia; el estado de cada una se muestra en el mapa de cobertura."),
    _p("Consultar la web es gratis y no exige registro. Dinero Público ofrece además servicios por correo electrónico "
       "(las alertas por correo y el servicio «Licitaciones para tu empresa»), que se rigen por sus Condiciones de "
       "contratación y por la Política de privacidad."),
    _h("3. Condiciones de uso", "uso"),
    _p("Usar la web supone aceptar este aviso legal. Quien la usa se compromete a hacerlo de forma lícita y sin "
       "dañar el sitio ni impedir que otras personas lo usen."),
    _p("Para que la web responda a todos, el servidor limita de forma automática las peticiones muy seguidas desde un "
       "mismo dispositivo y las de los programas de rastreo, y el fichero robots.txt excluye algunas consultas muy "
       "costosas. [DECIDIR: condiciones para la descarga masiva o automatizada de los datos.]"),
    _h("4. Origen de los datos", "origen"),
    _p("Los datos proceden de fuentes oficiales y públicas. Las principales son:"),
    _ul("Contratos y licitaciones: la Plataforma de Contratación del Sector Público (PLACSP), del Ministerio de "
        "Hacienda, para todo el territorio, y fuentes autonómicas y municipales complementarias, como el Boletín "
        "Oficial de la Región de Murcia (BORM), la Plataforma de Servicios de Contratación Pública de Cataluña (PSCP) "
        "y los portales de datos abiertos de distintos ayuntamientos y comunidades para los contratos menores.",
        "Administradores y apoderados de las sociedades adjudicatarias: el Boletín Oficial del Registro Mercantil "
        "(BORME), que publica la Agencia Estatal Boletín Oficial del Estado. No se consultan directorios privados de "
        "empresas.",
        "Subvenciones: la Base de Datos Nacional de Subvenciones (BDNS).",
        "Fondos europeos: los portales de datos abiertos de la Comisión Europea (Cohesion Data, Kohesio y CORDIS).",
        "Deuda viva, liquidaciones y cuentas de las entidades locales: el Ministerio de Hacienda y la Plataforma de "
        "Rendición de Cuentas de las Entidades Locales.",
        "Población: el Padrón Municipal publicado por el Instituto Nacional de Estadística (INE).",
        "Alcaldes y concejales: el registro oficial de cargos electos de las entidades locales (concejales.redsara.es); "
        "retribuciones: la información salarial de puestos de la Administración (ISPA) y las publicaciones oficiales "
        "que se citan en cada caso."),
    _p("Siempre que es posible, cada dato enlaza con su fuente original. Cómo se calcula cada indicador se explica en "
       "la página de metodología."),
    _h("5. Exactitud de la información y responsabilidad", "exactitud"),
    _p("Los datos se muestran tal como los publican las fuentes oficiales. Cuando se detecta un error evidente de una "
       "fuente, se señala con un aviso y, si hace falta, se deja fuera de las sumas; un dato solo se corrige después "
       "de comprobarlo uno a uno."),
    _p("Las fuentes pueden contener errores, publicarse con retraso o cambiar después. Los cruces entre fuentes (por "
       "ejemplo, entre un contrato y el municipio al que corresponde, o entre una empresa y sus administradores) se "
       "hacen de forma automática y pueden fallar. Por eso la información es orientativa: para cualquier uso con "
       "efectos jurídicos o económicos vale la publicación oficial."),
    _p("Los indicadores, índices y clasificaciones que elabora Dinero Público describen los datos con un método "
       "público. No son un juicio sobre la legalidad ni sobre la conducta de ninguna persona, empresa o "
       "administración: que un dato llame la atención no significa que haya una irregularidad."),
    _p("El titular no responde de los daños que pueda causar el uso de la información de la web, salvo en los casos "
       "en que la ley no permite limitar esa responsabilidad. [ABOGADO: alcance de esta cláusula.]"),
    _p(f"Si ves un error, puedes avisar en los comentarios de la ficha o escribiendo a {CONTACTO}. Los errores "
       "corregidos que tienen interés, propios o de las fuentes, se cuentan en la sección Casos."),
    _h("6. Personas físicas que aparecen en los datos", "personas"),
    _p("Dinero Público publica sobre todo datos de administraciones y empresas. Algunos datos se refieren a personas "
       "físicas; siempre salen de fuentes oficiales y públicas y se muestran con estas reglas:"),
    _ul("Profesionales autónomos adjudicatarios de contratos: con el nombre que publica la fuente y con el DNI o NIE "
        "enmascarado (solo se ven cuatro cifras, por ejemplo ***4567**).",
        "Administradores y apoderados de sociedades adjudicatarias: los que figuran en el BORME, junto con la fecha "
        "del nombramiento, el enlace al anuncio oficial y un enlace para pedir su rectificación.",
        "Alcaldes y concejales, y sus retribuciones: tal como figuran en los registros y publicaciones oficiales.",
        "En la sección de fondos europeos no se muestran beneficiarios que sean personas físicas."),
    _p("Una revisión automática diaria recorre las páginas publicadas y comprueba que no aparecen DNI ni NIE "
       "completos, que no hay personas físicas en la sección de fondos europeos y que cada administrador va con su "
       "fuente en el BORME."),
    _p("Quien aparece en los datos puede ejercer sus derechos de protección de datos como explica la Política de "
       "privacidad. Si procede suprimir a una persona de los listados de alcaldes, concejales o sueldos, se usa una "
       "lista de exclusión que no guarda su nombre."),
    _h("7. Comentarios", "comentarios"),
    _p("Las fichas de municipios y las búsquedas de empresas admiten comentarios, con un nombre opcional. Ningún "
       "comentario se publica hasta que el titular lo revisa y lo aprueba (moderación previa)."),
    _p("[PROPUESTA DE NORMAS] No se publican comentarios con insultos, amenazas, acusaciones sin base, datos "
       "personales de otras personas, publicidad o contenidos ilícitos. Quien comenta responde de lo que escribe. El "
       "titular puede no publicar un comentario o retirarlo en cualquier momento, y lo retirará cuando se le "
       "comunique que es ilícito o lesiona derechos de terceros."),
    _h("8. Propiedad intelectual e industrial", "propiedad"),
    _p("El código fuente de la plataforma está registrado como obra en Safe Creative, con todos los derechos "
       "reservados (número de registro 2607236515551, de 23 de julio de 2026). Que el código pueda consultarse en "
       "un repositorio público no concede ninguna licencia para usarlo."),
    _p("Los datos de las fuentes oficiales se reutilizan conforme a la Ley 37/2007, de 16 de noviembre, sobre "
       "reutilización de la información del sector público, y a las condiciones de cada fuente; pertenecen a quien "
       "los publica."),
    _p("Los textos, el diseño, la marca «Dinero Público» y las elaboraciones propias (cruces, indicadores, rankings) "
       "pertenecen a su titular. [DECIDIR: permitir su reutilización citando la fuente, por ejemplo con licencia "
       "Creative Commons Reconocimiento 4.0, o reservar todos los derechos.]"),
    _h("9. Enlaces a otros sitios", "enlaces"),
    _p("La web enlaza con fuentes oficiales y con otros sitios de interés. Dinero Público no controla su contenido ni "
       "responde de él."),
    _h("10. Publicidad y donaciones", "publicidad"),
    _p("La web puede mostrar publicidad de Google AdSense cuando esté activa, y solo con las cookies que acepte quien "
       "la visita (ver la Política de privacidad). Los anunciantes no influyen en los contenidos."),
    _p("Quien quiera apoyar el proyecto puede hacer una aportación voluntaria por Bizum o por transferencia. Es una "
       "donación: no da derecho a ningún servicio ni condiciona los contenidos."),
    _h("11. Privacidad, cookies y servicios por correo", "privacidad"),
    _p("Cómo se tratan los datos personales y qué cookies usa la web se explica en la Política de privacidad. Las "
       "alertas por correo y el servicio «Licitaciones para tu empresa» se rigen además por sus Condiciones de "
       "contratación."),
    _h("12. Idiomas", "idiomas"),
    _p("La web está en castellano y, en parte, en gallego, catalán y euskera. Si una traducción no coincide con el "
       "castellano, prevalece la versión en castellano."),
    _h("13. Ley aplicable y cambios", "ley"),
    _p("Este aviso legal se rige por la ley española. [ABOGADO: juzgados competentes.] El titular puede actualizarlo; "
       "la versión vigente es la publicada en esta página, con su fecha."),
]


# ─── 2. POLÍTICA DE PRIVACIDAD ──────────────────────────────────────────────────────────────────────────────────────
PRIVACIDAD = [
    _h("1. Responsable del tratamiento", "responsable"),
    _p(f"El responsable es {TITULAR}, con NIF [NIF DEL TITULAR] y domicilio en [DOMICILIO], titular de Dinero "
       f"Público ({DOMINIO}). Para cualquier asunto de protección de datos: {CONTACTO}. "
       "[DELEGADO DE PROTECCIÓN DE DATOS, SI SE NOMBRA.]"),
    _p("Esta política explica qué datos personales se tratan en cada parte de Dinero Público: al visitar la web, en "
       "los datos públicos que se publican, en los comentarios, al escribirnos, en las alertas por correo y en el "
       "servicio «Licitaciones para tu empresa»."),

    _h("2. Si visitas la web", "visitas"),
    _p("Para consultar la web no hace falta registrarse ni dar ningún dato."),
    _ul("Registros del servidor. El proveedor de alojamiento (Render) registra, como cualquier servidor, la dirección "
        "IP, la fecha, la página pedida y el navegador de cada petición. Se conservan [PLAZO DE CONSERVACIÓN DE LOS "
        "REGISTROS DEL SERVIDOR] y solo se usan para el funcionamiento y la seguridad del servicio.",
        "Control de abusos. Para frenar las ráfagas de peticiones, la web lleva la cuenta de las peticiones de cada "
        "conexión y navegador (dirección IP y navegador) solo en memoria, mientras está en marcha; no la guarda.",
        "Recuento propio de visitas, sin cookies. Se guardan solo sumas por día (peticiones, páginas, volumen) por "
        "tipo de visitante, por página sin parámetros y por red. La dirección IP nunca se guarda entera: la red se "
        "recorta a su bloque (los tres primeros números en IPv4, los tres primeros grupos en IPv6), y de los días "
        "pasados solo se conservan, durante 30 días, las 100 redes con más tráfico de cada día. Para no contar dos "
        "veces al mismo visitante se usa una huella de la dirección IP y el navegador mezclada con una clave aleatoria "
        "que se destruye cada semana junto con las huellas.",
        "Almacenamiento en tu navegador. La web guarda en tu propio navegador (almacenamiento local, no cookies) tu "
        "decisión sobre las cookies y algunas preferencias, como el municipio elegido o haber cerrado un aviso. No "
        "salen de tu dispositivo."),
    _h("2.1. Cookies de terceros", "cookies"),
    _p("Solo se activan si las aceptas en el aviso que aparece al entrar, y puedes cambiar tu decisión en cualquier "
       "momento desde «Preferencias de cookies», al pie de cada página. Rechazarlas no impide usar la web."),
    _ul("Google Analytics (Google Ireland Limited / Google LLC): estadísticas de uso agregadas.",
        "Google AdSense, cuando esté activo: mostrar publicidad, que puede ser personalizada según tus intereses."),
    _p("Base legal: tu consentimiento (artículo 6.1.a del Reglamento General de Protección de Datos, RGPD, y "
       "artículo 22.2 de la LSSI). Más información sobre cómo usa Google los datos: "
       "policies.google.com/technologies/partner-sites. [LISTA DE COOKIES CON NOMBRE, FINALIDAD Y DURACIÓN.]"),

    _h("3. Personas que aparecen en los datos publicados", "datos-publicados"),
    _p("Dinero Público publica información de fuentes oficiales y accesibles al público. Algunos de esos datos son de "
       "personas físicas:"),
    _ul("profesionales autónomos adjudicatarios de contratos públicos: nombre y NIF enmascarado (solo cuatro cifras), "
        "con los datos del contrato;",
        "administradores y apoderados de sociedades adjudicatarias: nombre, cargo y fecha del nombramiento según el "
        "BORME, con el enlace al anuncio oficial;",
        "alcaldes y concejales: nombre, cargo, partido y, cuando se publican, sus retribuciones."),
    _p("Finalidad: la transparencia sobre el uso del dinero público y la rendición de cuentas. Se publican los datos "
       "tal como figuran en la fuente y solo los necesarios para esa finalidad. Origen: las fuentes oficiales citadas "
       "en el Aviso legal (PLACSP, fuentes autonómicas y municipales, BORME, registro oficial de cargos electos y "
       "publicaciones oficiales de retribuciones)."),
    _p("Base legal: [ABOGADO: BASE JURÍDICA — interés legítimo del artículo 6.1.f del RGPD en la transparencia y la "
       "información sobre asuntos de interés público, u otra que proceda]."),
    _p("Conservación: [DECIDIR: mientras la información siga publicada en la fuente oficial y tenga interés para la "
       "transparencia, o un plazo concreto]."),
    _p(f"Tus derechos: puedes pedir el acceso, la rectificación o la supresión de tus datos, u oponerte a su "
       f"publicación, escribiendo a {CONTACTO}. Junto a cada administrador del BORME hay además un enlace para pedir "
       "la rectificación. Cada petición se estudia caso por caso, teniendo en cuenta el interés público de la "
       "información."),
    _p("Cuando procede suprimir a una persona de los listados de alcaldes, concejales o sueldos, no se guarda su "
       "nombre: se guarda solo una huella irreversible (un código calculado con una clave secreta a partir del "
       "municipio, la provincia y el nombre), que sirve para que esa persona no vuelva a aparecer cuando se "
       "actualizan los datos desde la fuente oficial. Sin la clave no se puede saber a quién corresponde cada huella."),

    _h("4. Comentarios", "comentarios"),
    _p("Si dejas un comentario en una ficha, se guarda el texto, el nombre que escribas (es opcional), la ficha en la "
       "que lo dejas y la fecha. No se guarda tu dirección IP junto al comentario. El comentario no se publica hasta "
       "que lo aprueba el titular; para avisarle, se le envía por correo el texto y el nombre a través de Resend."),
    _p("Finalidad: publicar tu aportación en la ficha. Base legal: [ABOGADO: consentimiento al enviar el comentario "
       "u otra]. Conservación: mientras esté publicado [DECIDIR: plazo para los comentarios no aprobados]. Puedes "
       f"pedir que se borre en cualquier momento en {CONTACTO}."),
    _p("Lo que escribas, si se publica, lo puede leer cualquiera: no incluyas datos personales tuyos ni de otras "
       "personas."),

    _h("5. Si nos escribes", "contacto"),
    _p(f"Si escribes a {CONTACTO}, usamos tu dirección y lo que nos cuentes solo para contestarte y, si es una "
       "petición de derechos, para atenderla y poder demostrar que se atendió. Base legal: [ABOGADO]. Conservación: "
       "[PLAZO]. El correo lo gestiona [PROVEEDOR DEL CORREO DE CONTACTO]."),

    _h("6. Alertas por correo", "alertas"),
    _p("Este servicio está preparado pero todavía no está abierto al público."),
    _p("Qué datos guardamos: tu dirección de correo electrónico, el idioma en que te apuntaste, tu nivel (gratuito o "
       "de pago) y tus alertas (qué tipo de novedades pides: contratos, licitaciones o subvenciones, y con qué "
       "filtros), con las fechas de alta, de confirmación y de los últimos envíos. No pedimos nombre, teléfono ni "
       "ningún otro dato, y no guardamos tu dirección IP en la base de datos del servicio."),
    _p("De cada correo que enviamos queda un registro (cuándo, de qué tipo, cuántas alertas y novedades llevaba y la "
       "respuesta del servicio de envío, con cualquier dirección de correo tapada) que no incluye tu dirección. Sirve "
       "para no repetir envíos y para no pasar del cupo diario. Se borra a los 400 días; si te das de baja antes, ya "
       "no se puede asociar a ti."),
    _p("Para qué: enviarte las novedades que has pedido (nivel gratuito: una alerta, con un resumen semanal; nivel de "
       "pago: hasta diez alertas, con un aviso diario) y los correos necesarios del servicio (confirmación). No "
       "cedemos tu correo a nadie ni lo usamos para publicidad."),
    _p("Base legal: en el nivel gratuito, tu consentimiento (artículo 6.1.a del RGPD), que confirmas desde el enlace "
       "que te enviamos; en el nivel de pago, [ABOGADO: el contrato (artículo 6.1.b) para el servicio y las "
       "obligaciones legales (artículo 6.1.c) para la facturación]."),
    _p("Cuánto tiempo: si no confirmas tu correo, la solicitud se borra a los 7 días. Si te das de baja, borramos en "
       "ese momento tu dirección y todas tus alertas. Mientras sigas apuntado, guardamos los datos para seguir "
       "enviándote las alertas. [DECIDIR: plazo de borrado por falta de uso, como en «Licitaciones para tu empresa».]"),

    _h("7. «Licitaciones para tu empresa»", "filtro-licitaciones"),
    _p("Este servicio está preparado pero todavía no está abierto al público."),
    _p("Qué datos guardamos:"),
    _ul("tu dirección de correo electrónico;",
        "los datos de tu empresa que indicas en el formulario: sectores (códigos CPV), provincias en las que trabaja "
        "y si quiere también las de ámbito nacional, tipo de contrato que le interesa, número de personas en "
        "plantilla, tramo de facturación, año de constitución, clasificación de contratista, certificados, si ha "
        "trabajado ya para alguna Administración y si iría en unión temporal de empresas (UTE);",
        "las fechas de alta, de confirmación de tu correo y de la última vez que usaste el servicio, y las que "
        "necesita el envío (último correo, último intento fallido, aviso de borrado);",
        "cuando el servicio sea de pago: la fecha hasta la que lo tienes pagado. Junto a tu perfil no se guarda ningún "
        "otro dato del pago."),
    _p("No pedimos nombre, apellidos ni teléfono, y no guardamos tu dirección IP en la base de datos del servicio. "
       "De cada correo enviado queda un registro sin tu dirección (cuándo, de qué tipo y la respuesta del servicio de "
       "envío, con cualquier dirección tapada), que se borra a los 90 días."),
    _p("Cuando el servicio sea de pago, para cobrarlo y facturarlo se tratarán además [DATOS DE FACTURACIÓN: nombre o "
       "razón social, NIF, domicilio fiscal y datos del pago, según la FORMA DE PAGO]. Esos datos no se guardarán "
       "junto al perfil de tu empresa, sino en [DÓNDE SE GUARDAN LOS DATOS DE FACTURACIÓN]."),
    _p("Para qué los usamos:"),
    _ul("buscar las licitaciones abiertas que encajan con tu empresa, enseñártelas al rellenar el formulario y en la "
        "página «Mis licitaciones», y enviártelas por correo una vez por semana (normalmente los lunes), solo si hay "
        "alguna nueva;",
        "enviarte los correos necesarios del servicio: la confirmación de tu correo o de un cambio de datos, el aviso "
        "de que tu perfil se va a borrar por falta de uso y, cuando el servicio sea de pago, los avisos de que tu "
        "periodo pagado va a terminar (15 días antes y el último día);",
        "cuando el servicio sea de pago, guardar el perfil de tu empresa al terminar el periodo pagado, para que no "
        "tengas que rellenarlo otra vez si renuevas, y gestionar el cobro y las facturas."),
    _p("No cedemos tus datos a nadie, no los usamos para publicidad y no los combinamos con otros datos. La selección "
       "de licitaciones la hace un programa con lo que publica la Plataforma de Contratación del Sector Público y con "
       "los datos que nos das. Es orientativa: no toma ninguna decisión sobre ti ni sobre tu empresa."),
    _p("Base legal: [ABOGADO: si el servicio es gratuito, tu consentimiento (artículo 6.1.a), que das al confirmar el "
       "correo; si es de pago, el contrato (artículo 6.1.b) para el perfil y los envíos, las obligaciones legales "
       "(artículo 6.1.c) para las facturas y la base que proceda para guardar el perfil cuando no hay servicio "
       "contratado]."),
    _p("Cuánto tiempo los guardamos:"),
    _ul("si no confirmas tu correo, borramos los datos a los 7 días;",
        "si cambias los datos de tu empresa, el cambio no vale hasta que lo confirmas desde el correo; si no lo "
        "confirmas, se descarta a los 7 días;",
        "si no usas el servicio en 11 meses, te escribimos para preguntarte si quieres mantener tu perfil; si no "
        "pulsas el enlace en 30 días, lo borramos. Si ese aviso no hubiera podido llegarte, lo borramos igualmente a "
        "los 13 meses sin uso. «Usar» el servicio es confirmar tu correo o un cambio, abrir tus licitaciones desde el "
        "enlace del correo o pulsar «mantener mi perfil»; recibir los correos no cuenta;",
        "cuando el servicio sea de pago: mientras tengas el periodo pagado en vigor no te enviamos ese aviso ni "
        "borramos tus datos por falta de uso; al terminar, guardamos tu perfil y esos plazos se cuentan desde el fin "
        "del periodo pagado o desde la última vez que usaste el servicio, lo que sea más tarde;",
        "si te das de baja, borramos tu correo y tu perfil en ese momento;",
        "cuando el servicio sea de pago, las facturas y los datos para emitirlas se conservan el tiempo que exige la "
        "ley [ABOGADO: PLAZO], aunque te hayas dado de baja."),
    _p("Consulta rápida sin registro: si la web ofrece una consulta de licitaciones sin darse de alta, lo que "
       "escribas en ella se usa solo para calcular el resultado en ese momento; no se guarda ni se pide el correo."),

    _h("8. Quién trata los datos por cuenta nuestra", "encargados"),
    _ul("Render (Render Services, Inc., Estados Unidos): el servidor en el que funciona la web y en el que se guardan "
        "las bases de datos. [REGIÓN DEL SERVIDOR.]",
        "Resend (Resend, Inc., Estados Unidos): envía los correos (alertas, «Licitaciones para tu empresa» y el aviso "
        "interno de cada comentario nuevo). Recibe la dirección de destino y el contenido de cada correo solo para "
        "entregarlo.",
        "GitHub (GitHub, Inc., Estados Unidos): ejecuta las tareas programadas que hacen las copias de seguridad y "
        "las guarda en un repositorio privado.",
        "Google (Google Ireland Limited / Google LLC): Analytics y AdSense, solo si aceptas sus cookies.",
        "[OTROS: gestoría, banco o pasarela de pago, programa de facturación, cuando el servicio sea de pago.]"),
    _p("Transferencias internacionales: algunos de estos proveedores están en Estados Unidos. [ABOGADO: garantía "
       "aplicable a cada uno — Marco de Privacidad de Datos UE-EE. UU. o cláusulas contractuales tipo de la Comisión "
       "Europea.]"),

    _h("9. Copias de seguridad", "copias"),
    _p("Una vez por semana se hace una copia de seguridad de las bases de datos de las alertas y de «Licitaciones para "
       "tu empresa». Cada copia se cifra (AES-256) en el momento de hacerla y se guarda solo cifrada en un repositorio "
       "privado; se conservan las cuatro últimas. Por eso, unos datos borrados pueden seguir dentro de una copia "
       "cifrada hasta cuatro semanas, hasta que esa copia se sustituye. Las copias solo se abren para recuperar el "
       "servicio si se pierden los datos."),
    _p("La base de datos general de la web (los datos públicos y los comentarios) también se copia una vez por semana "
       "en un repositorio privado, donde se conservan las dos últimas copias. [Hoy esta copia va comprimida pero no "
       "cifrada: ajustar este párrafo cuando se cifre.]"),

    _h("10. Tus derechos", "derechos"),
    _p(f"Puedes pedir el acceso a tus datos, su rectificación o su supresión, oponerte al tratamiento, pedir que lo "
       f"limitemos y pedir la portabilidad de tus datos escribiendo a {CONTACTO}. Si te diste de alta en un servicio "
       "por correo, escríbenos desde esa dirección. Para darte de baja de las alertas o de «Licitaciones para tu "
       "empresa» basta además con el enlace que va en todos los correos: al pulsarlo se borran tus datos. Si diste tu "
       "consentimiento, puedes retirarlo en cualquier momento, sin que afecte a lo hecho antes."),
    _p("Si crees que no hemos tratado bien tus datos, puedes reclamar ante la Agencia Española de Protección de Datos "
       "(www.aepd.es)."),

    _h("11. Otras cuestiones", "otras"),
    _ul("Menores: los servicios por correo no están pensados para menores de 14 años. [ABOGADO: redacción.]",
        "Decisiones automatizadas: no se toman decisiones con efectos jurídicos sobre nadie de forma automatizada. Los "
        "indicadores de la web y la selección de licitaciones son cálculos orientativos.",
        "Seguridad: las altas se confirman desde el correo (doble confirmación), los enlaces de los correos van "
        "firmados, las bases de datos de los servicios por correo están separadas de la de la web, el panel de "
        "administración pide clave y las copias de los servicios por correo van cifradas.",
        "Cambios: si cambia esta política, la versión nueva se publica aquí con su fecha y, si afecta a los servicios "
        "por correo, se avisa por correo a quien esté dado de alta."),
]


# ─── 3. CONDICIONES DE CONTRATACIÓN ─────────────────────────────────────────────────────────────────────────────────
CONDICIONES = [
    _h("1. Objeto", "objeto"),
    _p("Estas condiciones regulan la contratación de los servicios de pago por correo electrónico de Dinero Público:"),
    _ul("«Licitaciones para tu empresa»: un correo semanal con las licitaciones públicas abiertas que encajan con el "
        "perfil de tu empresa (apartado 4);",
        "Alertas por correo, nivel de pago: avisos diarios de novedades en contratos, licitaciones o subvenciones "
        "(apartado 5)."),
    _p("El nivel gratuito de las alertas no se paga y se rige por la Política de privacidad y, en lo que le sea "
       "aplicable, por estas condiciones. [DECIDIR: si «Licitaciones para tu empresa» tendrá también un nivel o una "
       "prueba gratuitos.]"),
    _h("2. Quién presta el servicio", "prestador"),
    _p(f"Los servicios los presta {TITULAR}, con NIF [NIF DEL TITULAR] y domicilio en [DOMICILIO], titular de Dinero "
       f"Público ({DOMINIO}). Contacto: {CONTACTO}. [DECIDIR: papel de la Cámara de Comercio u otras entidades que "
       "den a conocer el servicio.]"),
    _h("3. A quién van dirigidos", "destinatarios"),
    _p("«Licitaciones para tu empresa» es un servicio para empresas y profesionales autónomos que quieren presentarse "
       "a licitaciones públicas, y se contrata para esa actividad. [DECIDIR: si las alertas de pago se ofrecen "
       "también a particulares (consumidores).]"),
    _h("4. «Licitaciones para tu empresa»: qué incluye", "filtro"),
    _ul("Un perfil de tu empresa, que rellenas en el formulario: sectores (divisiones CPV y, si quieres, códigos más "
        "concretos), provincias en las que trabajas y si quieres también las de ámbito nacional, tipo de contrato "
        "(obras, servicios, suministros), personas en plantilla, tramo de facturación, año de constitución, "
        "clasificación de contratista si la tienes, certificados, si has trabajado ya para alguna Administración y si "
        "irías en UTE.",
        "Al enviar el formulario, una vista previa con las licitaciones abiertas en ese momento que encajan con tu "
        "perfil.",
        "Mientras tengas el servicio pagado [o en periodo de prueba], un correo semanal con las licitaciones NUEVAS "
        "desde el correo anterior que encajan con tu empresa. Sale normalmente el lunes; si ese día hay muchos envíos, "
        "puede llegar en los días siguientes de la misma semana. Si una semana no hay ninguna licitación nueva para "
        "ti, no se envía nada.",
        "Cada licitación va en uno de estos grupos, con los motivos explicados: «Puede optar» (por lo que nos has "
        "dicho y lo que publica el anuncio, tu empresa cumple lo que se pide); «Revisa el pliego» (con los datos del "
        "anuncio no se puede saber si cumples); «Solo en UTE o en un lote» (tu empresa sola no llegaría, pero sí junto "
        "a otra o a una parte del contrato).",
        "Cada correo lleva como mucho 20 licitaciones, las que cierran antes dentro de cada grupo. Las demás están en "
        "la página «Mis licitaciones», a la que se llega con el enlace del correo y que muestra las licitaciones "
        "abiertas de cada momento.",
        "Solo se incluyen licitaciones a las que les quedan al menos 2 días de plazo para presentar ofertas.",
        "Puedes cambiar los datos de tu empresa cuando quieras, rellenando de nuevo el formulario con el mismo correo; "
        "el cambio se aplica cuando lo confirmas desde el correo que te enviamos."),
    _p("Qué no incluye: no se leen los pliegos (la clasificación se hace con los datos del anuncio); no se preparan "
       "ni presentan ofertas ni se asesora sobre ellas; no se garantiza que se te adjudique ningún contrato. El "
       "servicio está solo en castellano. [DECIDIR: si incluye un informe en PDF y atención por teléfono; plazo de "
       "respuesta a las consultas.]"),
    _p("De dónde salen las licitaciones: del canal de licitaciones de la Plataforma de Contratación del Sector Público "
       "(PLACSP), del Ministerio de Hacienda. Algunas comunidades autónomas y entidades publican sus licitaciones en "
       "plataformas propias y no siempre en la PLACSP: esas pueden no aparecer."),
    _h("5. Alertas por correo: qué incluyen", "alertas"),
    _ul("Nivel gratuito: una alerta, con un resumen semanal de novedades.",
        "Nivel de pago: hasta diez alertas, con un aviso diario de novedades.",
        "Cada alerta sigue un tipo de información (los contratos de un municipio, las licitaciones abiertas o las "
        "subvenciones) con los filtros que elijas. «Novedad» es lo que aparece por primera vez después de crear la "
        "alerta: una alerta nueva no envía lo que ya estaba publicado.",
        "Si un día o una semana no hay novedades, no se envía nada.",
        "Las alertas pueden recibirse en castellano, gallego, catalán o euskera, según el idioma en que te apuntes."),
    _p("El paso al nivel de pago lo activa el titular cuando recibe el pago; no hay pasarela de pago automática. "
       "[DECIDIR: duración del nivel de pago y qué pasa al terminar.]"),
    _h("6. Precio y forma de pago", "precio"),
    _p("Precio de «Licitaciones para tu empresa»: [PRECIO]. Precio del nivel de pago de las alertas: [PRECIO]. "
       "[DECIDIR: IVA incluido o «+ IVA»; periodo (mes o año); precios especiales.] El precio incluye todo lo descrito "
       "en estas condiciones; no hay costes adicionales."),
    _p("Forma de pago: [FORMA DE PAGO]. Factura: [QUIÉN LA EMITE, CON QUÉ DATOS Y CÓMO SE ENVÍA]."),
    _h("7. Cómo se contrata", "contratacion"),
    _ul("Rellenas el formulario del servicio y aceptas estas condiciones marcando la casilla correspondiente. "
        "[La casilla está preparada en el PR #25, sin fusionar: hay que fusionarlo antes de vender.]",
        "Te enviamos un correo para confirmar tu dirección. Sin esa confirmación el servicio no empieza y tus datos se "
        "borran a los 7 días.",
        "Al confirmar el correo se guarda tu perfil; el envío de pago empieza cuando se registra el pago [o cuando "
        "empieza tu periodo de prueba]. Sin pago o prueba vigente, «Licitaciones para tu empresa» no envía el correo "
        "semanal.",
        "En el correo para confirmar tu dirección te enviamos el enlace a estas condiciones y a la Política de "
        "privacidad, y la versión que aceptaste. Guardamos la fecha y la versión aceptadas. Puedes consultar, guardar "
        "o imprimir esta página cuando quieras. [DECIDIR: si las versiones anteriores siguen publicadas para quien "
        "aceptó una de ellas.]",
        "Si te equivocas al rellenar el formulario, puedes corregirlo antes de enviarlo y, después, en cualquier "
        "momento, rellenándolo otra vez con el mismo correo."),
    _p("El proceso de contratación es solo en castellano."),
    _h("8. Duración y renovación", "duracion"),
    _p("«Licitaciones para tu empresa» se contrata por [DURACIÓN] desde [EL PAGO / LA CONFIRMACIÓN]. No se renueva "
       "solo. Te escribiremos 15 días antes de que termine y otra vez el último día, con la forma de renovarlo. Si no "
       "renuevas, tienes 7 días de cortesía en los que sigues recibiendo el correo semanal; después se deja de "
       "enviar, pero se guarda el perfil de tu empresa para que no tengas que rellenarlo otra vez si renuevas (cuánto "
       "tiempo, en la Política de privacidad). Con un periodo de menos de 12 días no llega el aviso de 15 días antes, "
       "solo el del último día."),
    _p("Si cambiamos el precio o estas condiciones, te lo diremos por correo al menos [30] días antes de que se "
       "apliquen a tu siguiente periodo; si no estás de acuerdo, puedes darte de baja antes, sin coste."),
    _h("9. Baja", "baja"),
    _p(f"Puedes darte de baja cuando quieras con el enlace que va en todos los correos, desde la página «Mis "
       f"licitaciones» o escribiendo a {CONTACTO}. Al darte de baja con el enlace se borran en ese momento tu correo y "
       "tus datos, y no recibirás más correos. Si la baja llega antes de que termine el periodo pagado, el servicio "
       "termina en ese momento, sin los 7 días de cortesía. [DECIDIR: si se devuelve la parte no disfrutada del "
       "periodo pagado.]"),
    _p("El titular puede dar de baja el servicio si se usa para algo distinto de lo previsto (por ejemplo, revender la "
       "información como propia) [ABOGADO: otros supuestos y preaviso], y también si deja de prestarlo; en ese caso "
       "avisará con [30] días de antelación y devolverá la parte proporcional de lo pagado."),
    _h("10. Derecho de desistimiento", "desistimiento"),
    _p("[ABOGADO: elegir una opción.] [OPCIÓN A, solo empresas y profesionales] Estos servicios se contratan para la "
       "actividad empresarial o profesional de quien los contrata, por lo que no se aplica el derecho de "
       "desistimiento de los consumidores (artículos 102 y siguientes del texto refundido de la Ley General para la "
       "Defensa de los Consumidores y Usuarios). Aun así, puedes darte de baja en cualquier momento como explica el "
       "apartado 9."),
    _p(f"[OPCIÓN B, con consumidores o desistimiento voluntario] Tienes 14 días naturales desde que contratas para "
       f"desistir sin dar ningún motivo, escribiendo a {CONTACTO} o con cualquier otra declaración clara. Te "
       "devolveremos lo pagado en un máximo de 14 días por el mismo medio de pago. Si pides que el servicio empiece "
       "dentro de esos 14 días y después desistes, te descontaremos la parte proporcional al tiempo en que lo has "
       "tenido. [FORMULARIO DE DESISTIMIENTO, SI PROCEDE.]"),
    _h("11. Exactitud de los datos y responsabilidad", "responsabilidad"),
    _ul("Las licitaciones, contratos, subvenciones, importes, plazos y requisitos son los que publican las fuentes "
        "oficiales. Se reproducen tal como se publican; pueden contener errores, cambiar después (correcciones, "
        "ampliaciones de plazo, anulaciones) o publicarse con retraso.",
        "La clasificación de las licitaciones la hace un programa con los datos del anuncio y los que nos das de tu "
        "empresa. Es ORIENTATIVA: los anuncios casi nunca traen todos los requisitos (por ejemplo, cuando el anuncio "
        "no da la solvencia económica que se pide, se estima a partir del importe del contrato) y el programa no lee "
        "los pliegos. Lo que manda siempre es el pliego oficial y el anuncio en la PLACSP: antes de preparar o "
        "presentar una oferta tienes que comprobarlos.",
        "Si los datos de tu empresa no son correctos o están desactualizados, la clasificación tampoco lo será.",
        "No se garantiza que el servicio recoja todas las licitaciones o novedades que podrían interesarte ni que esté "
        "siempre disponible: depende de las fuentes, del servidor y del servicio de envío de correos, y hay un cupo "
        "diario de envíos. Si un correo no sale, las licitaciones siguen en «Mis licitaciones» y van en el correo "
        "siguiente si siguen abiertas.",
        "El titular no responde de las decisiones que tomes con la información del servicio, de que no se te adjudique "
        "un contrato ni de las ofertas que dejes de presentar o presentes fuera de plazo, salvo dolo o culpa grave. "
        "[ABOGADO: límite de responsabilidad.]",
        "La información no es asesoramiento jurídico ni técnico."),
    _h("12. Uso de la información", "uso"),
    _p("La información es para uso de quien contrata. [DECIDIR: si se permite reenviarla dentro de la empresa o a los "
       "socios de una UTE, y si se prohíbe revenderla.]"),
    _h("13. Protección de datos", "datos"),
    _p("Los datos que nos das se tratan como explica la Política de privacidad, en sus apartados «Alertas por correo» "
       "y «Licitaciones para tu empresa»."),
    _h("14. Ley aplicable y tribunales", "ley"),
    _p("Estas condiciones se rigen por la ley española. [ABOGADO: tribunales competentes.]"),
]


DOCUMENTOS = {
    "aviso-legal": {"ruta": "/legal/aviso-legal", "titulo": "Aviso legal", "bloques": AVISO_LEGAL,
                    "descripcion": "Aviso legal de Dinero Público (borrador)."},
    "privacidad": {"ruta": "/legal/privacidad", "titulo": "Política de privacidad", "bloques": PRIVACIDAD,
                   "descripcion": "Política de privacidad de Dinero Público (borrador)."},
    "condiciones": {"ruta": "/legal/condiciones",
                    "titulo": "Condiciones de contratación de los servicios por correo", "bloques": CONDICIONES,
                    "descripcion": "Condiciones de contratación de las alertas y de «Licitaciones para tu empresa» "
                                   "(borrador)."},
}
RUTAS = {d["ruta"]: clave for clave, d in DOCUMENTOS.items()}


# ─── HTML ───────────────────────────────────────────────────────────────────────────────────────────────────────────
_RE_HUECO = re.compile(r"\[[^\[\]]+\]")


def _texto_html(texto):
    t = html.escape(texto, quote=False)
    t = t.replace(CONTACTO, f'<a href="mailto:{CONTACTO}">{CONTACTO}</a>')
    t = t.replace("www.aepd.es", '<a href="https://www.aepd.es" target="_blank" rel="noopener">www.aepd.es</a>')
    return _RE_HUECO.sub(lambda m: f'<mark class="hueco">{m.group(0)}</mark>', t)


def cuerpo_html(clave):
    """El cuerpo (dentro de .static-page) del documento `clave`, sin cabecera ni pie de la web."""
    doc = DOCUMENTOS[clave]
    partes = []
    if BORRADOR:
        partes.append(f'<p class="borrador-legal"><b>{html.escape(MARCA_BORRADOR)}</b><br>Texto en preparación, '
                      'pendiente de revisión jurídica. Los huecos entre corchetes están por completar. Mientras tanto '
                      'vale el <a href="/aviso-legal">Aviso legal</a> publicado.</p>')
    partes.append(f"<h1>{html.escape(doc['titulo'])}</h1>")
    partes.append(f'<p class="sub">{_texto_html(VERSION)}</p>')
    for b in doc["bloques"]:
        if b[0] == "h2":
            ancla = f' id="{html.escape(b[2])}"' if b[2] else ""
            partes.append(f"<h2{ancla}>{_texto_html(b[1])}</h2>")
        elif b[0] == "p":
            partes.append(f"<p>{_texto_html(b[1])}</p>")
        elif b[0] == "ul":
            partes.append("<ul>" + "".join(f"<li>{_texto_html(x)}</li>" for x in b[1]) + "</ul>")
    return ('<div class="static-page textos-legales">\n  ' + "\n  ".join(partes) + "\n</div>")


CSS = ("<style>.textos-legales mark.hueco{background:#fff3b0;color:#3a2f00;padding:0 2px;border-radius:3px}"
       ".textos-legales .borrador-legal{border:2px dashed #c0392b;color:#c0392b;border-radius:8px;padding:10px 14px;"
       "font-size:14px}</style>")
