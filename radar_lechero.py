#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BOT 384520: monitoreo de noticias, eventos y normativa sobre lechería y ganado bovino.

Combina fuentes RSS y portales con búsqueda web asistida por IA opcional.
Los resultados encontrados con IA se verifican contra las páginas originales.
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
MAX_GOOGLE_NEWS_ITEMS = 30

# Fuentes editoriales y técnicas. Se priorizan sitios oficiales y especializados.
WEB_SOURCES: list[dict[str, str]] = [
    {"name": "Argentina.gob.ar – Noticias", "url": "https://www.argentina.gob.ar/noticias", "kind": "institucional"},
    {"name": "SENASA", "url": "https://www.argentina.gob.ar/senasa", "kind": "institucional"},
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
    {"name": "UNL – Noticias", "url": "https://www.unl.edu.ar/noticias/", "kind": "academica"},
    {"name": "Infocampo", "url": "https://www.infocampo.com.ar/", "kind": "agro"},
    {"name": "Agroempresario", "url": "https://agroempresario.com/", "kind": "agro"},
    {"name": "Portal Lechero", "url": "https://portalechero.com/", "kind": "especializada"},
    {"name": "OCLA", "url": "https://www.ocla.org.ar/", "kind": "especializada"},
    {"name": "FCV UNL – Eventos", "url": "https://www.fcv.unl.edu.ar/eventos/", "kind": "eventos"},
    {"name": "Colegio de Médicos Veterinarios de Santa Fe", "url": "https://cmver.com.ar/", "kind": "profesional"},
    {"name": "Mundo Rural", "url": "https://mundorural.com.ar/", "kind": "agro"},
    {"name": "InfoLáctea", "url": "https://www.infolactea.com.ar/", "kind": "especializada"},
    {"name": "Secretaría de Agricultura", "url": "https://www.argentina.gob.ar/economia/agricultura", "kind": "institucional"},
    {"name": "INDEC", "url": "https://www.indec.gob.ar/", "kind": "estadistica"},
    {"name": "Bolsa de Comercio de Rosario", "url": "https://www.bcr.com.ar/es/mercados/investigacion-y-desarrollo/informativo-semanal", "kind": "economia"},
]

# El Boletín Oficial se procesa por separado para leer la Primera Sección.
BOLETIN_URL = "https://www.boletinoficial.gob.ar/seccion/primera"
BOLETIN_HOME = "https://www.boletinoficial.gob.ar/"

# Perfiles solicitados. Se consultan como páginas públicas; no se inicia sesión,
# no se evita CAPTCHA ni se accede a endpoints privados. Meta/HTML no siempre
# contiene publicaciones, por lo que se registra cada limitación de acceso.
SOCIAL_PROFILES = [
    "https://www.instagram.com/chacradebarrow",
    "https://www.instagram.com/eeafamailla",
    "https://x.com/pamperotv?lang=es",
    "https://x.com/senasaar",
]

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
    date_label: str = "Publicado"
    legal_copy: str = ""
    relevance: int = 0

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
    "ith", "sequía", "inundación", "falta de agua", "escasez de agua",
]
SPECIFIC_LIVESTOCK_TERMS = [
    term for term in LIVESTOCK_EDITORIAL_TERMS
    if term not in ("ganadería", "ganado", "veterinaria")
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
    el_nino = contains_term(ntext, "el niño") or contains_term(ntext, "enso")
    meat = any(contains_term(ntext, term) for term in MEAT_FOCUS_TERMS)
    crop = any(contains_term(ntext, term) for term in CROP_FOCUS_TERMS)

    if meat and not dairy:
        return False
    if el_nino:
        return True
    if crop and not (dairy or specific_livestock):
        return False
    return dairy or livestock

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


def is_within_window(dt: datetime | None, now: datetime, hours: int = 24) -> bool:
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


def parse_article(url: str, title_hint: str, context_hint: str, source_name: str, now: datetime) -> Item | None:
    raw, final_url, status = fetch(url)
    if not raw:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    title = clean_text((og_title.get("content") if og_title else "") or (h1.get_text(" ", strip=True) if h1 else "") or title_hint, 300)
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
    relevant, tags, score = is_relevant(text)
    if not relevant:
        return None
    published = extract_published_date(soup)
    if not is_within_window(published, now):
        return None
    is_event = any(normalize(w) in normalize(f"{title} {description} {context_hint}") for w in EVENT_WORDS)
    # No se toma la fecha de una jornada pasada como fecha futura del evento.
    event_date = guess_event_date(f"{title} {description} {context_hint} {body_text[:5000]}", now) if is_event else ""
    return Item(
        title=title,
        url=final_url or url,
        source=source_name,
        published_at=published,
        summary=summarize(description or body_text or context_hint),
        section="Evento" if is_event else "Noticia",
        tags=tags,
        event_date=event_date,
        relevance=score,
    )


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


def google_news_queries() -> list[str]:
    # Búsquedas centradas en lechería, ganado bovino y efectos de El Niño.
    return [
        '(lechería OR lechero OR tambo OR tambos) Argentina when:1d',
        '("vacas lecheras" OR "rodeo lechero" OR "producción de leche" OR terneras) Argentina when:1d',
        '(mastitis OR terneros OR vaquillonas OR reproducción bovina OR sanidad bovina) Argentina when:1d',
        '(OCLA OR "precio de la leche" OR "industria láctea" OR lácteos) Argentina when:1d',
        '("ganado bovino" OR bovinos OR ganadería) (sanidad OR nutrición OR bienestar OR reproducción OR alimentación) Argentina when:1d',
        '(SENASA bovinos OR trazabilidad animal OR identificación electrónica bovina) Argentina when:1d',
        '(forrajes OR alfalfa OR "maíz para silo" OR pasturas OR "silo de maíz" OR nutrición bovina) (tambo OR vacas OR ganado) Argentina when:1d',
        '("El Niño" OR ENSO) (Argentina OR ganadería OR bovinos OR tambo OR pasturas OR forrajes) when:1d',
    ]


def scan_google_news(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    results: list[Item] = []
    seen: set[str] = set()
    for query in google_news_queries():
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
            seen.add(link)
            st = entry.get("published_parsed")
            pub = None
            if st:
                try:
                    pub = datetime(*st[:6], tzinfo=timezone.utc).astimezone(TZ)
                except Exception:
                    pass
            if pub is None:
                pub = parse_datetime(entry.get("published"))
            source_obj = entry.get("source", {}) or {}
            source_name = clean_text(source_obj.get("title", "Google News"), 120)
            summary = clean_text(entry.get("summary", ""), 600)
            relevant, tags, score = is_relevant(f"{title} {summary}")
            if relevant and is_within_window(pub, now):
                event = any(normalize(w) in normalize(title) for w in EVENT_WORDS)
                results.append(Item(
                    title=title,
                    url=link,
                    source=f"Google News · {source_name}",
                    published_at=pub,
                    summary=summary or "Resultado detectado por Google News; abrir la fuente para consultar el contenido completo.",
                    section="Evento" if event else "Noticia",
                    tags=tags,
                    event_date=guess_event_date(f"{title} {summary}", now) if event else "",
                    relevance=score,
                ))
    return results, {"fuente": "Google News RSS", "url": "https://news.google.com/", "estado": "consultada", "resultados": len(results)}


# ---------------------------------------------------------------------------
# Descubrimiento ampliado con IA y búsqueda web (opcional)
# ---------------------------------------------------------------------------
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_DOCS_URL = "https://developers.openai.com/api/docs/guides/tools-web-search"
AI_DEFAULT_MODEL = "gpt-6-astra"
AI_MAX_CANDIDATES = 24
AI_EVENT_HORIZON_DAYS = 90
MAX_BULLETIN_CANDIDATES = 70
MAX_BULLETIN_AI_DOCS = 24

AI_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "url": {"type": "string"},
        "source_name": {"type": "string"},
        "country": {"type": "string", "enum": ["Argentina", "Otro"]},
        "publication_date": {"type": "string"},
        "kind": {"type": "string", "enum": ["news", "event"]},
        "category": {"type": "string"},
        "summary": {"type": "string"},
        "event_date": {"type": "string"},
        "location": {"type": "string"},
        "organizer": {"type": "string"},
        "relevance": {"type": "integer"},
    },
    "required": [
        "title", "url", "source_name", "country", "publication_date", "kind",
        "category", "summary", "event_date", "location", "organizer", "relevance",
    ],
    "additionalProperties": False,
}

def ai_output_text(payload: dict[str, Any]) -> str:
    """Extrae texto estructurado desde la respuesta de Responses API."""
    chunks: list[str] = []
    for output in payload.get("output", []):
        if output.get("type") != "message":
            continue
        for part in output.get("content", []):
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def ai_search_prompt(now: datetime) -> str:
    today = now.strftime("%d/%m/%Y")
    from_date = (now - timedelta(hours=24)).strftime("%d/%m/%Y")
    event_limit = (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).strftime("%d/%m/%Y")
    return f"""
Fecha y hora local de Argentina: {today}, {now.strftime('%H:%M')} ({TZ_NAME}).

Actuás como investigador periodístico especializado en la cadena láctea argentina.
Usá la búsqueda web para descubrir publicaciones REALES de medios, organismos,
universidades, asociaciones, cooperativas, entidades técnicas y organizadores de
eventos de Argentina. No respondas con una lista de ideas ni con búsquedas sugeridas:
buscá páginas concretas y devolvé sus enlaces originales.

Hacé búsquedas diferenciadas para cubrir:
1. Noticias publicadas entre {from_date} y {today} sobre tambos, producción de leche,
   precio al productor, costos, rentabilidad, industria láctea, cooperativas,
   inversiones, exportaciones e importaciones de lácteos y políticas para el sector.
2. Ganado lechero: vacas en ordeño, reproducción, genética, crianza y recría de terneros
   y terneras, sanidad, mastitis, bienestar, instalaciones, ordeño y tecnología.
3. Alimentación de rodeos: raciones, nutrición, pasturas, alfalfa, forrajes, reservas,
   silaje, maíz para silo, sorgo forrajero, agua y manejo alimentario.
4. Jornadas, cursos, capacitaciones, seminarios, congresos, días de campo, exposiciones,
   ferias, webinars y reuniones técnicas vinculadas con lechería, tambos y ganado lechero.
   Para eventos, aceptá páginas publicadas antes de las últimas 24 horas, pero el evento
   debe tener una fecha futura entre hoy y {event_limit}.
5. Noticias y actividades de entidades, universidades, facultades de veterinaria,
   asociaciones de productores, cooperativas y organizaciones técnicas de las cuencas
   lecheras argentinas. Cubrí todo el país, especialmente Santa Fe, Córdoba, Buenos Aires,
   Entre Ríos, La Pampa y Santiago del Estero.

Criterios editoriales obligatorios:
- El foco es ARGENTINA y la actividad lechera/tambera.
- Priorizá ganado lechero. Podés incluir noticias sanitarias o de manejo bovino general
  solo si tienen impacto claro en vacas, vaquillonas o terneros de tambo.
- Excluí noticias centradas en carne, faena, feedlots, novillos y ganadería de carne.
- Excluí noticias exclusivamente agrícolas (maíz para grano, soja, trigo, mercados de
  granos) sin relación concreta con alimentación animal o tambos.
- No incluyas pronósticos, estado del tiempo ni alertas meteorológicas generales.
  El fenómeno El Niño solo corresponde si la publicación explica efectos sobre tambos,
  ganado, pasturas o alimentación.
- No inventes títulos, enlaces, fechas, lugares, organizadores ni actividades.
- Cada URL debe ser la página original de la noticia o del evento, no el buscador, una
  página de resultados, una portada genérica ni un enlace inventado.
- No confundas la fecha de publicación con la fecha futura del evento.
- Si no podés verificar un dato, devolvé una cadena vacía.
- Devolvé hasta 24 resultados, priorizando los más importantes y variados. Evitá duplicados.
- Para noticias, la fecha de publicación debe corresponder a las últimas 24 horas.
- Para eventos, informá la fecha exacta del evento y, si están visibles, localidad y
  organizador. No incluyas eventos pasados ni eventos sin fecha futura verificable.

Respondé únicamente con el objeto JSON del esquema solicitado. En "summary" escribí
una descripción concreta y breve, sin agregar datos que la fuente no respalde.
"".strip()


def ai_title_matches(candidate_title: str, page_title: str) -> bool:
    def tokens(value: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z0-9]{4,}", normalize(value))
            if token not in {"para", "desde", "sobre", "entre", "segun", "tras", "esta", "este"}
        }
    wanted = tokens(candidate_title)
    actual = tokens(page_title)
    if not wanted or not actual:
        return False
    overlap = len(wanted & actual) / max(1, len(wanted))
    return overlap >= 0.35 or normalize(candidate_title) in normalize(page_title)


def ai_event_date_visible(event_date: datetime, body_text: str) -> bool:
    """Comprueba que día y mes del evento figuren realmente en la página."""
    visible_dates = extract_text_dates(body_text)
    if event_date.date() in {d.date() for d in visible_dates}:
        return True
    # Si aparece el mismo día/mes con otro año explícito, no asumimos que
    # la actividad se repite en el año que propone el modelo.
    if any(d.day == event_date.day and d.month == event_date.month for d in visible_dates):
        return False
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    month = months[event_date.month - 1]
    text = normalize(body_text)
    day = event_date.day
    # Admite formatos como "18 de noviembre", "18 y 19 de noviembre"
    # o "18/11", aunque la página no imprima el año.
    month_pattern = rf"\b0?{day}\b.{{0,55}}\b{month}\b"
    numeric_pattern = rf"\b0?{day}[/.-]0?{event_date.month}\b"
    return bool(re.search(month_pattern, text) or re.search(numeric_pattern, text))

def ai_hard_excluded(text: str) -> bool:
    """Aplica exclusiones inequívocas aun cuando el modelo proponga un resultado."""
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


def verify_ai_candidate(candidate: dict[str, Any], now: datetime) -> Item | None:
    """Abre la página original y comprueba contenido, fechas y pertinencia."""
    title_hint = clean_text(str(candidate.get("title") or ""), 300)
    url = str(candidate.get("url") or "").strip()
    parsed_url = urlparse(url)
    if (
        len(title_hint) < 12
        or parsed_url.scheme not in ("http", "https")
        or not parsed_url.netloc
        or any(host in parsed_url.netloc.lower() for host in ("google.", "bing.com", "search.yahoo."))
    ):
        return None

    raw, final_url, status = fetch(url, timeout=(10, 25))
    if not raw or status >= 400:
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
    if not ai_title_matches(title_hint, title):
        return None

    description = ""
    for attrs in (
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 900)
            break

    article_node = soup.find("article") or soup.find("main") or soup.body or soup
    body_text = clean_text(article_node.get_text(" ", strip=True), 12000)
    if len(body_text) < 80 and len(description) < 40:
        return None

    full_text = f"{title} {description} {body_text[:10000]}"
    if ai_hard_excluded(full_text):
        return None

    kind = str(candidate.get("kind") or "").strip().lower()
    if kind not in ("news", "event"):
        return None

    page_published = extract_published_date(soup)
    model_published = parse_datetime(candidate.get("publication_date"))
    published = page_published or model_published

    if kind == "news":
        # Para noticias no se acepta una fecha estimada: debe poder verificarse
        # en metadatos de la página o en el contenido publicado por el medio.
        visible_dates = {d.date() for d in extract_text_dates(body_text[:6000])}
        if page_published is None and (
            model_published is None or model_published.date() not in visible_dates
        ):
            return None
        if not is_within_window(published, now):
            return None
        section = "Noticia"
        event_date = ""
        location = ""
        organizer = ""
        date_label = "Publicado"
    else:
        # Los eventos pueden haber sido anunciados días antes; se conservan
        # si la actividad todavía no ocurrió y su fecha aparece en la página.
        event_date_value = parse_datetime(candidate.get("event_date"))
        page_dates = extract_text_dates(body_text[:10000])
        if event_date_value is None or not ai_event_date_visible(event_date_value, body_text[:10000]):
            # Respaldo: tomar la primera fecha futura con año que realmente figura en la página.
            future_dates = [
                d for d in page_dates
                if now.date() <= d.date() <= (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).date()
            ]
            if not future_dates:
                return None
            event_date_value = min(future_dates)
        if not (now.date() <= event_date_value.date() <= (now + timedelta(days=AI_EVENT_HORIZON_DAYS)).date()):
            return None
        section = "Evento"
        event_date = event_date_value.strftime("%d/%m/%Y")
        location = clean_text(str(candidate.get("location") or ""), 180)
        organizer = clean_text(str(candidate.get("organizer") or ""), 180)
        # No se conserva una fecha de publicación sugerida por el modelo si
        # la página no ofrece metadatos verificables para un evento.
        if page_published is None:
            published = now
            date_label = "Detectado"
        else:
            published = page_published
            date_label = "Publicado"
        if location and normalize(location) not in normalize(full_text):
            location = ""
        if organizer and normalize(organizer) not in normalize(full_text):
            organizer = ""

    if published is None:
        return None

    category = clean_text(str(candidate.get("category") or "Lechería"), 80)
    summary = clean_text(str(candidate.get("summary") or ""), 480)
    if not summary:
        summary = summarize(description or body_text, 360)

    try:
        score = max(1, min(100, int(candidate.get("relevance", 75))))
    except (TypeError, ValueError):
        score = 75
    source_name = clean_text(str(candidate.get("source_name") or parsed_url.netloc), 120)

    return Item(
        title=title,
        url=final_url or url,
        source=f"IA web search · {source_name}",
        published_at=published,
        summary=summary,
        section=section,
        tags=[category],
        event_date=event_date,
        event_location=location,
        event_organizer=organizer,
        date_label=date_label,
        relevance=score,
    )


def scan_ai_web_search(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    """Busca noticias y agenda con OpenAI Web Search; funciona sin bloquear el radar."""
    status_row = {
        "fuente": "Búsqueda web con IA",
        "url": OPENAI_DOCS_URL,
        "estado": "consultada",
        "resultados": 0,
    }
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    enabled = os.getenv("RADAR_AI_WEB_SEARCH", "1").strip().lower() not in ("0", "false", "no")
    if not enabled:
        status_row["estado"] = "desactivada por configuración"
        return [], status_row
    if not api_key:
        status_row["estado"] = "no configurada: falta el secreto OPENAI_API_KEY"
        return [], status_row

    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": AI_ITEM_SCHEMA,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    payload = {
        "model": os.getenv("OPENAI_MODEL", AI_DEFAULT_MODEL),
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "tool_choice": "required",
        "max_output_tokens": 6000,
        "input": [
            {
                "role": "system",
                "content": (
                    "Sos un agente de búsqueda periodística. Debés buscar en la web, "
                    "contrastar la página original y devolver datos estructurados. "
                    "Nunca inventes fuentes, enlaces, fechas ni detalles de eventos."
                ),
            },
            {"role": "user", "content": ai_search_prompt(now)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "bot384520_dairy_radar",
                "strict": True,
                "schema": schema,
            }
        },
    }

    try:
        response = make_session().post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(20, 180),
        )
        if response.status_code >= 400:
            detail = clean_text(response.text, 500)
            status_row["estado"] = f"error API HTTP {response.status_code}: {detail}"
            LOG.warning("Búsqueda web IA: %s", status_row["estado"])
            return [], status_row
        response_data = response.json()
        output_text = ai_output_text(response_data)
        if not output_text:
            status_row["estado"] = "la API no devolvió contenido estructurado"
            LOG.warning("Búsqueda web IA: respuesta sin texto")
            return [], status_row
        data = json.loads(output_text)
        candidates = data.get("items", [])
        if not isinstance(candidates, list):
            raise ValueError("El campo items no es una lista")

        verified: list[Item] = []
        seen_urls: set[str] = set()
        for candidate in candidates[:AI_MAX_CANDIDATES]:
            if not isinstance(candidate, dict) or candidate.get("country") != "Argentina":
                continue
            url = str(candidate.get("url") or "").rstrip("/")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                item = verify_ai_candidate(candidate, now)
                if item:
                    verified.append(item)
            except Exception as exc:
                LOG.debug("No se pudo verificar resultado IA %s: %s", url, exc)

        status_row["resultados"] = len(verified)
        status_row["candidatos"] = len(candidates)
        status_row["estado"] = f"búsqueda completada; {len(verified)} verificados de {len(candidates)} candidatos"
        return verified, status_row
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        status_row["estado"] = f"error de búsqueda/procesamiento: {clean_text(str(exc), 260)}"
        LOG.warning("Búsqueda web IA no disponible: %s", exc)
        return [], status_row



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
    """Clasifica en una sola llamada las normas candidatas usando texto oficial."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, "IA no configurada: falta OPENAI_API_KEY; se usa el filtro de respaldo."

    compact_docs = []
    for index, doc in enumerate(documents):
        compact_docs.append({
            "index": index,
            "title": doc["title"],
            "area": doc["area"],
            "type": doc["notice_type"],
            "url": doc["url"],
            "publication_date": (
                doc["published_at"].strftime("%d/%m/%Y")
                if doc["published_at"] else ""
            ),
            "official_text": doc["body"][:5000],
        })

    prompt_text = f"""
Analizá estas publicaciones reales de la Primera Sección del Boletín Oficial argentino.
Tu función es seleccionar exclusivamente las normas y avisos que puedan afectar de
manera concreta a la lechería, los tambos o el ganado bovino, en especial el ganado lechero.

Incluí, cuando corresponda:
- producción de leche, tambos, establecimientos y plantas lácteas;
- sanidad, bienestar, identificación y trazabilidad de bovinos;
- vacunas, enfermedades, medicamentos veterinarios y requisitos de SENASA;
- reproducción, genética, crianza y movimiento de ganado lechero;
- alimentación animal, raciones, forrajes, pasturas, semillas y reservas;
- habilitaciones, registros, transporte, inocuidad y comercialización de leche;
- impuestos, créditos, emergencias, financiamiento y comercio cuando el texto
  alcance expresamente al sector agropecuario, a economías regionales o a la cadena láctea.

EXCLUÍ:
- designaciones y renuncias de personal sin efecto sectorial;
- normas administrativas genéricas sin incidencia identificable en el sector;
- agricultura, cultivos y mercados de granos sin relación expresa con alimentación animal;
- faena, carne, feedlots y producción ganadera cárnica sin vinculación lechera.

Reglas de análisis:
- No alcanza con que aparezca una palabra sectorial en un considerando incidental.
- Explicá qué cambia, a quién alcanza y si el efecto es directo o potencial.
- No infieras beneficios, obligaciones, subsidios ni exenciones que el texto no establezca.
- La puntuación va de 0 a 100. Usá relevancia >= 60 solo cuando el impacto sea claro.
- Si no es relevante, devolvé relevant=false, score=0 y textos vacíos.
- "evidence" debe ser una cita breve copiada literalmente del texto oficial que sustente
  el vínculo sectorial. Si no encontrás evidencia textual, marcá relevant=false.
- "what_to_check" debe señalar requisitos, sujetos, plazos o vigencia que el productor
  debería verificar; no reemplaza asesoramiento legal.
- Devolvé una entrada por cada documento, conservando exactamente su index.
- No inventes información. Respondé exclusivamente con el JSON del esquema.

DOCUMENTOS:
{json.dumps(compact_docs, ensure_ascii=False)}
""".strip()

    payload = {
        "model": os.getenv("OPENAI_BULLETIN_MODEL", AI_DEFAULT_MODEL),
        "reasoning": {"effort": "low"},
        "max_output_tokens": 7000,
        "input": [
            {
                "role": "system",
                "content": "Sos un analista jurídico-editorial del sector lechero argentino. El texto oficial es la única base de tus conclusiones.",
            },
            {"role": "user", "content": prompt_text},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "bot384520_bulletin_relevance",
                "strict": True,
                "schema": BOLETIN_AI_SCHEMA,
            }
        },
    }

    try:
        response = make_session().post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=(20, 180),
        )
        if response.status_code >= 400:
            return None, f"Error IA HTTP {response.status_code}: {clean_text(response.text, 300)}"
        output_text = ai_output_text(response.json())
        if not output_text:
            return None, "La IA no devolvió contenido estructurado; se usa el filtro de respaldo."
        data = json.loads(output_text)
        rows = data.get("items", [])
        if not isinstance(rows, list):
            return None, "La respuesta IA no contiene una lista válida; se usa el filtro de respaldo."
        mapped: dict[int, dict[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("index"), int):
                mapped[row["index"]] = row
        return mapped, f"análisis IA completado: {len(mapped)} documentos evaluados"
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return None, f"Error de análisis IA: {clean_text(str(exc), 300)}"


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
        f"**Impacto para la lechería:** {impact}\n\n"
        f"**A quiénes puede alcanzar:** {actors}\n\n"
        f"**Qué conviene verificar:** {what_to_check}\n\n"
        f"**Fundamento en el texto oficial:** “{evidence}”\n\n"
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

    documents.sort(key=lambda doc: (doc["published_at"] or datetime.min.replace(tzinfo=TZ), doc["title"]))
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
    if item.section == "Evento" and item.source.startswith("IA web search"):
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
</main><footer>BOT 384520 · Búsqueda asistida por IA y filtros automáticos · Las fuentes originales prevalecen sobre el resumen. Verificar vigencia y alcance de toda normativa en el texto oficial.</footer>
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
    try:
        google_items, google_status = scan_google_news(now)
        all_items.extend(google_items)
        statuses.append(google_status)
        LOG.info("Google News: %s resultados", len(google_items))
    except Exception as exc:
        statuses.append({"fuente": "Google News RSS", "url": "https://news.google.com/", "estado": f"error: {exc}"})

    # Búsqueda ampliada con IA: noticias de las últimas 24 h y eventos próximos.
    try:
        ai_items, ai_status = scan_ai_web_search(now)
        all_items.extend(ai_items)
        statuses.append(ai_status)
        LOG.info("Búsqueda web con IA: %s resultados verificados", len(ai_items))
    except Exception as exc:
        statuses.append({
            "fuente": "Búsqueda web con IA",
            "url": OPENAI_DOCS_URL,
            "estado": f"error: {clean_text(str(exc), 260)}",
            "resultados": 0,
        })
        LOG.exception("Error en búsqueda web con IA")

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
