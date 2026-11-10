# Radar

Recolección diaria de noticias, eventos, normativa y contexto meteorológico para comunicación del sector lechero argentino. El proyecto utiliza scraping de páginas públicas, RSS, Google News RSS, la Primera Sección del Boletín Oficial y endpoints públicos del SMN. **No utiliza inteligencia artificial ni APIs de modelos generativos.**

## Qué genera

Cada ejecución crea informes fechados en `informes/`:
- `noticiasinta_DDMMYY.html`
- `noticiasinta_DDMMYY.xls`

El filtro editorial toma publicaciones con fecha identificable dentro de las 24 horas anteriores a la ejecución. Registra fecha, fuente, enlace y etiquetas temáticas. El contexto meteorológico se presenta separado de las noticias.

## Ejecución automática

El workflow `.github/workflows/radar-diario.yml` está programado para las 23:00 de `America/Argentina/Cordoba` y permite ejecución manual desde **Actions**. Requiere Actions habilitado, el workflow en la rama predeterminada y permiso `contents: write`. Los horarios programados pueden demorarse por demanda de GitHub.

## Fuentes y cobertura

Incluye portales oficiales y sectoriales, consultas temáticas en Google News RSS, Primera Sección del Boletín Oficial, endpoints públicos del Servicio Meteorológico Nacional y perfiles públicos de Instagram/X solicitados. El acceso a redes sociales es limitado: si una plataforma no expone publicaciones públicamente, el informe lo indica como restringido/no verificable. No usa credenciales ni evade controles.

## Normativa

Para normas detectadas se prepara un extracto y un copy orientativo mediante reglas determinísticas. No se adjudican beneficios no comprobados. Antes de comunicar o tomar decisiones, verificar articulado, sujetos alcanzados, requisitos, anexos y vigencia en la publicación oficial.

## Criterios y límites

- Solo se incluyen noticias/eventos con fecha de publicación identificable dentro de las últimas 24 horas.
- Se eliminan duplicados por título normalizado.
- Los resúmenes son extractivos, no generativos.
- El scraping depende de cambios de diseño, disponibilidad, JavaScript, límites y condiciones de cada fuente.
- No usa cookies privadas, login ni servicios de IA.

## Instalación y prueba local

Requiere Python 3.11 o superior:

```bash
python -m pip install -r requirements.txt
python radar_lechero.py
```

Para omitir consultas sociales:

```bash
RADAR_SCAN_SOCIAL=0 python radar_lechero.py
```

## Dependencias

`requests`, `beautifulsoup4`, `feedparser`, `python-dateutil`, `xlwt`.
