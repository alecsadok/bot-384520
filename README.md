# BOT 384520

Recolección diaria de noticias, eventos, normativa y contexto meteorológico para comunicación del sector lechero argentino. El proyecto utiliza scraping de páginas públicas, RSS, Google News RSS, la Primera Sección del Boletín Oficial y endpoints públicos del SMN. **No utiliza inteligencia artificial ni APIs de modelos generativos.**

## Qué genera

Cada ejecución crea o actualiza únicamente los archivos correspondientes a la fecha local del informe dentro de `informes/`:

- `bot384520_DDMMYY.html`
- `bot384520_DDMMYY.txt`

Ejemplo: `bot384520_101126.html` y `bot384520_101126.txt` para el 10/11/2026.

El filtro editorial toma publicaciones con fecha identificable dentro de las 24 horas anteriores al momento de ejecución. Se registra la fecha y hora de publicación, la fuente, el enlace original, las etiquetas temáticas y, cuando corresponde, la fecha futura de un evento. El archivo TXT contiene, para cada publicación, el título, la fecha de publicación y el enlace original, separados por líneas en blanco. La información meteorológica se muestra en un bloque separado del HTML porque es una consulta de contexto actual y no una noticia publicada.

## Ejecución automática

El workflow `.github/workflows/radar-diario.yml` programa el script todos los días a las **23:00 de `America/Argentina/Cordoba`** y permite ejecución manual desde la pestaña **Actions** de GitHub.

El workflow instala dependencias, ejecuta el script y guarda los informes en el propio repositorio mediante un commit de `github-actions[bot]`. Requiere que GitHub Actions esté habilitado, que el archivo esté en la rama predeterminada y que el workflow tenga permiso `contents: write`. GitHub advierte que los eventos programados pueden demorarse en períodos de alta demanda; la hora indicada es la hora programada, no una garantía de inicio al segundo.

## Instalación en `el repositorio configurado`

Copiar al directorio raíz del repositorio:

```text
radar_lechero.py
requirements.txt
.github/workflows/radar-diario.yml
.gitignore
README.md
```

Crear la carpeta `informes/` (puede contener un `.gitkeep` para que exista antes de la primera ejecución). Luego hacer commit y push a la rama por defecto. El primer informe se genera al ejecutar manualmente el workflow o en el siguiente horario programado.

## Fuentes incluidas

### Portales de noticias y especialidad

Argentina.gob.ar, SENASA, Todo Lechería, Agrofy News/Lechería, Bichos de Campo, Agrolink, Clarín Rural, Agroverdad, Mundo Agro Córdoba, Agritotal, Revista Chacra/Infobae, La Nación Campo, UNL, Infocampo, Agroempresario, Portal Lechero, OCLA, FCV-UNL Eventos, Colegio de Médicos Veterinarios de Santa Fe, Mundo Rural, InfoLáctea, Secretaría de Agricultura, INDEC y Bolsa de Comercio de Rosario.

### Búsqueda transversal

Consultas temáticas en Google News RSS, acotadas a la ventana reciente (`when:1d`). Esto agrega medios y publicaciones que no están en la lista fija de portales.

### Boletín Oficial

Consulta de la **Primera Sección – Legislación y Avisos Oficiales**. Busca publicaciones vinculadas con lechería, bovinos, ganadería, sanidad animal, agricultura, trazabilidad, producción, forrajes, semillas, insumos, financiamiento, comercialización, impuestos, energía y normativa agropecuaria.

Para cada norma detectada prepara un extracto y un copy institucional de carácter orientativo con reglas determinísticas. El copy no adjudica automáticamente un beneficio: distingue posibles efectos sobre financiamiento, alivio fiscal, sanidad/trazabilidad, costos o comercialización y advierte cuando el texto disponible no permite identificar un beneficio directo. Se deben verificar siempre el articulado, los sujetos alcanzados, los requisitos, los anexos y la vigencia en la publicación oficial antes de comunicar o tomar decisiones.

### Clima y tiempo

Endpoints públicos del Servicio Meteorológico Nacional:

- Observaciones: `https://ws.smn.gob.ar/map_items/weather`
- Pronóstico: `https://ws.smn.gob.ar/map_items/forecast/3`
- Alertas: `https://ws.smn.gob.ar/alerts/type/AL`

Se intenta identificar Rafaela, Santa Fe, además de alertas regionales. La cobertura depende de la disponibilidad y estructura de la respuesta del servicio en cada ejecución.

### Redes sociales solicitadas

Se incluyen los perfiles públicos de Instagram y X enumerados en la solicitud. Se consultan sin autenticación y, cuando el HTML público expone enlaces a publicaciones, se intenta leer hasta dos posts por perfil para rescatar contenido y fecha. Instagram y X pueden devolver páginas incompletas, páginas que requieren JavaScript, bloqueos o metadatos de perfil sin publicaciones. El informe identifica esos casos como acceso restringido/no verificable; no usa credenciales, no evade controles y no afirma haber leído publicaciones inaccesibles. Para monitoreo confiable y completo de esas redes se necesitarían APIs oficiales y sus permisos correspondientes.

## Criterios de calidad y límites

- Solo se incluyen noticias y eventos con fecha de publicación identificable en las últimas 24 horas. Una página sin fecha fiable queda fuera, para no presentar material viejo como nuevo.
- No se inventan fechas de publicación. Las fechas futuras de eventos se extraen del texto cuando pueden identificarse.
- Se eliminan duplicados por título normalizado.
- Los resúmenes de noticias son extractivos, no generativos.
- El copy de normativa se construye con reglas y plantillas; no reemplaza asesoramiento legal ni revisión humana.
- El scraping está sujeto a cambios de diseño, disponibilidad, robots, límites de frecuencia, JavaScript y condiciones de cada fuente. Por eso cada informe incluye una tabla de estado de fuentes.
- El script no usa cookies privadas, login, cuentas de usuario ni servicios de IA.

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
