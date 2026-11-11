#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOT 384520: monitoreo de noticias, eventos y normativa sobre lechería y ganado bovino.

Combina fuentes públicas, RSS gratuito y análisis con un modelo de IA abierto
ejecutado localmente. No utiliza APIs de inferencia remotas.
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuración general
# ---------------------------------------------------------------------------
TZ_NAME = "America/Argentina/Cordoba"
TZ = ZoneInfo(TZ_NAME)
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "informes"
LOG = logging.getLogger("bot_384520")
USER_AGENT = "BOT-384520/1.0"
REQUEST_TIMEOUT = (15, 35)
MAX_WORKERS = 4
MIN_HOST_INTERVAL = 1.5
MAX_LINKS_PER_SOURCE = 12
MAX_FEED_ITEMS_PER_SOURCE = 15
MAX_GOOGLE_NEWS_ITEMS = 12
MAX_GOOGLE_NEWS_TOTAL = 90
NEWS_WINDOW_DAYS = 7
MAX_GOOGLE_NEWS_ENRICHMENTS = 36

# Fuentes directas: INTA tiene prioridad; se complementa con organismos,
# universidades, observatorios y medios sectoriales. Los resultados siempre
# deben superar el filtro temático y la revisión editorial.
WEB_SOURCES: list[dict[str, str]] = [
    {"name": "INTA – Noticias nacionales", "url": "https://www.argentina.gob.ar/inta/noticias", "kind": "inta"},
    {"name": "INTA – Centro Regional Santa Fe", "url": "https://www.argentina.gob.ar/inta/cr-santa-fe/noticias", "kind": "inta"},
    {"name": "INTA – Centro Regional Entre Ríos", "url": "https://www.argentina.gob.ar/inta/cr-entre-rios/noticias", "kind": "inta"},
    {"name": "INTA – Centro Regional Córdoba", "url": "https://www.argentina.gob.ar/inta/cr-cordoba/noticias", "kind": "inta"},
    {"name": "INTA – Centro Regional Corrientes", "url": "https://www.argentina.gob.ar/inta/cr-corrientes/noticias", "kind": "inta"},
    {"name": "INTA – Centro Regional Misiones", "url": "https://www.argentina.gob.ar/inta/cr-misiones/noticias", "kind": "inta"},
    {"name": "SENASA", "url": "https://www.argentina.gob.ar/senasa", "kind": "institucional"},
    {"name": "Secretaría de Agricultura", "url": "https://www.argentina.gob.ar/economia/agricultura", "kind": "institucional"},
    {"name": "CONICET – Prensa", "url": "https://www.conicet.gov.ar/prensa/", "kind": "academica"},
    {"name": "UNL – Noticias", "url": "https://www.unl.edu.ar/noticias/", "kind": "academica"},
    {"name": "FCV UNL – Eventos", "url": "https://www.fcv.unl.edu.ar/eventos/", "kind": "academica"},
    {"name": "OCLA", "url": "https://www.ocla.org.ar/", "kind": "organizacion_sectorial"},
    {"name": "Todo Lechería", "url": "https://www.todolecheria.com.ar/noticias/", "kind": "especializada"},
    {"name": "Agrofy – Lechería", "url": "https://news.agrofy.com.ar/lecheria", "kind": "especializada"},
    {"name": "Agrofy News", "url": "https://news.agrofy.com.ar/", "kind": "agro"},
    {"name": "Bichos de Campo", "url": "https://bichosdecampo.com/", "kind": "agro"},
    {"name": "Agrolink", "url": "https://agrolink.com.ar/ultimas-noticias/", "kind": "agro"},
    {"name": "Clarín Rural", "url": "https://www.clarin.com/rural/", "kind": "agro"},
    {"name": "Agroverdad", "url": "https://agroverdad.com.ar/todas-las-noticias", "kind": "agro"},
    {"name": "Mundo Agro Córdoba", "url": "https://mundoagrocba.com.ar/", "kind": "agro"},
    {"name": "Agritotal", "url": "https://www.agritotal.com/", "kind": "agro"},
    {"name": "Infobae – Revista Chacra", "url": "https://www.infobae.com/revista-chacra/", "kind": "agro"},
    {"name": "La Nación – Campo", "url": "https://www.lanacion.com.ar/economia/campo/", "kind": "agro"},
    {"name": "Infocampo", "url": "https://www.infocampo.com.ar/", "kind": "agro"},
    {"name": "Agroempresario", "url": "https://agroempresario.com/", "kind": "agro"},
    {"name": "Portal Lechero", "url": "https://portalechero.com/", "kind": "especializada"},
    {"name": "Colegio de Médicos Veterinarios de Santa Fe", "url": "https://cmver.com.ar/", "kind": "profesional"},
    {"name": "Mundo Rural", "url": "https://mundorural.com.ar/", "kind": "agro"},
    {"name": "InfoLáctea", "url": "https://www.infolactea.com.ar/", "kind": "especializada"},
    {"name": "INDEC", "url": "https://www.indec.gob.ar/", "kind": "estadistica"},
    {"name": "Bolsa de Comercio de Rosario", "url": "https://www.bcr.com.ar/es/mercados/investigacion-y-desarrollo/informativo-semanal", "kind": "economia"},
]

# El Boletín Oficial se procesa por separado para leer la Primera Sección.
BOLETIN_URL = "https://www.boletinoficial.gob.ar/seccion/primera"
BOLETIN_HOME = "https://www.boletinoficial.gob.ar/"

# La lectura automatizada de Instagram/X no es una fuente estable ni completa.
# Se deja vacía por defecto; solo se activa si se agregan perfiles y el contenido
# público puede verificarse sin iniciar sesión ni eludir controles.
SOCIAL_PROFILES: list[str] = []

# ---------------------------------------------------------------------------
# Diccionario temático. Se puede ampliar en keywords_extra.txt sin tocar código.
# ---------------------------------------------------------------------------
KEYWORDS: dict[str, list[str]] = {
    "Lechería y producción láctea": [
        "lechería", "vacas", "ganado", "sector lechero",
        "actividad lechera", "producción lechera", "producción de leche", "producción láctea",
        "cadena láctea", "cadena de valor láctea", "industria láctea", "industria lechera",
        "tambo", "tambos", "establecimiento lechero", "establecimientos lecheros",
        "establecimiento tambero", "establecimientos tamberos", "productor lechero",
        "productores lecheros", "productor tambero", "productores tamberos", "cuenca lechera",
        "cuencas lecheras", "sistemas de producción de leche", "sistemas lecheros",
        "sistemas pastoriles", "tambo pastoril", "tambo estabulado", "tambo robotizado",
        "tambo automatizado", "ordeño", "ordeño mecánico", "ordeño robotizado", "sala de ordeño",
        "equipos de ordeño", "máquinas de ordeño", "instalaciones de ordeño", "rutina de ordeño",
        "eficiencia de ordeño", "bienestar animal en el tambo", "gestión del tambo", "gestión lechera",
        "administración de tambos", "manejo del rodeo lechero", "eficiencia productiva", "productividad lechera",
    ],
    "Leche y productos lácteos": [
        "leche", "leche cruda", "leche bovina", "leche fluida", "leche refrigerada", "leche pasteurizada",
        "leche ultrapasteurizada", "leche en polvo", "leche concentrada", "leche en sachet",
        "productos lácteos", "productos derivados de la leche", "derivados lácteos", "quesos", "yogur",
        "manteca", "crema de leche", "dulce de leche", "suero lácteo", "lactosuero", "proteínas lácteas",
        "grasa láctea", "sólidos lácteos", "composición de la leche", "calidad de leche",
        "calidad higiénico-sanitaria de la leche", "inocuidad de productos lácteos", "análisis de leche",
        "recuento de células somáticas", "recuento bacteriano", "células somáticas",
        "residuos de antibióticos en leche", "adulteración de leche", "contaminantes en leche",
        "refrigeración de leche", "conservación de leche", "transporte de leche", "recepción de leche", "leche de calidad",
    ],
    "Rodeo lechero y reproducción": [
        "rodeo lechero", "vacas lecheras", "vacas en producción", "vacas en ordeño", "vacas secas",
        "vacas de descarte", "descarte de vacas", "vaquillonas", "vaquillonas lecheras", "reposición de vientres",
        "reposición de vaquillonas", "terneros de tambo", "terneras de tambo", "crianza artificial de terneros",
        "crianza de terneras", "recría de vaquillonas", "reproducción bovina", "reproducción en rodeos lecheros",
        "eficiencia reproductiva", "inseminación artificial", "inseminación artificial a tiempo fijo",
        "transferencia embrionaria", "genética lechera", "mejoramiento genético bovino", "selección genética",
        "biotecnología reproductiva", "fertilidad", "índices reproductivos", "parto", "período de transición",
        "período seco", "lactancia", "curva de lactancia", "producción individual", "control lechero",
        "control de producción de leche",
    ],
    "Sanidad y bienestar del rodeo": [
        "sanidad del rodeo lechero", "salud del rodeo", "sanidad bovina", "mastitis", "mastitis bovina",
        "mastitis ambiental", "mastitis contagiosa", "leucosis bovina", "brucelosis bovina", "tuberculosis bovina",
        "queratoconjuntivitis infecciosa bovina", "enfermedades del ganado lechero", "enfermedades de las vacas lecheras",
        "enfermedades de los terneros", "salud de terneros", "bienestar animal", "bienestar animal en bovinos",
        "bienestar de vacas lecheras", "estrés calórico", "estrés térmico", "índice de temperatura y humedad", "ith",
        "mortalidad de terneros", "mortalidad en rodeos lecheros", "vacunación bovina", "productos veterinarios",
        "medicamentos veterinarios", "antibióticos veterinarios", "residuos de medicamentos en leche",
        "trazabilidad animal", "identificación animal", "identificación electrónica bovina", "identificación electrónica animal",
    ],
    "Alimentación, nutrición y forrajes": [
        "alimentación de vacas lecheras", "nutrición de vacas lecheras", "nutrición bovina", "alimentación del rodeo lechero",
        "dieta de vacas lecheras", "ración para vacas lecheras", "balanceado para vacas lecheras", "suplementación",
        "suplementación alimenticia", "suplementación de vacas lecheras", "concentrados", "forrajes", "reservas forrajeras",
        "heno", "pasturas", "pasturas implantadas", "pasturas megatérmicas", "alfalfa", "verdeos", "maíz para silo",
        "sorgo forrajero", "calidad de forrajes", "calidad nutricional", "balance nutricional", "eficiencia alimenticia",
        "conversión alimenticia", "agua para consumo animal", "bebederos", "comederos", "alimentación de terneros",
        "sustitutos lácteos", "reemplazantes lácteos", "calostro",
    ],
    "Economía y comercialización": [
        "economía lechera", "economía del tambo", "costos de producción de leche", "costos de producción lechera",
        "costo por litro de leche", "precio de la leche", "precio al productor", "precio de leche cruda", "mercado lácteo",
        "mercado de la leche", "comercialización de leche", "comercialización de productos lácteos",
        "industria procesadora de leche", "exportación de productos lácteos", "importación de productos lácteos",
        "retenciones a productos lácteos", "derechos de exportación de lácteos", "rentabilidad del tambo",
        "financiamiento para tambos", "créditos para productores lecheros", "emergencia agropecuaria para productores lecheros",
        "precio internacional de la leche", "exportaciones lácteas", "mercado internacional de lácteos",
    ],
    "Regulación y organismos": [
        "senasa", "secretaría de agricultura", "registro de establecimientos lácteos",
        "habilitación de establecimientos lácteos", "habilitación de tambos", "habilitación de plantas lácteas",
        "transporte de productos lácteos", "buenas prácticas lecheras", "buenas prácticas de ordeño",
        "buenas prácticas de manufactura", "inocuidad alimentaria", "higiene del tambo", "higiene de la leche",
        "fiscalización de productos lácteos", "regulación de productos lácteos", "rotulado de productos lácteos",
        "código alimentario argentino", "ren spa", "renspa", "sigsa", "documento de tránsito electrónico",
        "identificación animal", "sanidad animal", "registro sanitario", "emergencia agropecuaria",
        "declaración de emergencia", "declaracion de emergencia", "régimen de promoción", "regimen de promocion",
        "alivio fiscal", "reducción de impuestos", "reduccion de impuestos", "crédito", "credito", "financiamiento",
        "línea de crédito", "linea de credito", "comercio exterior", "derechos de exportación", "derechos de exportacion",
        "retenciones", "exportación", "exportacion", "importación", "importacion", "aranceles", "semillas",
        "fertilizantes", "fitosanitarios", "alimentos balanceados", "zoonosis", "transporte de animales",
        "transporte de alimentos", "faena bovina", "ganadería", "ganaderia", "agropecuario", "agropecuaria",
        "tarifa eléctrica", "tarifa electrica", "combustibles", "energía", "energia", "costos logísticos",
        "costos logisticos", "iva", "industria alimenticia",
    ],
    "Ganadería bovina y manejo del rodeo": [
        "ganadería bovina", "ganado bovino", "ganadería", "ganado", "bovino", "bovina", "bovinos",
        "bovinas", "vacuno", "vacunos", "rodeo bovino", "manejo del rodeo", "cría bovina",
        "recría bovina", "ternero", "terneros", "ternera", "terneras", "vaquillonas",
        "sanidad animal", "sanidad bovina", "bienestar animal", "bienestar bovino",
        "nutrición animal", "nutrición bovina", "alimentación animal", "alimentación bovina",
        "medicina veterinaria", "veterinaria", "identificación animal", "trazabilidad animal",
        "reproducción bovina", "inseminación artificial", "maíz para silo", "silo de maíz",
        "silaje", "maíz picado", "sorgo forrajero", "forrajes", "reservas forrajeras",
        "ración bovina", "raciones bovinas", "ración para vacas", "raciones para vacas",
        "alimento para el ganado", "alimentos para el ganado", "balanceado bovino", "grano húmedo",
        "pasturas", "alfalfa", "suplementación", "estrés calórico", "estrés térmico",
        "golpe de calor", "sequía", "inundación", "falta de agua", "escasez de agua",
    ],
    "Fenómeno El Niño": [
        "el niño", "fenómeno el niño", "evento el niño", "enso",
    ],
}

EVENT_WORDS = [
    "jornada", "jornadas", "curso", "cursos", "capacitación", "capacitacion", "seminario", "congreso",
    "encuentro", "taller", "día de campo", "dia de campo", "webinar", "charla", "conferencia", "expo",
    "exposición", "exposicion", "feria", "inscripción", "inscripcion", "convocatoria", "reunión", "reunion",
    "demostración", "demostracion", "entrenamiento", "actualización", "actualizacion", "foro",
]
BROAD_TERMS = {"leche", "vaca", "vacas", "ganado", "campo", "agro", "rural", "producción", "produccion"}

# ---------------------------------------------------------------------------
# Modelos y utilidades
# ---------------------------------------------------------------------------
@dataclass
class Item:
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str = ""
    section: str = "Noticia"
    tags: list[str] | None = None
    event_date: str = ""
    event_location: str = ""
    event_organizer: str = ""
    event_date_verified: bool = False
    date_label: str = "Publicado"
    legal_copy: str = ""
    relevance: int = 0
    discovered_via_google_news: bool = False
    editorial_group: str = "Otros medios y fuentes"
    editorial_priority: int = 50
    instagram_angle: str = ""
    format_suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        d["tags"] = self.tags or []
        return d



# Control de frecuencia por dominio: evita ráfagas cuando se consultan muchos
# artículos de un mismo medio. No intenta ocultar ni alterar la identidad del bot.
_HOST_REQUEST_LOCK = threading.Lock()
_HOST_LAST_REQUEST: dict[str, float] = {}

def wait_for_host(url: str) -> None:
    host = urlparse(url).netloc.lower()
    with _HOST_REQUEST_LOCK:
        now_mono = time.monotonic()
        previous = _HOST_LAST_REQUEST.get(host, 0.0)
        remaining = MIN_HOST_INTERVAL - (now_mono - previous)
        if remaining > 0:
            time.sleep(remaining)
        _HOST_LAST_REQUEST[host] = time.monotonic()

def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9,en;q=0.5"})
    return session


def normalize(text: str) -> str:
    text = html.unescape(text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text(value: str, limit: int = 900) -> str:
    value = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    value = html.unescape(re.sub(r"\s+", " ", value)).strip()
    return value[:limit]


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        raw = raw.replace("Z", "+00:00")
        # ISO-8601 debe parsearse sin dayfirst: de otro modo 2026-11-10
        # puede interpretarse erróneamente como 11 de octubre.
        if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|\s|$)", raw):
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt.astimezone(TZ)
        months = {
            "enero": "January", "febrero": "February", "marzo": "March", "abril": "April",
            "mayo": "May", "junio": "June", "julio": "July", "agosto": "August",
            "septiembre": "September", "setiembre": "September", "octubre": "October",
            "noviembre": "November", "diciembre": "December",
        }
        low = normalize(raw)
        for es, en in months.items():
            low = re.sub(rf"\b{normalize(es)}\b", en, low)
        # dateutil con fuzzy rescata fechas que aparecen dentro de etiquetas o frases.
        try:
            dt = date_parser.parse(low, fuzzy=True, dayfirst=True)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def extract_text_dates(text: str) -> list[datetime]:
    results: list[datetime] = []
    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de)?\s+\d{4}\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text or "", flags=re.IGNORECASE):
            dt = parse_datetime(match)
            if dt:
                results.append(dt)
    return results


def all_keywords() -> list[str]:
    return sorted({kw for group in KEYWORDS.values() for kw in group}, key=len, reverse=True)


def contains_term(text: str, term: str) -> bool:
    normalized_term = normalize(term)
    # Las siglas cortas requieren límites de palabra: "ENSO" no debe
    # coincidir dentro de "consenso" ni "ITH" dentro de "within".
    if normalized_term in {"enso", "ith"}:
        return re.search(rf"\b{re.escape(normalized_term)}\b", text) is not None
    return normalized_term in text


# Filtro editorial: una mención genérica al campo o a un cultivo no alcanza.
DAIRY_EDITORIAL_TERMS = [
    "leche", "lácteo", "lechero", "lechera", "lechería", "tambo", "ordeño",
    "vacas lecheras", "rodeo lechero", "producción láctea", "producción de leche",
    "industria láctea", "terneros de tambo", "terneras de tambo",
]
LIVESTOCK_EDITORIAL_TERMS = [
    "ganadería", "ganado", "bovino", "bovina", "bovinos", "bovinas", "vacuno", "vacunos",
    "rodeo", "vaca", "vacas", "ternero", "terneros", "ternera", "terneras", "vaquillonas",
    "sanidad animal", "sanidad bovina", "bienestar animal", "mastitis", "brucelosis",
    "tuberculosis bovina", "queratoconjuntivitis", "nutrición bovina", "nutrición animal",
    "alimentación bovina", "alimentación animal", "medicina veterinaria", "veterinaria",
    "reproducción bovina", "trazabilidad animal", "identificación animal",
    "forrajes", "reservas forrajeras", "pasturas", "alfalfa", "maíz para silo",
    "silo de maíz", "silaje", "maíz picado", "sorgo forrajero", "suplementación",
    "ración bovina", "raciones bovinas", "ración para vacas", "raciones para vacas",
    "alimento para el ganado", "alimentos para el ganado", "balanceado bovino", "grano húmedo",
    "estrés calórico", "estrés térmico", "golpe de calor", "índice de temperatura y humedad",
    "ith",
]
SPECIFIC_LIVESTOCK_TERMS = [
    term for term in LIVESTOCK_EDITORIAL_TERMS
    if term not in ("ganadería", "ganado", "veterinaria")
]
CLIMATE_IMPACT_TERMS = [
    "el niño", "enso", "sequía", "inundación", "falta de agua", "escasez de agua",
    "lluvia", "lluvias", "precipitaciones", "pronóstico", "agrometeorología",
    "meteorológico", "meteorológica",
]
FEED_CONTEXT_TERMS = [
    "maíz para silo", "silo de maíz", "silaje", "maíz picado", "sorgo forrajero",
    "ración bovina", "raciones bovinas", "ración para vacas", "alimento para el ganado",
    "nutrición bovina", "alimentación bovina", "forrajes", "reservas forrajeras",
    "pasturas", "alfalfa", "suplementación", "cadena forrajera",
]
MEAT_FOCUS_TERMS = [
    "carne bovina", "carne vacuna", "carne de res", "mercado de carnes",
    "exportación de carne", "exportaciones de carne", "cortes vacunos",
    "faena bovina", "faena de bovinos", "faena de vacunos", "feedlot", "feedlots",
    "engorde a corral", "novillo", "novillos", "novillito", "novillitos",
    "ganadería de carne", "ganado para carne", "producción de carne bovina",
]
CROP_FOCUS_TERMS = [
    "maíz", "soja", "trigo", "girasol", "cebada", "sorgo granífero",
    "mercado de granos", "cosecha de maíz", "siembra de maíz", "cosecha de soja",
    "siembra de soja", "rendimiento de maíz", "exportación de granos",
]

def editorially_relevant(text: str) -> bool:
    ntext = normalize(text)
    dairy = any(contains_term(ntext, term) for term in DAIRY_EDITORIAL_TERMS)
    livestock = any(contains_term(ntext, term) for term in LIVESTOCK_EDITORIAL_TERMS)
    specific_livestock = any(contains_term(ntext, term) for term in SPECIFIC_LIVESTOCK_TERMS)
    climate = any(contains_term(ntext, term) for term in CLIMATE_IMPACT_TERMS)
    feed_context = any(contains_term(ntext, term) for term in FEED_CONTEXT_TERMS)
    meat = any(contains_term(ntext, term) for term in MEAT_FOCUS_TERMS)
    crop = any(contains_term(ntext, term) for term in CROP_FOCUS_TERMS)

    if meat and not dairy:
        return False
    # Clima y El Niño solo interesan si la fuente explica un efecto concreto
    # sobre tambos, animales, pasturas o alimentación.
    if climate and not (dairy or specific_livestock or feed_context):
        return False
    if crop and not (dairy or specific_livestock or feed_context):
        return False
    return dairy or livestock or feed_context

def classify(text: str) -> tuple[list[str], int]:
    ntext = normalize(text)
    if not editorially_relevant(ntext):
        return [], 0
    tags: list[str] = []
    score = 0
    for category, terms in KEYWORDS.items():
        hits = [term for term in terms if contains_term(ntext, term)]
        if hits:
            tags.append(category)
            score += sum(3 if len(normalize(term).split()) > 1 else 1 for term in hits[:12])
    matched = [kw for kw in all_keywords() if contains_term(ntext, kw)]
    specific = [kw for kw in matched if normalize(kw) not in BROAD_TERMS]
    if not specific and len(matched) < 2:
        return [], 0
    return tags, score


def is_relevant(text: str, min_score: int = 1) -> tuple[bool, list[str], int]:
    tags, score = classify(text)
    return score >= min_score, tags, score


def extract_jsonld_dates(soup: BeautifulSoup) -> list[datetime]:
    values: list[datetime] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    if node.get(key):
                        dt = parse_datetime(node[key])
                        if dt:
                            values.append(dt)
                for val in node.values():
                    if isinstance(val, (dict, list)):
                        stack.append(val)
            elif isinstance(node, list):
                stack.extend(node)
    return values


def extract_published_date(soup: BeautifulSoup, fallback: datetime | None = None) -> datetime | None:
    # Prioridad a campos semánticos de publicación; no usar fechas de modificación
    # porque una nota antigua actualizada hoy no debe entrar en la ventana de 24 h.
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if "modified" in key or "updated" in key:
            continue
        if any(k in key for k in ("published_time", "datepublished", "pubdate", "publishdate", "publication_date")):
            dt = parse_datetime(tag.get("content"))
            if dt:
                return dt
    jsonld_dates = extract_jsonld_dates(soup)
    if jsonld_dates:
        return min(jsonld_dates)
    for tag in soup.find_all("time"):
        dt = parse_datetime(tag.get("datetime") or tag.get_text(" ", strip=True))
        if dt:
            return dt
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if "modified" in key or "updated" in key:
            continue
        if any(k in key for k in ("date", "created", "publication")):
            dt = parse_datetime(tag.get("content"))
            if dt:
                return dt
    body = clean_text(soup.get_text(" ", strip=True), 10000)
    text_dates = extract_text_dates(body[:3000])
    if text_dates:
        return text_dates[0]
    return fallback


def is_within_window(dt: datetime | None, now: datetime, hours: int = NEWS_WINDOW_DAYS * 24) -> bool:
    if dt is None:
        return False
    return now - timedelta(hours=hours) <= dt <= now + timedelta(minutes=10)


def guess_event_date(text: str, now: datetime) -> str:
    dates = extract_text_dates(text)
    future = [dt for dt in dates if dt.date() >= now.date() and dt <= now + timedelta(days=365)]
    if future:
        return min(future).strftime("%d/%m/%Y")
    return ""


def summarize(text: str, max_chars: int = 320) -> str:
    text = clean_text(text, 8000)
    if not text:
        return "No se encontró una descripción textual accesible en la fuente. Consultar el enlace original."
    # Descarta navegación, rótulos y encabezados excesivamente cortos.
    parts = re.split(r"(?<=[.!?])\s+", text)
    selected = " ".join(p for p in parts if len(p.strip()) > 35)[:max_chars].strip()
    return selected or text[:max_chars]


def absolute_url(base: str, href: str) -> str:
    return urljoin(base, href.strip())


def host_matches(a: str, b: str) -> bool:
    try:
        ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
        return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)
    except Exception:
        return False


def fetch(url: str, timeout: tuple[int, int] = REQUEST_TIMEOUT) -> tuple[str, str, int]:
    try:
        wait_for_host(url)
        response = make_session().get(url, timeout=timeout, allow_redirects=True)
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            return "", response.url, response.status_code
        if "html" not in content_type.lower() and "xml" not in content_type.lower() and "text" not in content_type.lower():
            return "", response.url, response.status_code
        response.encoding = response.apparent_encoding or response.encoding
        return response.text, response.url, response.status_code
    except requests.RequestException as exc:
        LOG.debug("No se pudo consultar %s: %s", url, exc)
        return "", url, 0


def discover_feed_urls(page_url: str, html_doc: str) -> list[str]:
    soup = BeautifulSoup(html_doc, "html.parser")
    feeds = []
    for link in soup.find_all("link", href=True):
        typ = (link.get("type") or "").lower()
        rel = " ".join(link.get("rel", [])).lower()
        if "alternate" in rel and any(x in typ for x in ("rss", "atom", "xml")):
            feeds.append(absolute_url(page_url, link["href"]))
    # Respaldo acotado para WordPress cuando no hay autodiscovery.
    generator = soup.find("meta", attrs={"name": "generator"})
    if not feeds and generator and "wordpress" in normalize(generator.get("content", "")):
        parsed = urlparse(page_url)
        feeds.append(f"{parsed.scheme}://{parsed.netloc}/feed/")
    return list(dict.fromkeys(feeds))[:4]


def parse_feed(feed_url: str, source_name: str, now: datetime) -> list[Item]:
    feed_raw, _, _ = fetch(feed_url)
    if not feed_raw:
        return []
    parsed = feedparser.parse(feed_raw)
    output: list[Item] = []
    for entry in parsed.entries[:MAX_FEED_ITEMS_PER_SOURCE]:
        title = clean_text(entry.get("title", ""), 300)
        link = entry.get("link", "")
        if not title or not link:
            continue
        pub = None
        for key in ("published_parsed", "updated_parsed"):
            st = entry.get(key)
            if st:
                try:
                    pub = datetime(*st[:6], tzinfo=timezone.utc).astimezone(TZ)
                    break
                except Exception:
                    pass
        if pub is None:
            pub = parse_datetime(entry.get("published") or entry.get("updated"))
        summary = clean_text(entry.get("summary", ""), 700)
        text = f"{title} {summary}"
        relevant, tags, score = is_relevant(text)
        if not relevant or not is_within_window(pub, now):
            continue
        is_event = any(normalize(w) in normalize(text) for w in EVENT_WORDS)
        output.append(Item(
            title=title,
            url=link,
            source=source_name,
            published_at=pub,
            summary=summary or summarize(text),
            section="Evento" if is_event else "Noticia",
            tags=tags,
            event_date=guess_event_date(text, now),
            relevance=score,
        ))
    return output


def candidate_links(page_url: str, page_html: str, now: datetime) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    found: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        title = clean_text(anchor.get_text(" ", strip=True), 260)
        href = absolute_url(page_url, anchor["href"])
        if len(title) < 18 or len(title) > 260:
            continue
        if not href.startswith("http") or not host_matches(href, page_url):
            continue
        parsed_path = urlparse(href).path.lower()
        if any(x in parsed_path for x in ("/tag/", "/category/", "/author/", "/contact", "/login", "/wp-json", "/page/")):
            continue
        if href.rstrip("/") == page_url.rstrip("/"):
            continue
        context_node = anchor
        for _ in range(3):
            if context_node.parent:
                context_node = context_node.parent
        context = clean_text(context_node.get_text(" ", strip=True), 700)
        relevant, tags, score = is_relevant(f"{title} {context}")
        # Los sitios de eventos y especializados admiten títulos más generales, siempre que el contexto lo vincule.
        if not relevant:
            continue
        if href not in found:
            found[href] = (title, context)
    return [(u, t, c) for u, (t, c) in list(found.items())[:MAX_LINKS_PER_SOURCE]]


def parse_article(
    url: str,
    title_hint: str,
    context_hint: str,
    source_name: str,
    now: datetime,
    allow_upcoming_event: bool = True,
    fallback_published_at: datetime | None = None,
) -> Item | None:
    raw, final_url, status = fetch(url)
    if not raw:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    title = clean_text(
        (og_title.get("content") if og_title else "")
        or (h1.get_text(" ", strip=True) if h1 else "")
        or title_hint,
        300,
    )
    if len(title) < 10:
        title = title_hint

    description = ""
    for attrs in ({"property": "og:description"}, {"name": "description"}, {"name": "twitter:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 900)
            break

    article_node = soup.find("article") or soup.find("main") or soup.body or soup
    body_text = clean_text(article_node.get_text(" ", strip=True), 12000)
    text = f"{title} {description} {context_hint} {body_text}"
    if ai_hard_excluded(text):
        return None
    relevant, tags, score = is_relevant(text)

    event_text = f"{title} {description} {context_hint} {body_text[:7000]}"
    is_event = any(normalize(word) in normalize(event_text) for word in EVENT_WORDS)
    event_date = guess_event_date(event_text, now) if is_event else ""
    event_dt = parse_datetime(event_date) if event_date else None
    upcoming_event = bool(
        allow_upcoming_event
        and is_event
        and event_dt
        and now.date() <= event_dt.date() <= (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).date()
        and ai_event_date_visible(event_dt, event_text)
    )

    if not relevant and not upcoming_event:
        return None

    page_published = extract_published_date(soup)
    published = page_published or fallback_published_at
    if published is None:
        return None
    if not is_within_window(published, now):
        # Un anuncio anterior se conserva únicamente cuando el artículo verifica
        # una actividad futura y el buscador lo encontró en la ventana de 30 días.
        if not upcoming_event or published < now - timedelta(days=30):
            return None

    item = Item(
        title=title,
        url=final_url or url,
        source=source_name,
        published_at=published,
        summary=summarize(description or body_text or context_hint, 650),
        section="Evento" if is_event else "Noticia",
        tags=tags,
        event_date=event_date if upcoming_event else "",
        event_date_verified=upcoming_event,
        date_label="Publicado" if page_published else "Fecha del RSS" if fallback_published_at else "Detectado",
        relevance=score if relevant else 20,
    )
    return item


def scan_web_source(source: dict[str, str], now: datetime) -> tuple[list[Item], dict[str, Any]]:
    name, url = source["name"], source["url"]
    raw, final_url, status = fetch(url)
    status_row = {"fuente": name, "url": url, "estado": "consultada" if raw else f"sin acceso (HTTP {status or 'error'})"}
    if not raw:
        return [], status_row

    results: list[Item] = []
    soup = BeautifulSoup(raw, "html.parser")
    feeds = discover_feed_urls(final_url, raw)
    for feed_url in feeds:
        try:
            results.extend(parse_feed(feed_url, name, now))
        except Exception as exc:
            LOG.debug("Feed %s: %s", feed_url, exc)

    links = candidate_links(final_url, raw, now)
    if not results and not links:
        status_row["estado"] = "consultada; sin resultados detectables en el HTML público"
    elif links:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(parse_article, u, t, c, name, now) for u, t, c in links]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        results.append(item)
                except Exception as exc:
                    LOG.debug("Artículo de %s: %s", name, exc)
    status_row["resultados"] = len(results)
    return results, status_row


def google_news_queries() -> list[tuple[str, str]]:
    """Búsquedas gratuitas: INTA primero, otras instituciones después y medios como complemento."""
    return [
        ('site:argentina.gob.ar/inta (lechería OR tambo OR leche OR "vacas lecheras" OR forrajes) when:7d', "news"),
        ('site:argentina.gob.ar/inta/cr-santa-fe/noticias (lechería OR tambo OR leche OR vacas OR forrajes) when:7d', "news"),
        ('site:argentina.gob.ar/inta/cr-entre-rios/noticias (lechería OR tambo OR leche OR vacas OR forrajes) when:7d', "news"),
        ('site:argentina.gob.ar/inta/cr-cordoba/noticias (lechería OR tambo OR leche OR vacas OR forrajes) when:7d', "news"),
        ('site:argentina.gob.ar/inta/cr-corrientes/noticias (lechería OR tambo OR leche OR vacas OR forrajes) when:7d', "news"),
        ('(lechería OR lechero OR tambo OR tambos OR "producción de leche") Argentina when:7d', "news"),
        ('("vacas lecheras" OR "rodeo lechero" OR terneras OR vaquillonas OR "crianza de terneros") Argentina when:7d', "news"),
        ('(mastitis OR brucelosis bovina OR tuberculosis bovina OR queratoconjuntivitis OR sanidad bovina) Argentina when:7d', "news"),
        ('(reproducción bovina OR genética lechera OR fertilidad OR crianza artificial) Argentina when:7d', "news"),
        ('("precio de la leche" OR "precio al productor" OR costos del tambo OR rentabilidad lechera OR OCLA) Argentina when:7d', "news"),
        ('(forrajes OR alfalfa OR "maíz para silo" OR pasturas OR raciones OR nutrición bovina) (tambo OR vacas lecheras) Argentina when:7d', "news"),
        ('(SENASA OR trazabilidad animal OR identificación electrónica bovina OR RENSPA) (lechería OR bovinos OR tambos) Argentina when:7d', "news"),
        ('(robotización OR automatización OR ordeño robotizado OR tecnología para tambos OR maquinaria lechera) Argentina when:7d', "news"),
        ('site:conicet.gov.ar (leche OR lechería OR bovinos OR mastitis OR reproducción animal OR forrajes) Argentina when:7d', "news"),
        ('site:unl.edu.ar (leche OR lechería OR bovinos OR mastitis OR tambo OR forrajes) when:7d', "news"),
        ('(jornada OR jornadas OR curso OR capacitación OR seminario OR congreso OR "día de campo" OR webinar) (lechería OR tambo OR "vacas lecheras") Argentina when:30d', "event"),
        ('(encuentro OR taller OR charla OR exposición OR feria OR actualización técnica) (producción de leche OR ganado lechero OR tambos) Argentina when:30d', "event"),
        ('(jornada OR curso OR seminario OR capacitación OR congreso) (lechería OR tambo OR bovinos) (Santa Fe OR Córdoba OR Entre Ríos OR Buenos Aires OR La Pampa) when:30d', "event"),
    ]


def enrich_google_news_item(item: Item, now: datetime) -> Item:
    """Intenta resolver el enlace de Google News y ampliar el resumen con texto público."""
    raw, final_url, status = fetch(item.url, timeout=(10, 25))
    if not raw:
        return item
    host = (urlparse(final_url).hostname or "").lower()
    if host.endswith("google.com") or host.endswith("googleusercontent.com"):
        return item

    soup = BeautifulSoup(raw, "html.parser")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    page_title = clean_text(
        (og_title.get("content") if og_title else "")
        or (h1.get_text(" ", strip=True) if h1 else ""),
        300,
    )
    description = ""
    for attrs in ({"property": "og:description"}, {"name": "description"}, {"name": "twitter:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 1100)
            break
    article_node = soup.find("article") or soup.find("main") or soup.body or soup
    body_text = clean_text(article_node.get_text(" ", strip=True), 14000)
    if len(body_text) >= 120:
        item.summary = summarize(body_text, 1000)
    elif len(description) >= 50:
        item.summary = description
    if len(page_title) >= 10:
        item.title = page_title
    page_date = extract_published_date(soup)
    if page_date and is_within_window(page_date, now):
        item.published_at = page_date
        item.date_label = "Publicado"
    item.url = final_url or item.url
    return item


def scan_google_news(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    results: list[Item] = []
    seen: set[str] = set()
    event_candidates = 0

    for query, query_kind in google_news_queries():
        url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=es-419&gl=AR&ceid=AR:es-419"
        try:
            feed_raw, _, _ = fetch(url)
            if not feed_raw:
                continue
            parsed = feedparser.parse(feed_raw)
        except Exception:
            continue

        for entry in parsed.entries[:MAX_GOOGLE_NEWS_ITEMS]:
            title = clean_text(entry.get("title", ""), 300)
            link = entry.get("link", "")
            if not title or not link or link in seen:
                continue

            st = entry.get("published_parsed")
            pub = None
            if st:
                try:
                    pub = datetime(*st[:6], tzinfo=timezone.utc).astimezone(TZ)
                except Exception:
                    pass
            if pub is None:
                pub = parse_datetime(entry.get("published"))
            if pub is None:
                continue

            source_obj = entry.get("source", {}) or {}
            source_name = clean_text(source_obj.get("title", "Google News"), 120)
            summary = clean_text(entry.get("summary", ""), 900)
            title_summary = f"{title} {summary}"
            is_event = any(normalize(word) in normalize(title_summary) for word in EVENT_WORDS)

            if query_kind == "event":
                # La publicación puede ser anterior, pero el evento debe ser futuro
                # y estar documentado en la página original.
                if not is_event or pub < now - timedelta(days=30):
                    continue
                seen.add(link)
                event_candidates += 1
                item = parse_article(
                    link,
                    title,
                    summary,
                    source_name,
                    now,
                    allow_upcoming_event=True,
                    fallback_published_at=pub,
                )
                if item:
                    item.discovered_via_google_news = True
                    results.append(item)
            elif is_within_window(pub, now):
                seen.add(link)
                relevant, tags, score = is_relevant(title_summary)
                # Google News ya devuelve candidatos de consultas sectoriales.
                # La IA local evaluará los que no entren por coincidencia literal.
                if ai_hard_excluded(title_summary):
                    continue
                results.append(Item(
                    title=title,
                    url=link,
                    source=source_name,
                    published_at=pub,
                    summary=summary or "Resultado detectado por Google News; abrir la fuente para consultar el contenido completo.",
                    section="Evento" if is_event else "Noticia",
                    tags=tags,
                    event_date=guess_event_date(title_summary, now) if is_event else "",
                    relevance=score if relevant else 15,
                    discovered_via_google_news=True,
                ))

            if len(results) >= MAX_GOOGLE_NEWS_TOTAL:
                break
        if len(results) >= MAX_GOOGLE_NEWS_TOTAL:
            break

    enrichable = [item for item in results if not item.event_date_verified][:MAX_GOOGLE_NEWS_ENRICHMENTS]
    if enrichable:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(enrich_google_news_item, item, now) for item in enrichable]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    LOG.debug("No se pudo ampliar un resultado de Google News: %s", exc)

    return results, {
        "fuente": "Google News RSS (búsqueda gratuita)",
        "url": "https://news.google.com/",
        "estado": "consultada",
        "candidatos_eventos": event_candidates,
        "resultados": len(results),
        "articulos_ampliados": len(enrichable),
        "ventana_noticias_dias": NEWS_WINDOW_DAYS,
    }


# ---------------------------------------------------------------------------
# IA local gratuita: inferencia con Ollama y modelo Qwen3
# ---------------------------------------------------------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL_LIBRARY_URL = "https://ollama.com/library/qwen3:1.7b"
AI_EVENT_HORIZON_DAYS = 90
MAX_BULLETIN_CANDIDATES = 50
MAX_BULLETIN_AI_DOCS = 12
MAX_GOOGLE_NEWS_AI_ITEMS = 48
LOCAL_AI_BATCH_SIZE = 8


def local_ai_is_available() -> tuple[bool, str]:
    """Solo acepta Ollama en loopback: ningún texto se envía a un modelo remoto."""
    if os.getenv("RADAR_LOCAL_AI", "1").strip().lower() in ("0", "false", "no"):
        return False, "IA local desactivada por configuración."
    host = urlparse(OLLAMA_HOST)
    if host.hostname not in ("127.0.0.1", "localhost", "::1"):
        return False, "IA local desactivada: OLLAMA_HOST no apunta a localhost."
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=(2, 3))
        response.raise_for_status()
        models = response.json().get("models", [])
        names = {str(model.get("name", "")) for model in models}
        if OLLAMA_MODEL not in names:
            return False, f"modelo local no instalado: {OLLAMA_MODEL}"
        return True, f"Ollama local disponible ({OLLAMA_MODEL})"
    except (requests.RequestException, ValueError, TypeError) as exc:
        return False, f"Ollama local no disponible: {clean_text(str(exc), 180)}"


def local_ai_generate_json(prompt: str, schema: dict[str, Any], max_predict: int = 3000, timeout_seconds: int = 240) -> tuple[dict[str, Any] | None, str]:
    """Inferencia en localhost con salida JSON estructurada; no usa claves ni servicios pagos."""
    available, status = local_ai_is_available()
    if not available:
        return None, status
    payload = {
        "model": OLLAMA_MODEL,
        "system": (
            "Sos un asistente editorial especializado en lechería argentina. "
            "Analizá exclusivamente la información proporcionada. No inventes hechos, "
            "fechas, lugares, organismos, obligaciones ni beneficios."
        ),
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {"temperature": 0, "num_ctx": 16000, "num_predict": max_predict},
    }
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=payload,
            timeout=(5, timeout_seconds),
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        if not isinstance(raw, str) or not raw.strip():
            return None, "Ollama respondió sin contenido."
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, "Ollama no devolvió un objeto JSON."
        return data, f"inferencia local completada con {OLLAMA_MODEL}"
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return None, f"error de inferencia local: {clean_text(str(exc), 220)}"


def ai_event_date_visible(event_date: datetime, body_text: str) -> bool:
    """Comprueba que día y mes del evento figuren realmente en el texto de la fuente."""
    visible_dates = extract_text_dates(body_text)
    if event_date.date() in {d.date() for d in visible_dates}:
        return True
    if any(d.day == event_date.day and d.month == event_date.month for d in visible_dates):
        return False
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    month = months[event_date.month - 1]
    text = normalize(body_text)
    day = event_date.day
    month_pattern = rf"\b0?{day}\b.{{0,55}}\b{month}\b"
    numeric_pattern = rf"\b0?{day}[/.-]0?{event_date.month}\b"
    return bool(re.search(month_pattern, text) or re.search(numeric_pattern, text))


def ai_hard_excluded(text: str) -> bool:
    """Las exclusiones editoriales prevalecen sobre cualquier clasificación de la IA."""
    ntext = normalize(text)
    dairy = any(contains_term(ntext, term) for term in DAIRY_EDITORIAL_TERMS)
    specific_livestock = any(contains_term(ntext, term) for term in SPECIFIC_LIVESTOCK_TERMS)
    meat = any(contains_term(ntext, term) for term in MEAT_FOCUS_TERMS)
    crop = any(contains_term(ntext, term) for term in CROP_FOCUS_TERMS)
    feed_context = any(contains_term(ntext, term) for term in (
        "maíz para silo", "silo de maíz", "silaje", "maíz picado", "sorgo forrajero",
        "ración bovina", "raciones bovinas", "ración para vacas", "alimento para el ganado",
        "nutrición bovina", "alimentación bovina", "forrajes", "reservas forrajeras",
        "pasturas", "alfalfa", "suplementación",
    ))
    if meat and not dairy:
        return True
    if crop and not (dairy or specific_livestock or feed_context):
        return True
    return False


NEWS_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "kind": {"type": "string", "enum": ["news", "event"]},
                    "category": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer"},
                    "summary": {"type": "string"},
                    "event_date": {"type": "string"},
                    "location": {"type": "string"},
                    "organizer": {"type": "string"},
                },
                "required": [
                    "index", "relevant", "kind", "category", "tags", "score",
                    "summary", "event_date", "location", "organizer",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def filter_google_news_fallback(items: list[Item]) -> list[Item]:
    """Fallback determinístico: preserva somente itens tematicamente relevantes."""
    return [
        item for item in items
        if is_relevant(f"{item.title} {item.summary}")[0]
        and not ai_hard_excluded(f"{item.title} {item.summary}")
    ]


def review_google_news_with_local_ai(items: list[Item], now: datetime) -> tuple[list[Item] | None, dict[str, Any]]:
    """Filtra y resume con el modelo local los candidatos de las búsquedas RSS gratuitas."""
    status_row = {
        "fuente": f"IA local · {OLLAMA_MODEL}",
        "url": OLLAMA_MODEL_LIBRARY_URL,
        "estado": "pendiente",
        "resultados": 0,
    }
    if not items:
        status_row["estado"] = "sin candidatos para analizar"
        return [], status_row
    available, reason = local_ai_is_available()
    if not available:
        status_row["estado"] = f"{reason}; se conservan los resultados convencionales"
        return None, status_row

    reviewed: list[Item] = []
    candidates = items[:MAX_GOOGLE_NEWS_AI_ITEMS]
    leftovers = [
        item for item in items[MAX_GOOGLE_NEWS_AI_ITEMS:]
        if is_relevant(f"{item.title} {item.summary}")[0]
        and not ai_hard_excluded(f"{item.title} {item.summary}")
    ]

    for batch_start in range(0, len(candidates), LOCAL_AI_BATCH_SIZE):
        batch = candidates[batch_start:batch_start + LOCAL_AI_BATCH_SIZE]
        rows = []
        for local_index, item in enumerate(batch):
            rows.append({
                "index": local_index,
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at.strftime("%d/%m/%Y %H:%M"),
                "url": item.url,
                "preliminary_section": item.section,
                "preliminary_event_date": item.event_date,
                "text_from_feed_or_article": item.summary[:1000],
            })
        prompt = f"""
Fecha de hoy en Argentina: {now.strftime("%d/%m/%Y")} ({TZ_NAME}).

Evaluá estos candidatos recuperados mediante búsquedas RSS gratuitas de Google News.
Seleccioná solo publicaciones argentinas realmente vinculadas con tambos, producción
y precio de la leche, industria láctea, vacas lecheras, vaquillonas, terneros de tambo,
reproducción, genética, sanidad, bienestar, alimentación, forrajes y tecnología lechera.
También seleccioná jornadas, cursos, congresos, capacitaciones, días de campo y
encuentros técnicos sobre esos temas.

Excluí carne, faena, feedlots, novillos, cultivos o mercados de granos sin vínculo
expreso con alimentación animal, y meteorología general.

Reglas:
- El texto de cada candidato es la única evidencia disponible. No completes datos ausentes.
- No confundas la fecha de publicación con la fecha del evento.
- "news" requiere publicación dentro de las últimas 24 horas.
- "event" requiere una fecha futura entre hoy y los próximos {AI_EVENT_HORIZON_DAYS} días.
- Para un evento, event_date debe aparecer claramente en el texto; si no, no lo clasifiques como evento.
- Localidad y organizador solo se completan si aparecen en el texto.
- No alcanza una mención incidental a "ganado", "campo" o "agro".
- Si no es relevante, relevant=false y score=0.
- Asigná score de 40 a 100 según relevancia. No inventes hechos.
- Devolvé exactamente una fila por candidato y respetá su index.
- Respondé únicamente con JSON.

CANDIDATOS:
{json.dumps(rows, ensure_ascii=False)}
""".strip()
        data, model_status = local_ai_generate_json(
            prompt, NEWS_AI_SCHEMA, max_predict=1800, timeout_seconds=180
        )
        if data is None:
            status_row["estado"] = f"{model_status}; se conservan los resultados convencionales"
            return None, status_row
        output_rows = data.get("items", [])
        if not isinstance(output_rows, list):
            status_row["estado"] = "respuesta local inválida; se conservan los resultados convencionales"
            return None, status_row

        by_index = {
            row.get("index"): row
            for row in output_rows
            if isinstance(row, dict) and isinstance(row.get("index"), int)
        }
        for local_index, item in enumerate(batch):
            row = by_index.get(local_index)
            if not isinstance(row, dict) or not row.get("relevant"):
                continue
            evidence_text = f"{item.title} {item.summary}"
            if ai_hard_excluded(evidence_text):
                continue
            try:
                score = max(0, min(100, int(row.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            if score < 40:
                continue
            summary = clean_text(str(row.get("summary") or ""), 650)
            if len(summary) < 35:
                summary = item.summary
            category = clean_text(str(row.get("category") or "Lechería"), 80)
            tags = [
                clean_text(str(tag), 65)
                for tag in row.get("tags", [])
                if clean_text(str(tag), 65)
            ][:5]
            if category and category not in tags:
                tags.insert(0, category)

            kind = str(row.get("kind") or "news").lower()
            candidate_date = parse_datetime(row.get("event_date"))
            existing_date = parse_datetime(item.event_date) if item.event_date else None
            event_date = candidate_date or existing_date
            verified_event = bool(
                kind == "event"
                and event_date
                and now.date() <= event_date.date() <= (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).date()
                and (
                    item.event_date_verified
                    or ai_event_date_visible(event_date, evidence_text)
                )
            )
            if verified_event:
                item.section = "Evento"
                item.event_date = event_date.strftime("%d/%m/%Y")
                location = clean_text(str(row.get("location") or ""), 160)
                organizer = clean_text(str(row.get("organizer") or ""), 160)
                item.event_location = location if location and normalize(location) in normalize(evidence_text) else ""
                item.event_organizer = organizer if organizer and normalize(organizer) in normalize(evidence_text) else ""
            elif is_within_window(item.published_at, now):
                item.section = "Noticia"
                item.event_date = ""
                item.event_location = ""
                item.event_organizer = ""
            else:
                continue
            item.source = f"{item.source} · IA local"
            item.summary = summary
            item.tags = tags
            item.relevance = score
            reviewed.append(item)

    reviewed.extend(leftovers)
    status_row["candidatos"] = len(candidates)
    status_row["resultados"] = len(reviewed)
    status_row["estado"] = f"análisis local terminado: {len(reviewed)} resultados conservados de {len(items)} candidatos"
    return reviewed, status_row


# ---------------------------------------------------------------------------
# Boletín Oficial: extracción de fichas y análisis orientado a lechería
# ---------------------------------------------------------------------------
BOLETIN_DISCOVERY_TERMS = [
    "leche", "lácteo", "lechero", "lechería", "tambo", "tambero", "ordeño",
    "bovino", "bovina", "vacuno", "ganado", "ganadería", "animal", "veterinario",
    "veterinaria", "senasa", "sanidad", "brucelosis", "tuberculosis", "aftosa",
    "zoonosis", "trazabilidad", "identificación animal", "renspa", "sigsa",
    "forraje", "pastura", "alfalfa", "silaje", "maíz para silo", "alimento balanceado",
    "nutrición animal", "agropecuario", "agropecuaria", "agricultura", "semillas",
    "fitosanitario", "fertilizante", "inocuidad alimentaria", "alimentos",
    "emergencia agropecuaria", "emergencia sanitaria", "producción agropecuaria",
    "registro sanitario", "establecimiento rural", "establecimiento productivo",
    "crédito agropecuario", "financiamiento agropecuario", "economía regional",
    "comercio exterior", "exportación de productos lácteos", "industria láctea",
]


def bulletin_discovery_score(text: str) -> int:
    ntext = normalize(text)
    return sum(
        2 if len(normalize(term).split()) > 1 else 1
        for term in BOLETIN_DISCOVERY_TERMS
        if contains_term(ntext, term)
    )


def bulletin_edition_date(soup: BeautifulSoup) -> datetime | None:
    published = extract_published_date(soup)
    if published:
        return published
    page_text = clean_text(soup.get_text(" ", strip=True), 12000)
    candidates = extract_text_dates(page_text[:4000])
    return candidates[0] if candidates else None


def bulletin_listing_candidates(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    """Levanta enlaces individuales de la Primera Sección y prioriza candidatos sectoriales."""
    container = soup.find(id="avisosSeccionDiv") or soup.find("main") or soup.body or soup
    candidates: dict[str, dict[str, str]] = {}

    for anchor in container.find_all("a", href=True):
        href_raw = str(anchor.get("href") or "").strip()
        if not href_raw or "?" in href_raw:
            continue
        article_url = absolute_url(page_url, href_raw)
        parsed = urlparse(article_url)
        if parsed.scheme not in ("http", "https") or not host_matches(article_url, BOLETIN_HOME):
            continue
        if article_url.rstrip("/") == page_url.rstrip("/"):
            continue
        path = normalize(parsed.path)
        if any(token in path for token in ("/seccion/", "/busqueda", "/ayuda", "/contacto", "/login")):
            continue

        context_node = anchor
        for _ in range(3):
            if context_node.parent and context_node.parent is not container:
                context_node = context_node.parent
        local_context = clean_text(context_node.get_text(" ", strip=True), 1100)
        title = clean_text(anchor.get_text(" ", strip=True), 320)
        if len(title) < 12:
            heading = context_node.find(["h1", "h2", "h3", "h4"])
            title = clean_text(heading.get_text(" ", strip=True), 320) if heading else local_context[:320]
        score = bulletin_discovery_score(f"{title} {local_context}")
        if score <= 0:
            continue

        current = candidates.get(article_url)
        record = {
            "url": article_url,
            "title_hint": title,
            "context": local_context,
            "discovery_score": str(score),
        }
        if current is None or score > int(current["discovery_score"]):
            candidates[article_url] = record

    ordered = sorted(
        candidates.values(),
        key=lambda row: (-int(row["discovery_score"]), row["url"]),
    )
    return ordered[:MAX_BULLETIN_CANDIDATES]


def fetch_bulletin_detail(candidate: dict[str, str], edition_date: datetime | None) -> dict[str, Any] | None:
    """Descarga una ficha oficial y extrae título, área, tipo, texto y fecha."""
    raw, article_url, status = fetch(candidate["url"], timeout=(12, 30))
    if not raw or status >= 400:
        return None

    soup = BeautifulSoup(raw, "html.parser")
    title_area = soup.find(id="tituloDetalleAviso")
    title_heading = title_area.find("h2") if title_area else None
    area_heading = title_area.find("h1") if title_area else None

    title_tag = title_heading or soup.find("h1") or soup.find("title")
    title = clean_text(
        title_tag.get_text(" ", strip=True) if title_tag else candidate.get("title_hint", ""),
        320,
    )
    if len(title) < 8:
        title = clean_text(candidate.get("title_hint", ""), 320)

    area = clean_text(area_heading.get_text(" ", strip=True), 220) if area_heading else ""
    type_node = soup.find(class_="puntero first-section")
    notice_type = clean_text(type_node.get_text(" ", strip=True), 120) if type_node else ""

    content_node = soup.find(id="cuerpoDetalleAviso")
    if content_node is None:
        content_node = soup.find("article") or soup.find("main") or soup.body or soup
    body = clean_text(content_node.get_text(" ", strip=True), 14000)
    if len(body) < 45:
        body = clean_text(candidate.get("context", ""), 14000)
    if len(body) < 45:
        return None

    publication_date = extract_published_date(soup) or edition_date
    return {
        "url": article_url or candidate["url"],
        "title": title,
        "area": area,
        "notice_type": notice_type,
        "body": body,
        "published_at": publication_date,
        "discovery_score": int(candidate.get("discovery_score") or 0),
    }


BOLETIN_AI_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "category": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "integer"},
                    "summary": {"type": "string"},
                    "impact": {"type": "string"},
                    "affected_actors": {"type": "string"},
                    "what_to_check": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": [
                    "index", "relevant", "category", "tags", "score", "summary",
                    "impact", "affected_actors", "what_to_check", "evidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def analyze_bulletin_documents(documents: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]] | None, str]:
    """Clasifica documentos oficiales con el modelo abierto ejecutado localmente."""
    compact_docs = []
    for index, doc in enumerate(documents):
        compact_docs.append({
            "index": index,
            "title": doc["title"],
            "area": doc["area"],
            "type": doc["notice_type"],
            "url": doc["url"],
            "publication_date": doc["published_at"].strftime("%d/%m/%Y") if doc["published_at"] else "",
            "official_text": doc["body"][:3200],
        })
    prompt = f"""
Analizá estas publicaciones de la Primera Sección del Boletín Oficial argentino.
Seleccioná únicamente disposiciones con incidencia concreta en lechería, tambos
o ganado bovino, especialmente el ganado lechero.

Incluí producción de leche, sanidad, bienestar, identificación y trazabilidad bovina,
SENASA, medicamentos veterinarios, reproducción, genética, crianza de terneros,
alimentación animal, raciones, forrajes, pasturas, silaje, habilitaciones, registros,
inocuidad, transporte, comercialización de leche y medidas económicas que alcancen
expresamente al sector.

Excluí designaciones sin impacto sectorial, normas genéricas, agricultura sin relación
con alimentación animal y disposiciones sobre carne, faena, feedlots o novillos.

Reglas:
- No alcanza una mención incidental a un término sectorial.
- Explicá qué cambia, a quién alcanza y si el efecto es directo o potencial.
- No inventes obligaciones, beneficios, subsidios, exenciones ni fechas de vigencia.
- relevance va de 0 a 100; usá al menos 60 solo si el impacto es claro.
- Si no es relevante, relevant=false y score=0.
- evidence debe ser una cita literal y breve del texto oficial que fundamente su impacto.
- Si no hay evidencia textual suficiente, relevant=false.
- what_to_check debe identificar sujetos, requisitos, plazos o vigencia a verificar.
- Devolvé una fila por documento y conservá el index exacto.
- Respondé solo JSON.

DOCUMENTOS:
{json.dumps(compact_docs, ensure_ascii=False)}
""".strip()
    data, status = local_ai_generate_json(
        prompt, BOLETIN_AI_SCHEMA, max_predict=3200, timeout_seconds=240
    )
    if data is None:
        return None, f"{status}; se utiliza el filtro temático de respaldo"
    rows = data.get("items", [])
    if not isinstance(rows, list):
        return None, "respuesta local inválida; se utiliza el filtro temático de respaldo"
    mapped: dict[int, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("index"), int):
            mapped[row["index"]] = row
    return mapped, f"{status}; {len(mapped)} documentos evaluados"

def bulletin_ai_copy(doc: dict[str, Any], analysis: dict[str, Any]) -> str:
    pub = doc["published_at"]
    pub_label = pub.strftime("%d/%m/%Y") if pub else "fecha no identificada"
    impact = clean_text(str(analysis.get("impact") or ""), 900)
    actors = clean_text(str(analysis.get("affected_actors") or ""), 500)
    what_to_check = clean_text(str(analysis.get("what_to_check") or ""), 600)
    evidence = clean_text(str(analysis.get("evidence") or ""), 420)
    return (
        f"📌 {doc['title']}\n\n"
        f"Publicación oficial: {pub_label} · {doc['url']}\n\n"
        f"Impacto para la lechería: {impact}\n\n"
        f"A quiénes puede alcanzar: {actors}\n\n"
        f"Qué conviene verificar: {what_to_check}\n\n"
        f"Fundamento en el texto oficial: “{evidence}”\n\n"
        "Análisis orientativo elaborado con IA a partir del texto oficial. "
        "Verificar el articulado completo, anexos, sujetos alcanzados y vigencia "
        "antes de tomar decisiones o comunicar obligaciones o beneficios."
    )


def scrape_bulletin(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    """Recolector propio de la Primera Sección; usa IA para priorizar normas sectoriales."""
    raw, final_url, status = fetch(BOLETIN_URL)
    status_row: dict[str, Any] = {
        "fuente": "Boletín Oficial – Primera Sección",
        "url": BOLETIN_URL,
        "estado": "consultada" if raw else f"sin acceso (HTTP {status or 'error'})",
        "resultados": 0,
    }
    if not raw:
        return [], status_row

    listing_soup = BeautifulSoup(raw, "html.parser")
    edition_date = bulletin_edition_date(listing_soup)
    candidates = bulletin_listing_candidates(listing_soup, final_url or BOLETIN_URL)
    status_row["edicion"] = edition_date.strftime("%d/%m/%Y") if edition_date else "fecha no identificada"
    status_row["enlaces_candidatos"] = len(candidates)

    documents: list[dict[str, Any]] = []
    if candidates:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(fetch_bulletin_detail, candidate, edition_date)
                for candidate in candidates
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    document = future.result()
                    if document:
                        documents.append(document)
                except Exception as exc:
                    LOG.debug("Ficha del Boletín Oficial: %s", exc)

    documents.sort(
        key=lambda doc: (
            -int(doc.get("discovery_score") or 0),
            -(doc["published_at"].timestamp() if doc["published_at"] else 0),
            doc["title"],
        )
    )
    documents = [
        doc for doc in documents
        if doc["published_at"] is not None and is_within_window(doc["published_at"], now)
    ][:MAX_BULLETIN_AI_DOCS]

    status_row["fichas_recuperadas"] = len(documents)
    if not documents:
        status_row["estado"] = "consultada; no se recuperaron fichas sectoriales con fecha verificable"
        return [], status_row

    analyses, analysis_status = analyze_bulletin_documents(documents)
    results: list[Item] = []

    for index, doc in enumerate(documents):
        analysis = analyses.get(index) if analyses is not None else None
        full_text = f"{doc['title']} {doc['area']} {doc['body']}"
        if analyses is not None:
            if not isinstance(analysis, dict) or not analysis.get("relevant"):
                continue
            if ai_hard_excluded(full_text):
                continue
            try:
                score = max(0, min(100, int(analysis.get("score", 0))))
            except (TypeError, ValueError):
                score = 0
            evidence = clean_text(str(analysis.get("evidence") or ""), 420)
            normalized_body = normalize(doc["body"])
            if score < 60 or not evidence or normalize(evidence) not in normalized_body:
                continue
            summary = clean_text(str(analysis.get("summary") or ""), 700)
            impact = clean_text(str(analysis.get("impact") or ""), 900)
            if len(summary) < 30 or len(impact) < 30:
                continue
            tags = [
                clean_text(str(tag), 70)
                for tag in analysis.get("tags", [])
                if clean_text(str(tag), 70)
            ][:6]
            category = clean_text(str(analysis.get("category") or "Normativa sectorial"), 100)
            if category and category not in tags:
                tags.insert(0, category)
            legal_copy = bulletin_ai_copy(doc, analysis)
            relevance = score
        else:
            relevant, tags, score = is_relevant(full_text)
            if not relevant:
                continue
            summary = summarize(doc["body"], 450)
            legal_copy = legal_impact_copy(
                doc["title"], doc["body"], doc["url"], doc["published_at"], tags
            )
            relevance = min(100, score + 5)

        results.append(Item(
            title=doc["title"],
            url=doc["url"],
            source="Boletín Oficial – Análisis IA" if analyses is not None else "Boletín Oficial – Filtro de respaldo",
            published_at=doc["published_at"],
            summary=summary,
            section="Normativa",
            tags=tags,
            legal_copy=legal_copy,
            relevance=relevance,
        ))

    status_row["analisis_ia"] = analysis_status
    status_row["documentos_analizados"] = len(analyses) if analyses is not None else 0
    status_row["resultados"] = len(results)
    status_row["estado"] = (
        f"{analysis_status}; {len(results)} normas relevantes seleccionadas"
        if analyses is not None
        else f"{analysis_status}; filtro de respaldo produjo {len(results)} resultados"
    )
    return results, status_row


# ---------------------------------------------------------------------------
# Redes sociales (consulta de páginas públicas, sin autenticación)
# ---------------------------------------------------------------------------
def scan_social_profile(url: str, now: datetime) -> tuple[list[Item], dict[str, Any]]:
    raw, final_url, status = fetch(url, timeout=(10, 25))
    handle = urlparse(url).path.strip("/")
    if not raw:
        return [], {"fuente": handle, "url": url, "estado": f"acceso restringido o bloqueado (HTTP {status or 'error'})"}
    soup = BeautifulSoup(raw, "html.parser")
    description = ""
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 260)
            break

    # Cuando la propia página pública entrega enlaces a posts, se consultan hasta
    # dos publicaciones recientes. No se intenta iniciar sesión ni eludir bloqueos.
    is_instagram = "instagram.com" in urlparse(final_url).netloc.lower()
    post_urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = absolute_url(final_url, anchor["href"])
        path = urlparse(href).path.lower()
        if is_instagram and re.search(r"/(p|reel|tv)/[a-z0-9_-]+", path):
            post_urls.append(href)
        elif not is_instagram and re.search(r"/status/\d+", path):
            post_urls.append(href)
    post_urls = list(dict.fromkeys(post_urls))[:2]
    source_name = ("Instagram " if is_instagram else "X ") + "@" + handle.split("/")[0]
    items: list[Item] = []
    if post_urls:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(parse_article, post_url, f"Publicación de {source_name}", "", source_name, now) for post_url in post_urls]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        items.append(item)
                except Exception as exc:
                    LOG.debug("Publicación social %s: %s", url, exc)
    state = "posts públicos consultados" if items else (
        "página pública consultada; no se expusieron publicaciones fechadas en el HTML" if not post_urls
        else "se detectaron enlaces a publicaciones, pero no se pudo verificar contenido y fecha"
    )
    return items, {
        "fuente": handle,
        "url": final_url,
        "estado": state,
        "metadatos": description,
        "resultados": len(items),
    }

# ---------------------------------------------------------------------------
# Dedupe, HTML y TXT
# ---------------------------------------------------------------------------
def deduplicate(items: list[Item]) -> list[Item]:
    best: dict[str, Item] = {}
    for item in items:
        key = normalize(item.title)
        if not key:
            key = item.url
        current = best.get(key)
        if current is None or item.relevance > current.relevance:
            best[key] = item
    return sorted(best.values(), key=lambda x: (x.section != "Normativa", x.section != "Evento", -x.relevance, x.published_at), reverse=False)


def should_keep_item(item: Item, now: datetime) -> bool:
    if is_within_window(item.published_at, now):
        return True
    if item.section == "Evento" and ("Google News" in item.source or "IA local" in item.source):
        event_dt = parse_datetime(item.event_date)
        return bool(
            event_dt
            and now.date() <= event_dt.date() <= (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).date()
        )
    return False


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_html(items: list[Item], statuses: list[dict[str, Any]], now: datetime, window_start: datetime) -> str:
    day_label = now.strftime("%d/%m/%Y")
    counts = {
        "total": len(items),
        "noticias": sum(i.section == "Noticia" for i in items),
        "eventos": sum(i.section == "Evento" for i in items),
        "normativa": sum(i.section == "Normativa" for i in items),
    }
    sections = [("Normativa", "Normativa y Boletín Oficial"), ("Evento", "Agenda y eventos"), ("Noticia", "Noticias del sector")]
    cards = []
    for section, heading in sections:
        subset = [i for i in items if i.section == section]
        cards.append(f'<section class="section"><h2>{heading} <span>{len(subset)}</span></h2>')
        if not subset:
            cards.append('<p class="empty">No se detectaron publicaciones que cumplan el filtro de las últimas 24 horas.</p>')
        for item in subset:
            tags = " · ".join(item.tags or [])
            pub = item.published_at.strftime("%d/%m/%Y %H:%M")
            event_details = []
            if item.event_date:
                event_details.append(f"Fecha: {esc(item.event_date)}")
            if item.event_location:
                event_details.append(f"Lugar: {esc(item.event_location)}")
            if item.event_organizer:
                event_details.append(f"Organiza: {esc(item.event_organizer)}")
            event = f'<p class="event-date">{" · ".join(event_details)}</p>' if event_details else ""
            legal = f'<div class="copy"><h4>Copy institucional sugerido (borrador automático)</h4><pre>{esc(item.legal_copy)}</pre></div>' if item.legal_copy else ""
            cards.append(
                '<article class="item">'
                f'<div class="meta"><span>{esc(item.source)}</span><span>{esc(item.date_label)}: {pub}</span></div>'
                f'<h3><a href="{esc(item.url)}" target="_blank" rel="noopener">{esc(item.title)}</a></h3>'
                f'<p>{esc(item.summary)}</p>{event}'
                f'<p class="tags">{esc(tags)}</p>{legal}'
                '</article>'
            )
        cards.append('</section>')

    source_rows = "".join(f'<tr><td>{esc(s.get("fuente"))}</td><td>{esc(s.get("estado"))}</td><td>{esc(s.get("resultados", "—"))}</td></tr>' for s in statuses)
    social_rows = "".join(f'<tr><td><a href="{esc(s.get("url"))}" target="_blank" rel="noopener">{esc(s.get("fuente"))}</a></td><td>{esc(s.get("estado"))}</td></tr>' for s in statuses if s.get("social"))

    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BOT 384520 – {day_label}</title>
<style>
:root{{--ink:#1f2937;--muted:#64748b;--line:#e2e8f0;--paper:#f8fafc;--green:#1f6b4f;--gold:#b7791f;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 Arial,Helvetica,sans-serif}}
header{{background:#174b3a;color:white;padding:34px max(22px,calc((100% - 1100px)/2)) 28px}}
header h1{{margin:0;font-size:30px}}header p{{margin:6px 0;color:#d7e9df}}main{{max-width:1100px;margin:24px auto;padding:0 18px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}}
.metric,.section,.sources{{background:white;border:1px solid var(--line);border-radius:12px;padding:18px}}
.metric strong{{display:block;font-size:27px;color:var(--green)}}.metric span{{font-size:13px;color:var(--muted)}}
h2{{font-size:21px;margin:0 0 14px}}h2 span{{font-size:13px;color:var(--muted);font-weight:normal}}
.section{{margin:18px 0}}.item{{padding:17px 0;border-top:1px solid var(--line)}}.item:first-of-type{{border-top:0}}
.item h3{{font-size:19px;line-height:1.3;margin:8px 0}}a{{color:#135f48;text-decoration:none}}a:hover{{text-decoration:underline}}
.item p{{margin:7px 0}}.meta{{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px}}
.tags{{color:#64748b;font-size:12px}}.event-date{{color:#854d0e}}.copy{{background:#fffbeb;border:1px solid #f4d58d;border-radius:8px;padding:13px;margin-top:13px}}
.copy h4{{margin:0 0 8px;color:#854d0e}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 Arial,sans-serif;margin:0}}
.empty{{color:var(--muted);font-size:14px}}.sources{{margin:18px 0}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
footer{{text-align:center;padding:28px;color:var(--muted);font-size:12px}}@media(max-width:620px){{.metrics{{grid-template-columns:repeat(2,1fr)}}header h1{{font-size:24px}}}}
</style></head><body>
<header><h1>BOT 384520</h1><p>Noticias, eventos y normativa sobre lechería, ganadería bovina y ganado lechero</p>
<p>Informe del {day_label} · Ventana: {window_start.strftime('%d/%m/%Y %H:%M')} a {now.strftime('%d/%m/%Y %H:%M')} ({TZ_NAME})</p></header>
<main>
<div class="metrics"><div class="metric"><strong>{counts['total']}</strong><span>Publicaciones relevantes</span></div><div class="metric"><strong>{counts['noticias']}</strong><span>Noticias</span></div><div class="metric"><strong>{counts['eventos']}</strong><span>Eventos</span></div><div class="metric"><strong>{counts['normativa']}</strong><span>Normas detectadas</span></div></div>
{''.join(cards)}
<section class="sources"><h2>Estado de las fuentes consultadas</h2><p>Una fuente sin resultados no significa que no haya publicado: puede no exponer RSS, bloquear solicitudes automatizadas o requerir JavaScript.</p><table><thead><tr><th>Fuente</th><th>Estado</th><th>Resultados</th></tr></thead><tbody>{source_rows}</tbody></table>
<h3>Redes sociales incluidas en el monitoreo</h3><p>Instagram y X pueden limitar el acceso automatizado. Este informe solo muestra metadatos públicos que la página haya entregado; no inicia sesión ni afirma haber leído publicaciones que no fueron accesibles.</p><table><thead><tr><th>Perfil</th><th>Estado de acceso</th></tr></thead><tbody>{social_rows or '<tr><td colspan="2">No hubo perfiles accesibles en esta ejecución.</td></tr>'}</tbody></table></section>
</main><footer>BOT 384520 · IA ejecutada localmente · Las fuentes originales prevalecen sobre el resumen. Verificar vigencia y alcance de toda normativa en el texto oficial.</footer>
</body></html>'''


def write_txt(path: Path, items: list[Item]) -> None:
    """Genera un listado plano: título, fecha de publicación y enlace."""
    blocks = []
    for item in items:
        blocks.append(
            f"{item.title.strip()}\n"
            f"{item.published_at.strftime('%d/%m/%Y')}\n"
            f"{item.url.strip()}"
        )
    content = "\n\n".join(blocks)
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")

# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def run() -> tuple[Path, Path, int]:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(TZ)
    window_start = now - timedelta(hours=24)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = now.strftime("%d%m%y")
    html_path = OUTPUT_DIR / f"bot384520_{suffix}.html"
    txt_path = OUTPUT_DIR / f"bot384520_{suffix}.txt"

    LOG.info("Inicio de BOT 384520: %s (%s)", now.isoformat(), TZ_NAME)
    LOG.info("Ventana: %s – %s", window_start.isoformat(), now.isoformat())

    all_items: list[Item] = []
    statuses: list[dict[str, Any]] = []

    # Fuentes principales, en paralelo con concurrencia acotada.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(scan_web_source, source, now): source for source in WEB_SOURCES}
        for future in concurrent.futures.as_completed(future_map):
            source = future_map[future]
            try:
                items, status = future.result()
                all_items.extend(items)
                statuses.append(status)
                LOG.info("%s: %s resultados", source["name"], len(items))
            except Exception as exc:
                statuses.append({"fuente": source["name"], "url": source["url"], "estado": f"error de procesamiento: {exc}"})
                LOG.exception("Error en fuente %s", source["name"])

    # Google News RSS añade descubrimiento transversal, independiente de la lista de sitios.
    google_items: list[Item] = []
    try:
        google_items, google_status = scan_google_news(now)
        statuses.append(google_status)
        LOG.info("Google News: %s candidatos", len(google_items))
    except Exception as exc:
        statuses.append({"fuente": "Google News RSS", "url": "https://news.google.com/", "estado": f"error: {exc}"})

    # IA local revisa candidatos de Google News sin salir del runner.
    try:
        reviewed_google_items, ai_status = review_google_news_with_local_ai(google_items, now)
        if reviewed_google_items is not None:
            google_items = reviewed_google_items
        else:
            # Si el modelo local no está disponible, vuelve al filtro determinístico
            # para no volcar todos los resultados del RSS sin clasificación.
            google_items = filter_google_news_fallback(google_items)
            ai_status["fallback_resultados"] = len(google_items)
        all_items.extend(google_items)
        statuses.append(ai_status)
        LOG.info("IA local: %s candidatos finales", len(google_items))
    except Exception as exc:
        statuses.append({
            "fuente": f"IA local · {OLLAMA_MODEL}",
            "url": OLLAMA_MODEL_LIBRARY_URL,
            "estado": f"error local: {clean_text(str(exc), 260)}",
            "resultados": 0,
        })
        google_items = filter_google_news_fallback(google_items)
        all_items.extend(google_items)
        LOG.exception("Error en análisis local")

    # Legislación de la Primera Sección del Boletín Oficial.
    try:
        legal_items, legal_status = scrape_bulletin(now)
        all_items.extend(legal_items)
        statuses.append(legal_status)
        LOG.info("Boletín Oficial: %s normas relevantes", len(legal_items))
    except Exception as exc:
        statuses.append({"fuente": "Boletín Oficial – Primera Sección", "url": BOLETIN_URL, "estado": f"error: {exc}"})
        LOG.exception("Error leyendo Boletín Oficial")

    # Consulta de perfiles públicos: no se autentica ni se fuerza el acceso a contenido restringido.
    social_statuses: list[dict[str, Any]] = []
    if os.getenv("RADAR_SCAN_SOCIAL", "1").lower() not in ("0", "false", "no"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(scan_social_profile, url, now): url for url in SOCIAL_PROFILES}
            for future in concurrent.futures.as_completed(futures):
                try:
                    social_items, row = future.result()
                    all_items.extend(social_items)
                    row["social"] = True
                    social_statuses.append(row)
                except Exception as exc:
                    social_statuses.append({"fuente": futures[future], "url": futures[future], "estado": f"error: {exc}", "social": True})
        statuses.extend(social_statuses)

    items = deduplicate([item for item in all_items if should_keep_item(item, now)])
    # Orden explícito: normas, eventos y después noticias; dentro de cada bloque, más recientes primero.
    priority = {"Normativa": 0, "Evento": 1, "Noticia": 2}
    items.sort(key=lambda x: (priority.get(x.section, 9), -x.relevance, -x.published_at.timestamp()))

    html_content = render_html(items, statuses, now, window_start)
    html_path.write_text(html_content, encoding="utf-8")
    write_txt(txt_path, items)

    # El nombre de archivo es diario. Si se re-ejecuta en la misma fecha, se
    # actualiza el informe de ese día; nunca se modifican informes de otras fechas.
    LOG.info("Informe HTML: %s", html_path)
    LOG.info("Listado TXT: %s", txt_path)
    LOG.info("Total: %s publicaciones (%s normas, %s eventos)", len(items), sum(i.section == "Normativa" for i in items), sum(i.section == "Evento" for i in items))
    return html_path, txt_path, len(items)


if __name__ == "__main__":
    try:
        html_file, txt_file, total = run()
        print(f"OK: {total} publicaciones")
        print(f"HTML: {html_file}")
        print(f"TXT: {txt_file}")
    except Exception as exc:
        LOG.exception("La ejecución falló: %s", exc)
        sys.exit(1)
