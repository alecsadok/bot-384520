# BOT 384520

Monitoreo diario de noticias, eventos y normativa de interés para la **lechería argentina, la ganadería bovina y el ganado lechero**. El proyecto utiliza scraping de páginas públicas, RSS, Google News RSS y la Primera Sección del Boletín Oficial. **No utiliza inteligencia artificial ni APIs de modelos generativos.**

## Enfoque editorial

El radar prioriza:

- Lechería: tambos, producción y precio de la leche, industria láctea, eficiencia, instalaciones y sistemas de producción.
- Ganado lechero: reproducción, genética, crianza y recría de terneros y terneras, manejo del rodeo, sanidad, bienestar y medicina veterinaria.
- Ganadería bovina: noticias sanitarias, productivas, regulatorias y de manejo que afecten al ganado.
- Alimentación animal: nutrición, raciones, forrajes, pasturas, alfalfa, reservas, silaje y maíz destinado a silo o alimentación.
- Fenómeno El Niño: noticias específicas sobre El Niño/ENSO.

No se incorporan pronósticos meteorológicos, observaciones del tiempo ni alertas generales del SMN. Tampoco se priorizan noticias centradas exclusivamente en maíz u otros cultivos, mercados de granos o agricultura sin relación concreta con la alimentación del ganado. Se excluyen las publicaciones enfocadas en producción de carne, faena, feedlots o engorde, salvo que tengan un contenido claramente vinculado también con la lechería.

El filtro combina términos temáticos con reglas de exclusión. Una noticia sobre un cultivo puede ingresar cuando el contenido la relaciona expresamente con forrajes, silaje, nutrición o alimentación animal. Una noticia sobre El Niño puede ingresar como tema específico, aunque no sea una nota meteorológica de pronóstico.

## Qué genera

Cada ejecución crea o actualiza únicamente los archivos correspondientes a la fecha local del informe dentro de `informes/`:

- `bot384520_DDMMYY.html`
- `bot384520_DDMMYY.txt`

Ejemplo: `bot384520_101126.html` y `bot384520_101126.txt` para el 10/11/2026.

El filtro editorial toma publicaciones con fecha identificable dentro de las 24 horas anteriores al momento de ejecución. Se registra la fecha y hora de publicación, la fuente, el enlace original, las etiquetas temáticas y, cuando corresponde, la fecha futura de un evento. El archivo TXT contiene, para cada publicación, el título, la fecha de publicación y el enlace original, separados por líneas en blanco.

## Ejecución automática

El workflow `.github/workflows/radar-diario.yml` programa el script todos los días a las **23:00 de `America/Argentina/Cordoba`** y permite ejecución manual desde la pestaña **Actions** de GitHub.

El workflow instala dependencias, ejecuta el script y guarda los informes en el propio repositorio mediante un commit de `github-actions[bot]`. Requiere que GitHub Actions esté habilitado, que el archivo esté en la rama predeterminada y que el workflow tenga permiso `contents: write`. GitHub advierte que los eventos programados pueden demorarse en períodos de alta demanda; la hora indicada es la hora programada, no una garantía de inicio al segundo.

## Fuentes incluidas

### Portales de noticias y especialidad

Argentina.gob.ar, SENASA, Todo Lechería, Agrofy News/Lechería, Bichos de Campo, Agrolink, Clarín Rural, Agroverdad, Mundo Agro Córdoba, Agritotal, Revista Chacra/Infobae, La Nación Campo, UNL, Infocampo, Agroempresario, Portal Lechero, OCLA, FCV-UNL Eventos, Colegio de Médicos Veterinarios de Santa Fe, Mundo Rural, InfoLáctea, Secretaría de Agricultura, INDEC y Bolsa de Comercio de Rosario.

La presencia de una fuente generalista no implica que se incorporen todas sus publicaciones: cada resultado debe superar el filtro temático del BOT 384520.

### Búsqueda transversal

Consultas temáticas en Google News RSS, acotadas a la ventana reciente (`when:1d`). Las búsquedas se orientan a lechería, ganado bovino, sanidad, reproducción, alimentación animal y El Niño.

### Boletín Oficial

Consulta de la **Primera Sección – Legislación y Avisos Oficiales**. Se filtran normas vinculadas con lechería, bovinos, sanidad animal, trazabilidad, alimentación y producción ganadera. Para cada norma detectada se prepara un extracto y un copy orientativo mediante reglas determinísticas. Se deben verificar siempre el articulado, los sujetos alcanzados, los requisitos, los anexos y la vigencia en la publicación oficial antes de comunicar o tomar decisiones.

### Redes sociales

Se consultan perfiles públicos de Instagram y X sin autenticación. Cuando el HTML público expone enlaces a publicaciones, se intenta leer hasta dos posts por perfil para recuperar contenido y fecha. Estas plataformas pueden devolver páginas incompletas, páginas que requieren JavaScript, bloqueos o metadatos sin publicaciones. El informe identifica esos casos como acceso restringido/no verificable; no usa credenciales, no evade controles y no afirma haber leído publicaciones inaccesibles.

## Criterios de calidad y límites

- Solo se incluyen noticias y eventos con fecha de publicación identificable en las últimas 24 horas. Una página sin fecha fiable queda fuera, para no presentar material viejo como nuevo.
- No se inventan fechas de publicación. Las fechas futuras de eventos se extraen del texto cuando pueden identificarse.
- Se eliminan duplicados por título normalizado.
- Los resúmenes de noticias son extractivos, no generativos.
- El copy de normativa se construye con reglas y plantillas; no reemplaza asesoramiento legal ni revisión humana.
- El filtro editorial reduce resultados ajenos al ganado, pero una mención contextual puede requerir revisión humana. Conviene revisar titulares y enlaces antes de redistribuir el informe.
- El scraping está sujeto a cambios de diseño, disponibilidad, robots, límites de frecuencia, JavaScript y condiciones de cada fuente. Por eso cada informe incluye una tabla de estado de fuentes.
- El script no consulta servicios meteorológicos, no usa cookies privadas, login, cuentas de usuario ni servicios de IA.

## Prueba local

Requiere Python 3.11 o superior:

```bash
python -m pip install -r requirements.txt
python radar_lechero.py
```

Para desactivar las consultas a perfiles públicos de Instagram/X durante una prueba local:

```bash
RADAR_SCAN_SOCIAL=0 python radar_lechero.py
```

En Windows PowerShell:

```powershell
$env:RADAR_SCAN_SOCIAL="0"
python radar_lechero.py
```

## Dependencias

- `requests`: descarga de páginas y endpoints.
- `beautifulsoup4`: análisis de HTML.
- `feedparser`: RSS/Atom.
- `python-dateutil`: interpretación de fechas.
