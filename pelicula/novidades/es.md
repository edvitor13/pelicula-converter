## Versión 1.5.0 — 28 de octubre de 2026

**Movimiento, texto y subtítulos en el modo Edición.**

- 🪟 **Transparencia.** Los videos e imágenes con fondo transparente (PNG, ProRes 4444, WebM y el recorte de CorridorKey) aparecen sobre las pistas de abajo, en vez de quedar con fondo negro. Puedes montar con *Fondo transparente* y exportar con transparencia en ProRes 4444, WebM o secuencia de PNG o TIFF. Las secuencias de imágenes numeradas (plano_0001.png…) entran como un solo video.
- ◆ **Animación con claves.** Haz clic en el rombo junto a un ajuste para grabar una clave en el punto donde estás: posición, escala, rotación, opacidad, color, luz, volumen y los ajustes de la película cambian con el tiempo. Las claves aparecen en la línea de tiempo, donde puedes arrastrarlas.
- ⏱️ **Tiempo del clip.** Rampa de velocidad con seis formas listas (el sonido la sigue sin cambiar el tono), reversa y *Congelar este fotograma* (Shift+F).
- 🔤 **Títulos y generadores.** En Medios → *Nuevo*: color sólido, degradado, cola con cuenta regresiva y pitido, y títulos con 11 fuentes integradas, seis estilos y ocho animaciones.
- 🎞️ **Transiciones de película.** Fundido óptico, aparecer y oscurecer en la exposición, película quemada, empalme con destello, cola e iris, además de empujar, cortinilla y zoom. Clic derecho en un clip → *Transición*.
- 💬 **Subtítulos.** Panel (Ctrl+Shift+L) y pista en la línea de tiempo, unidos al habla aunque cortes. Estilos YouTube, Reels (palabra por palabra) y Cine; importa y exporta .srt y .vtt. Al exportar, los subtítulos van en el archivo, grabados en la película (con grano y halación), encima del look o en un archivo aparte.
- 🎙️ **Subtítulos a partir del habla (Beta).** La app transcribe el video en tu computadora, sin enviar nada por internet, y con el tiempo de cada palabra puedes cortar por el texto. Empieza desactivado: actívalo en Configuración → Funciones marcando *Mostrar funciones en prueba* y descarga el transcriptor y un modelo en Componentes (unos 290 MB con el modelo Rápido, o 600 MB con el Preciso).
- 🔇 **Quitar silencios.** La app encuentra los tramos en silencio, muestra la lista para que la revises y los quita todos de una vez (un Ctrl+Z lo deshace).
- ✂️ **Herramientas de corte.** Insertar o sobrescribir al soltar un clip, pista principal magnética opcional, Q y W para recortar hasta el cursor, cortes J y L, y las teclas J, K y L para reproducir hacia atrás, pausar y reproducir hacia adelante. **Repetir** pasó a **Ctrl+L**.
- 🧩 **En tu perfil.** Las herramientas nuevas siguen el perfil de Configuración → Funciones: en Simple llegan desactivadas; en Creador, Cine y Todo, activadas.
- 📂 **Proyectos.** Un proyecto que usa algo nuevo de la 1.5 solo abre en la 1.5 o posterior (la 1.4 avisa, en vez de abrirlo mal). Los proyectos antiguos abren y salen iguales.
- 🛠️ **Corrección.** En Windows, la vista previa de la ventana de exportación a veces mostraba "Vista previa no disponible".

## Versión 1.4.0 — 27 de octubre de 2026

**Exportación lista para cada red, marcadores y capítulos, recorte con IA y una app a tu manera.**

- 📱 **Listo para cada red.** Al exportar, elige la plataforma (YouTube, Shorts, Reels, Stories, TikTok, Kwai, WhatsApp y otras, 27 en total) y la app completa el cuadro, el códec, el sonido y los límites. Recorta, pon bordes negros o fondo desenfocado, elige el tamaño del archivo y el volumen. La vista previa muestra el área segura, donde los botones de la red cubren el video.
- 📍 **Marcadores y capítulos.** En el modo Edición, la tecla M pone un marcador, con color, nombre y nota. Los que marques como capítulo se convierten en el texto listo para la descripción de YouTube y entran en el archivo MP4, MOV o MKV.
- ⌨️ **El sonido de la vista previa cambió de tecla.** Ahora es **Shift+M**, en los dos modos. En el modo Película, la M sigue funcionando como antes.
- 🔊 **Mejor sonido.** Medidor de sonido junto a la vista previa (picos y volumen en LUFS), transición suave de sonido entre clips y empalmes sin chasquidos.
- ✂️ **Recorte con IA (Beta).** Quita el fondo verde o azul de un video con CorridorKey, de Corridor Digital. Empieza desactivado: actívalo en Configuración → Funciones marcando *Mostrar funciones en prueba*. Es una descarga aparte de unos 7,6 GB y necesita una tarjeta NVIDIA RTX serie 30 o más nueva.
- 🧩 **Una app a tu manera.** En Configuración → Funciones, deja activadas solo las herramientas que usas, una por una o por perfil (Simple, Creador, Cine o Todo). Desactivar solo oculta: tus proyectos siguen saliendo iguales. En Componentes puedes ver, descargar, actualizar y quitar los programas extra, como ffmpeg.
- 🔔 **Avisos y recuperación.** La app avisa cuando termina una exportación, incluso con la ventana minimizada. Si se cierra de repente, al abrirla de nuevo ofrece recuperar el proyecto y la cola de exportación.
- 📷 **HDR del celular.** Los videos HDR (HLG y PQ, como los del iPhone) se reconocen y convierten solos.
- 🎨 **S-Log3, V-Log y N-Log con la exposición correcta.** Estos perfiles leían el video en la escala equivocada. Ahora son correctos, también en el plugin de DaVinci, por eso los proyectos antiguos que los usan pueden salir un poco distintos (hasta cerca de ⅓ de stop).
- 🛠️ **Correcciones.** El video vertical ya no se encoge en las calidades predefinidas; una exportación interrumpida ya no deja un archivo roto ni borra el anterior; *Optimizar el codificador para grano* vuelve a funcionar; y cancelar el cierre en la ventana de actualización ya no cierra la app.

## Versión 1.3.0 — 19 de octubre de 2026

**Modo Edición, Laboratorio de película y plugin para DaVinci Resolve.**

- 🎬 **Modo Edición.** Arriba en la ventana, cambia entre *Película* y *Edición*. En la edición, monta el video en pistas de imagen y sonido: importa videos, fotos y música, corta (tecla S), recorta, mueve, cambia la velocidad y usa transiciones como disolvencia y aparecer desde negro. Después, el modo Película aplica el look sobre el montaje.
- 🎨 **Color y luz de cada clip, sin complicaciones.** Botón *Automático*, ajustes rápidos (Más vivo, Cálido, Frío, B/N…), exposición, altas luces, sombras, ruedas de color, curva, color por rango (HSL), nitidez y claridad. Copia y pega los ajustes entre clips. Los monitores muestran histograma, forma de onda y vectorscopio.
- 🔊 **Sonido de cada clip.** Volumen, subir al inicio y bajar al final, graves y agudos, realzar la voz y reducir el ruido.
- 🧪 **Laboratorio.** Simula el camino de la película: el negativo, las luces de la positivadora y la copia, incluido el Technicolor de tres tiras. Separación de colores (Hue Split), densidad de rojos, verdes y azules, bleach bypass y más — con nuevos negativos y copias Kodak y Eastman.
- 📷 **Más cámaras.** Entradas Blackmagic Film Gen 5, ARRI LogC4 y Apple Log (iPhone).
- 🔌 **Plugin para DaVinci Resolve.** En Configuración → Plugin para DaVinci Resolve, instala el efecto *PeliculaConverter*, que funciona incluso en el Resolve gratuito, con todos los presets. Para Studio también hay DCTL y LUT.
- 📐 **Paneles que se adaptan.** Arrastra los divisores a gusto: nada desaparece ni queda cortado, y los looks se reorganizan en columnas.

## Versión 1.2.2 — 16 de octubre de 2026

**Pantalla completa más práctica y control del desenfoque de los formatos.**

- 🖥️ **Pantalla completa con el reproductor.** En la vista previa en pantalla completa, los controles de reproducción y la barra de la vista previa siguen en pantalla. Se mantiene la resolución que elegiste, y puedes cambiarla ahí mismo.
- 🎞️ **Desenfoque del formato.** La ligera suavidad del Super 8 y del 8 mm ahora tiene su propio interruptor en Película → Desenfoque del formato: desactívalo para mantener la nitidez del video o ajusta su intensidad.

## Versión 1.2.1 — 16 de octubre de 2026

**La actualización automática vuelve a funcionar en Windows.**

- 🔄 **Actualizar con un clic, de verdad.** Antes, la aplicación descargaba la versión nueva y se cerraba, pero no la instalaba. Ahora la instala y se vuelve a abrir sola, ya en la versión nueva.
- ℹ️ **¿Vienes de la 1.1.0 o la 1.2.0?** Esas versiones tienen el error, así que esta actualización se instala a mano una vez (descarga el instalador en el sitio o en GitHub). Desde entonces, todo ocurre solo.

## Versión 1.2.0 — 16 de octubre de 2026

**Mira cada detalle de la película.**

- 🖥️ **Vista previa en pantalla completa.** Un clic en el botón de pantalla completa (o F11) y solo el video ocupa la pantalla, en la resolución original, para revisar el grano, el halo y la nitidez de cerca. Esc sale.
- 🔍 **Zoom libre.** Usa las lupas − y +, las teclas + y − o la rueda del ratón para acercar o alejar cuanto quieras, de 10% a 1600%.
- 📂 **Abrir proyectos con el botón Abrir.** Los archivos .plc ahora aparecen junto con los videos y las imágenes.

## Versión 1.1.0 — 16 de octubre de 2026

**La aplicación ahora habla tu idioma y recuerda lo que estabas haciendo.**

- 🌎 **Portugués, inglés y español.** La primera vez eliges el idioma (viene marcado el de tu computadora). Puedes cambiarlo después en Configuración.
- 🎬 **Pantalla de bienvenida.** Al abrir la aplicación ves la versión, tus proyectos recientes y accesos directos para empezar: abrir un video, abrir un proyecto o usar la escena de prueba.
- 💾 **Proyectos (.plc).** Guarda tu edición y continúa donde lo dejaste: el video, el look, todos los ajustes, el tramo marcado y el cuadro en el que estabas. Haz doble clic en un archivo .plc para abrirlo directamente.
- 🔄 **Actualización automática.** Cuando salga una versión nueva, la aplicación te avisa y se actualiza sola con un clic, comprobando que el archivo descargado es el original.
- 📦 **Instaladores.** Además de la versión portátil, ahora hay instalador para Windows (.msi) y para Linux (.deb), con acceso directo en el menú y asociación de los archivos .plc.
- ✨ **Novedades.** ¡Esta ventana! Cada vez que actualices, verás aquí qué cambió, en lenguaje sencillo.

## Versión 1.0.0 — 16 de octubre de 2026

**La primera versión de PeliculaConverter.**

- 🎞️ **Aspecto de cine en cualquier video.** Colores de negativos y copias de cine, grano, el brillo rojizo alrededor de las luces (halación), bloom y mucho más, con vista previa al instante.
- 📽️ **33 looks listos.** Kodak Vision3, Fujifilm Eterna, Super 8 Kodachrome, 16 mm, 65 mm, IMAX, blanco y negro clásico, Portra, Velvia, CineStill y otros. Ajusta cualquiera y guárdalo como tuyo.
- 📏 **Formatos de 8 mm a IMAX.** Cada uno cambia el tamaño del grano, la nitidez, el temblor y la proporción de la imagen.
- 🎞 **Escaneo de la película.** Muestra la película completa, con las perforaciones iluminadas, el texto del borde y los cuadros vecinos, como en un escaneo real.
- 🕸️ **Defectos de película.** Polvo, rayas, un pelo en la ventanilla, manchas, destellos de fin de rollo, marcas de cambio de rollo y más: elige cuáles aparecen.
- 📤 **Exportación para todo.** MP4, MOV, MKV, WebM, AVI, GIF, másteres en ProRes y DNxHR y un formato sin pérdidas, con estimación de tiempo y cola de exportación.
- 🎨 **LUTs.** Usa los LUTs que ya tienes y convierte cualquier look en un LUT para otros programas.
- ⬇️ **ffmpeg automático.** Si tu computadora no tiene ffmpeg (o tiene uno muy antiguo), la aplicación lo descarga e instala por ti.
