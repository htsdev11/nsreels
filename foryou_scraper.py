import base64
import hashlib
import json
import logging
import os
import random
import re
import string
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

import django
import requests
from requests.adapters import HTTPAdapter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
django.setup()

from django.db import close_old_connections
from django.utils.text import slugify
from api.models import (
    ShortDrama,
    ShortDramaCountry,
    ShortDramaEpisode,
    ShortDramaForyou,
    ShortDramaGenre,
)


# --------------------------------------------------
# LOGGING
# --------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------
# CONFIG
# --------------------------------------------------
TAB_URL = (
    "https://h5-api.aoneroom.com/"
    "wefeed-h5api-bff/vskit/tab-operation-list"
)

RECOMMEND_URL = (
    "https://h5-api.aoneroom.com/"
    "wefeed-h5api-bff/vskit/recommend-list"
)

SITE_HOME_URL = "https://vskit.online/"
WATCH_BASE_URL = "https://vskit.online/watch"

PER_PAGE = 20
TRENDING_PAGES = 5

CATEGORY_WORKERS = 3

# Keep episode scraping sequential for safety.
# This prevents all missing episodes being submitted before a stale slug is detected.
EPISODE_WORKERS = 1

REQUEST_TIMEOUT = 30
RETRY_LIMIT = 3
RETRY_DELAY = 2

DELAY_BETWEEN_EPISODES = 0.7
DELAY_BETWEEN_DRAMAS = 10
DELAY_BETWEEN_TRENDING_PAGES = 3

SCRAPE_EPISODES = True

GENRE_CACHE = {}
COUNTRY_CACHE = {}

_thread_local = threading.local()


# --------------------------------------------------
# AUTH
# --------------------------------------------------
AUTH_COOKIE_NAMES = (
    "token",
    "access_token",
    "accessToken",
)

JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)

_auth_lock = threading.Lock()


def normalize_bearer_token(value):
    value = (value or "").strip()

    if value.lower().startswith("bearer "):
        value = value[7:].strip()

    return value


def jwt_expiry_timestamp(token):
    token = normalize_bearer_token(token)

    try:
        parts = token.split(".")

        if len(parts) != 3:
            return None

        payload = parts[1]
        payload += "=" * (-len(payload) % 4)

        data = json.loads(
            base64.urlsafe_b64decode(
                payload.encode("ascii")
            ).decode("utf-8")
        )

        exp = data.get("exp")
        return int(exp) if exp is not None else None

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return None


def bearer_token_is_usable(token, leeway=60):
    token = normalize_bearer_token(token)

    if not token:
        return False

    exp = jwt_expiry_timestamp(token)

    # If the token is opaque rather than JWT, let the server validate it.
    if exp is None:
        return True

    return exp > int(time.time()) + leeway


def iter_cookie_string(cookie_string):
    cookie_text = (
        (cookie_string or "")
        .replace("…", "")
        .encode("ascii", "ignore")
        .decode()
    )

    for item in cookie_text.split(";"):
        item = item.strip()

        if "=" not in item:
            continue

        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key:
            yield key, value


BEARER_TOKEN = normalize_bearer_token(
    os.getenv("VSKIT_BEARER_TOKEN", "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOjQ2Mjg4NjM1NjEzNTAyNDQzNDQsImF0cCI6MywiZXh0IjoiMTc4NjE5OTgyOCIsImV4cCI6MTc5Mzk3NTgyOCwiaWF0IjoxNzg2MTk5NTI4fQ.D3f4vFQwICvmyl8L7Qijv3SPEnZdsn_2xv0F-cwqOl0")
)

COOKIE_STRING = os.getenv(
    "VSKIT_COOKIE_STRING",
    "",
)


# --------------------------------------------------
# EXCEPTIONS
# --------------------------------------------------
class DramaUnavailableError(Exception):
    """Raised when VSKit returns an empty watch page for a drama."""


# --------------------------------------------------
# BASIC HELPERS
# --------------------------------------------------
def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def random_rsc_value(length=8):
    alphabet = (
        string.ascii_lowercase
        + string.digits
    )

    return "".join(
        random.choice(alphabet)
        for _ in range(length)
    )


def extract_expiry(play_url):
    if not play_url:
        return None

    try:
        query = parse_qs(
            urlparse(play_url).query
        )

        values = (
            query.get("Expires")
            or query.get("expires")
            or query.get("expire")
        )

        if not values:
            return None

        return datetime.fromtimestamp(
            int(values[0]),
            tz=timezone.utc,
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
        IndexError,
    ):
        return None


# --------------------------------------------------
# NEXT.JS ROUTER STATE
# --------------------------------------------------
def build_next_router_state_tree(drama_slug):
    state = [
        "",
        {
            "children": [
                ["locale", "en", "d"],
                {
                    "children": [
                        "watch",
                        {
                            "children": [
                                [
                                    "slug",
                                    drama_slug,
                                    "d",
                                ],
                                {
                                    "children": [
                                        "__PAGE__",
                                        {},
                                        None,
                                        "refetch",
                                    ]
                                },
                                None,
                                None,
                            ]
                        },
                        None,
                        None,
                    ]
                },
                None,
                None,
            ]
        },
        None,
        None,
    ]

    compact_json = json.dumps(
        state,
        separators=(",", ":"),
    )

    return quote(
        compact_json,
        safe="",
    )


# --------------------------------------------------
# SESSION HELPERS
# --------------------------------------------------
def add_cookie_string(
    http_session,
    include_auth_cookie=True,
):
    for key, value in iter_cookie_string(
        COOKIE_STRING
    ):
        # Never let a stale token from VSKIT_COOKIE_STRING
        # override a freshly fetched bearer token.
        if key in AUTH_COOKIE_NAMES:
            continue

        http_session.cookies.set(
            key,
            value,
            domain="vskit.online",
            path="/",
        )

    if include_auth_cookie and BEARER_TOKEN:
        http_session.cookies.set(
            "token",
            BEARER_TOKEN,
            domain="vskit.online",
            path="/",
        )


def extract_token_from_session(
    http_session,
    response=None,
):
    candidates = []

    # Prefer explicit auth cookies set by the site.
    for cookie in http_session.cookies:
        if cookie.name in AUTH_COOKIE_NAMES:
            candidates.append(cookie.value)

    if response is not None:
        authorization = response.headers.get(
            "Authorization",
            "",
        )

        if authorization:
            candidates.append(authorization)

        # Fallback: some Next.js responses serialize the anonymous JWT
        # in page/RSC data instead of exposing it as a readable cookie.
        candidates.extend(
            JWT_PATTERN.findall(response.text or "")
        )

    for candidate in candidates:
        candidate = normalize_bearer_token(
            candidate
        )

        if bearer_token_is_usable(candidate):
            return candidate

    return ""


def fetch_bearer_token_from_site():
    bootstrap_session = requests.Session()

    bootstrap_session.headers.update({
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Ubuntu; Linux x86_64; rv:152.0) "
            "Gecko/20100101 Firefox/152.0"
        ),
    })

    # Keep non-auth cookies if the user supplied them, but deliberately
    # omit any old token so the site can issue a fresh anonymous token.
    add_cookie_string(
        bootstrap_session,
        include_auth_cookie=False,
    )

    try:
        response = bootstrap_session.get(
            SITE_HOME_URL,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

        token = extract_token_from_session(
            bootstrap_session,
            response=response,
        )

        if token:
            logger.info(
                "Fetched bearer token automatically from VSKit."
            )
            return token

        logger.warning(
            "VSKit homepage loaded, but no bearer token "
            "was found in cookies, headers, or page data."
        )

    except requests.RequestException as exc:
        logger.warning(
            "Could not fetch bearer token from VSKit: %s",
            exc,
        )

    finally:
        bootstrap_session.close()

    return ""


def apply_bearer_token_to_session(
    http_session,
    include_cookie=False,
):
    if BEARER_TOKEN:
        http_session.headers["Authorization"] = (
            f"Bearer {BEARER_TOKEN}"
        )

        if include_cookie:
            http_session.cookies.set(
                "token",
                BEARER_TOKEN,
                domain="vskit.online",
                path="/",
            )
    else:
        http_session.headers.pop(
            "Authorization",
            None,
        )


def refresh_bearer_token(force=False):
    global BEARER_TOKEN

    with _auth_lock:
        if (
            not force
            and bearer_token_is_usable(
                BEARER_TOKEN
            )
        ):
            return BEARER_TOKEN

        old_token = BEARER_TOKEN
        fresh_token = fetch_bearer_token_from_site()

        if fresh_token:
            BEARER_TOKEN = fresh_token
        elif bearer_token_is_usable(old_token):
            logger.warning(
                "Automatic token fetch failed; "
                "using VSKIT_BEARER_TOKEN fallback."
            )
            BEARER_TOKEN = old_token
        else:
            BEARER_TOKEN = ""

        current_api_session = globals().get(
            "api_session"
        )

        if current_api_session is not None:
            apply_bearer_token_to_session(
                current_api_session
            )

        current_episode_session = getattr(
            _thread_local,
            "episode_session",
            None,
        )

        if current_episode_session is not None:
            apply_bearer_token_to_session(
                current_episode_session,
                include_cookie=True,
            )

        return BEARER_TOKEN


def build_api_session():
    http_session = requests.Session()

    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Origin": "https://vskit.online",
        "Referer": "https://vskit.online/",
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Ubuntu; Linux x86_64; rv:152.0) "
            "Gecko/20100101 Firefox/152.0"
        ),
        "X-Client-Info": (
            '{"timezone":"Asia/Karachi"}'
        ),
        "X-Request-Lang": "en",
        "X-Site-Domain": "https://vskit.online",
    }

    http_session.headers.update(headers)
    apply_bearer_token_to_session(
        http_session
    )

    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=0,
    )

    http_session.mount(
        "https://",
        adapter,
    )

    return http_session


def build_episode_session():
    http_session = requests.Session()

    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Ubuntu; Linux x86_64; rv:152.0) "
            "Gecko/20100101 Firefox/152.0"
        ),
        "Origin": "https://vskit.online",
        "Referer": "https://vskit.online/",
        "RSC": "1",
        "Priority": "u=4",
    }

    http_session.headers.update(headers)
    apply_bearer_token_to_session(
        http_session,
        include_cookie=True,
    )

    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=0,
    )

    http_session.mount(
        "https://",
        adapter,
    )

    add_cookie_string(
        http_session
    )

    return http_session


# Fetch a fresh anonymous token on startup. The environment token is
# retained only as a fallback if the site cannot be reached.
refresh_bearer_token(force=True)
api_session = build_api_session()


def get_episode_session():
    http_session = getattr(
        _thread_local,
        "episode_session",
        None,
    )

    if http_session is None:
        http_session = (
            build_episode_session()
        )

        _thread_local.episode_session = (
            http_session
        )

    return http_session


# --------------------------------------------------
# API REQUESTS
# --------------------------------------------------
def request_json(
    url,
    params=None,
    description="request",
):
    if not bearer_token_is_usable(
        BEARER_TOKEN
    ):
        refresh_bearer_token(force=True)

    if not BEARER_TOKEN:
        raise RuntimeError(
            "Could not obtain a VSKit bearer token."
        )

    for attempt in range(
        1,
        RETRY_LIMIT + 1,
    ):
        try:
            response = api_session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            logger.info(
                "%s | attempt=%s | status=%s",
                description,
                attempt,
                response.status_code,
            )

            if response.status_code == 401:
                logger.warning(
                    "Bearer token was rejected; "
                    "fetching a fresh token."
                )

                if refresh_bearer_token(
                    force=True
                ):
                    continue

                logger.error(
                    "Bearer token refresh failed."
                )
                return None

            if response.status_code == 429:
                retry_after = safe_int(
                    response.headers.get(
                        "Retry-After"
                    ),
                    RETRY_DELAY * attempt,
                )

                time.sleep(
                    retry_after
                )
                continue

            if response.status_code != 200:
                logger.warning(
                    "%s returned HTTP %s: %s",
                    description,
                    response.status_code,
                    response.text[:500],
                )

                time.sleep(
                    RETRY_DELAY * attempt
                )
                continue

            try:
                payload = response.json()

            except requests.exceptions.JSONDecodeError:
                logger.warning(
                    "%s returned invalid JSON.",
                    description,
                )

                time.sleep(
                    RETRY_DELAY * attempt
                )
                continue

            if payload.get("code") not in (
                None,
                0,
            ):
                logger.warning(
                    "%s API error code=%s message=%s",
                    description,
                    payload.get("code"),
                    payload.get("message"),
                )

                time.sleep(
                    RETRY_DELAY * attempt
                )
                continue

            return payload

        except requests.RequestException as exc:
            logger.warning(
                "%s failed on attempt %s/%s: %s",
                description,
                attempt,
                RETRY_LIMIT,
                exc,
            )

        time.sleep(
            RETRY_DELAY * attempt
        )

    return None


def fetch_foryou():
    payload = request_json(
        TAB_URL,
        description="Fetch ForYou categories",
    )

    if not payload:
        return []

    data = payload.get("data") or {}
    items = data.get("list") or []

    return (
        items
        if isinstance(items, list)
        else []
    )


def fetch_recommend_page(page):
    payload = request_json(
        RECOMMEND_URL,
        params={
            "page": page,
            "perPage": PER_PAGE,
            "novelType": 3,
        },
        description=(
            f"Fetch trending page {page}"
        ),
    )

    if not payload:
        return []

    data = payload.get("data") or {}
    items = data.get("list") or []

    return (
        items
        if isinstance(items, list)
        else []
    )


# --------------------------------------------------
# RSC PARSING
# --------------------------------------------------
def extract_json_object_after_key(
    raw_text,
    key,
):
    marker = re.search(
        rf'"{re.escape(key)}"\s*:\s*',
        raw_text,
    )

    if not marker:
        return None

    start = marker.end()

    while (
        start < len(raw_text)
        and raw_text[start].isspace()
    ):
        start += 1

    if (
        start >= len(raw_text)
        or raw_text[start] != "{"
    ):
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(
        start,
        len(raw_text),
    ):
        char = raw_text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1

            if depth == 0:
                return raw_text[
                    start:index + 1
                ]

    return None


def extract_json_string(
    raw_text,
    key,
):
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*'
        r'("(?:\\.|[^"\\])*")',
        raw_text,
    )

    if not match:
        return None

    try:
        return json.loads(
            match.group(1)
        )
    except json.JSONDecodeError:
        return None


def extract_json_integer(
    raw_text,
    key,
):
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*(-?\d+)',
        raw_text,
    )

    if not match:
        return None

    return safe_int(
        match.group(1),
        default=None,
    )


def extract_json_array(
    raw_text,
    key,
):
    marker = re.search(
        rf'"{re.escape(key)}"\s*:\s*',
        raw_text,
    )

    if not marker:
        return None

    start = marker.end()

    while (
        start < len(raw_text)
        and raw_text[start].isspace()
    ):
        start += 1

    if (
        start >= len(raw_text)
        or raw_text[start] != "["
    ):
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(
        start,
        len(raw_text),
    ):
        char = raw_text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1

            if depth == 0:
                try:
                    value = json.loads(
                        raw_text[
                            start:index + 1
                        ]
                    )

                    return (
                        value
                        if isinstance(value, list)
                        else None
                    )

                except json.JSONDecodeError:
                    return None

    return None


def extract_current_episode(raw_text):
    episode_json = (
        extract_json_object_after_key(
            raw_text,
            "currentEpisode",
        )
    )

    if not episode_json:
        return None, {}

    try:
        episode_data = json.loads(
            episode_json
        )

    except json.JSONDecodeError:
        return None, {}

    metadata = {
        "genre": extract_json_string(
            raw_text,
            "genre",
        ),
        "countryName": extract_json_string(
            raw_text,
            "countryName",
        ),
        "releaseDate": extract_json_string(
            raw_text,
            "releaseDate",
        ),
        "description": extract_json_string(
            raw_text,
            "description",
        ),
        "dramaTitle": extract_json_string(
            raw_text,
            "dramaTitle",
        ),
        "subjectSeoKey": extract_json_string(
            raw_text,
            "subjectSeoKey",
        ),
        "totalEpisode": extract_json_integer(
            raw_text,
            "totalEpisode",
        ),
        "tags": extract_json_array(
            raw_text,
            "tags",
        ),
    }

    return (
        episode_data,
        {
            key: value
            for key, value in metadata.items()
            if value is not None
        },
    )


def is_empty_watch_page(
    raw_text,
    episode_number,
):
    empty_title = (
        f"Watch  Episode {episode_number} - VSKit | VSKit"
        in raw_text
    )

    empty_description = (
        f"Stream  episode {episode_number} free in HD on VSKit."
        in raw_text
    )

    return (
        empty_title
        and empty_description
        and "currentEpisode" not in raw_text
    )


# --------------------------------------------------
# METADATA HELPERS
# --------------------------------------------------
def get_or_create_genre(genre_name):
    genre_name = (
        genre_name or ""
    ).strip()

    if not genre_name:
        return None

    cache_key = genre_name.casefold()

    if cache_key in GENRE_CACHE:
        return GENRE_CACHE[
            cache_key
        ]

    genre = (
        ShortDramaGenre.objects
        .filter(
            name__iexact=genre_name,
        )
        .first()
    )

    if genre is None:
        genre = (
            ShortDramaGenre.objects
            .create(
                name=genre_name,
                slug=slugify(
                    genre_name
                ),
            )
        )

    GENRE_CACHE[cache_key] = genre

    return genre


def get_or_create_country(country_name):
    country_name = (
        country_name or ""
    ).strip()

    if not country_name:
        return None

    cache_key = country_name.casefold()

    if cache_key in COUNTRY_CACHE:
        return COUNTRY_CACHE[
            cache_key
        ]

    country = (
        ShortDramaCountry.objects
        .filter(
            name__iexact=country_name,
        )
        .first()
    )

    if country is None:
        country = (
            ShortDramaCountry.objects
            .create(
                name=country_name,
                slug=slugify(
                    country_name
                ),
            )
        )

    COUNTRY_CACHE[cache_key] = country

    return country


def update_drama_metadata(
    drama,
    metadata,
):
    if not metadata:
        return False

    changed = False
    update_fields = []

    country_name = metadata.get(
        "countryName"
    )

    if (
        drama.country_id is None
        and country_name
    ):
        country = get_or_create_country(
            country_name
        )

        if country:
            drama.country = country
            update_fields.append(
                "country"
            )
            changed = True

            logger.info(
                "[%s] Added country: %s",
                drama.title,
                country.name,
            )

    release_date_value = metadata.get(
        "releaseDate"
    )

    if (
        drama.release_date is None
        and release_date_value
    ):
        try:
            drama.release_date = (
                datetime.strptime(
                    release_date_value,
                    "%Y-%m-%d",
                )
                .date()
            )

            update_fields.append(
                "release_date"
            )

            changed = True

            logger.info(
                "[%s] Added release date: %s",
                drama.title,
                drama.release_date,
            )

        except ValueError:
            logger.warning(
                "[%s] Invalid release date: %r",
                drama.title,
                release_date_value,
            )

    description = metadata.get(
        "description"
    )

    if (
        not drama.description
        and description
    ):
        drama.description = description

        update_fields.append(
            "description"
        )

        changed = True

    total_episode = safe_int(
        metadata.get(
            "totalEpisode"
        ),
        default=0,
    )

    if (
        total_episode > 0
        and drama.total_episodes
        != total_episode
    ):
        drama.total_episodes = (
            total_episode
        )

        update_fields.append(
            "total_episodes"
        )

        changed = True

    tags = metadata.get("tags")

    if tags and not drama.tags:
        drama.tags = tags

        update_fields.append(
            "tags"
        )

        changed = True

    if update_fields:
        drama.save(
            update_fields=list(
                dict.fromkeys(
                    update_fields
                )
            )
        )

    if not drama.genres.exists():
        genre_string = metadata.get(
            "genre"
        )

        if genre_string:
            normalized = (
                genre_string
                .replace("|", ",")
                .replace("/", ",")
                .replace(";", ",")
            )

            genres = []

            for genre_name in (
                normalized.split(",")
            ):
                genre = get_or_create_genre(
                    genre_name
                )

                if genre:
                    genres.append(
                        genre
                    )

            if genres:
                unique_genres = {
                    genre.pk: genre
                    for genre in genres
                }

                drama.genres.set(
                    unique_genres.values()
                )

                changed = True

                logger.info(
                    "[%s] Added genres: %s",
                    drama.title,
                    ", ".join(
                        genre.name
                        for genre
                        in unique_genres.values()
                    ),
                )

    return changed


# --------------------------------------------------
# SAVE DRAMA
# --------------------------------------------------
def save_drama(drama_data):
    subject_id = drama_data.get(
        "subjectId"
    )

    slug = drama_data.get(
        "subjectSeoKey"
    )

    if not subject_id or not slug:
        raise ValueError(
            "Drama is missing subjectId "
            "or subjectSeoKey."
        )

    obj, created = (
        ShortDrama.objects
        .update_or_create(
            subject_id=subject_id,
            defaults={
                "title": (
                    drama_data.get("title")
                    or ""
                ),
                "slug": slug,
                "cover": (
                    drama_data.get("cover")
                    or {}
                ),
                "tags": (
                    drama_data.get("tags")
                    or []
                ),
                "total_episodes": safe_int(
                    drama_data.get(
                        "totalEpisode"
                    ),
                    default=0,
                ),
                "total_views": (
                    drama_data.get(
                        "totalViews"
                    )
                ),
                "description": (
                    drama_data.get(
                        "description"
                    )
                    or ""
                ),
                "is_active": True,
            },
        )
    )

    logger.info(
        "%s drama: %s | episodes=%s",
        (
            "Created"
            if created
            else "Updated"
        ),
        obj.title,
        obj.total_episodes,
    )

    return obj


# --------------------------------------------------
# SAVE EPISODE
# --------------------------------------------------
def save_episode(
    drama,
    episode_data,
    metadata=None,
):
    episode_number = safe_int(
        episode_data.get("ep"),
        default=0,
    )

    if episode_number <= 0:
        raise ValueError(
            f"Invalid episode number: "
            f"{episode_data.get('ep')!r}"
        )

    if metadata:
        update_drama_metadata(
            drama,
            metadata,
        )

    video = (
        episode_data.get("video")
        or {}
    )

    video_address = (
        video.get("videoAddress")
        or {}
    )

    cover = (
        video.get("cover")
        or {}
    )

    play_url = (
        video_address.get("url")
    )

    ShortDramaEpisode.objects.update_or_create(
        drama=drama,
        episode_number=episode_number,
        defaults={
            "mini_id": (
                episode_data.get(
                    "miniId"
                )
            ),
            "subject_id": (
                episode_data.get(
                    "subjectId"
                )
                or drama.subject_id
            ),
            "season": safe_int(
                episode_data.get("se"),
                default=1,
            ),
            "play_url": play_url,
            "expires_at": extract_expiry(
                play_url
            ),
            "thumbnail": (
                cover.get("url")
            ),
            "duration": safe_int(
                video_address.get(
                    "duration"
                ),
                default=0,
            ),
            "width": safe_int(
                video_address.get(
                    "width"
                ),
                default=0,
            ),
            "height": safe_int(
                video_address.get(
                    "height"
                ),
                default=0,
            ),
            "file_size": safe_int(
                video_address.get(
                    "size"
                ),
                default=0,
            ),
            "lock_status": safe_int(
                episode_data.get(
                    "lockStatus"
                ),
                default=0,
            ),
            "is_active": True,
        },
    )


# --------------------------------------------------
# FETCH EPISODE
# --------------------------------------------------
def fetch_episode(
    drama,
    episode_number,
):
    if not drama.slug:
        return None, {}

    base_url = (
        f"{WATCH_BASE_URL}/"
        f"{drama.slug}"
    )

    params = {
        "ep": episode_number,
        "_rsc": random_rsc_value(),
    }

    visible_url = (
        f"{base_url}?ep={episode_number}"
    )

    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": visible_url,
        "Next-Url": (
            f"/en/watch/{drama.slug}"
            f"?ep={episode_number}"
        ),
        "Next-Router-State-Tree": (
            build_next_router_state_tree(
                drama.slug
            )
        ),
        "RSC": "1",
        "Priority": "u=4",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    http_session = get_episode_session()

    for attempt in range(
        1,
        RETRY_LIMIT + 1,
    ):
        try:
            response = http_session.get(
                base_url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )

            body_hash = hashlib.sha256(
                response.content
            ).hexdigest()[:16]

            logger.info(
                "[%s] Episode %s | attempt=%s | "
                "status=%s | content-type=%s | "
                "length=%s | sha256=%s | final-url=%s",
                drama.title,
                episode_number,
                attempt,
                response.status_code,
                content_type,
                len(response.content),
                body_hash,
                response.url,
            )

            if response.status_code == 401:
                logger.warning(
                    "[%s] Episode %s auth rejected; "
                    "refreshing bearer token.",
                    drama.title,
                    episode_number,
                )

                if refresh_bearer_token(
                    force=True
                ):
                    continue

            if response.status_code != 200:
                logger.warning(
                    "[%s] Episode %s returned HTTP %s: %s",
                    drama.title,
                    episode_number,
                    response.status_code,
                    response.text[:500],
                )

                time.sleep(
                    RETRY_DELAY * attempt
                )
                continue

            episode_data, metadata = (
                extract_current_episode(
                    response.text
                )
            )

            if episode_data:
                returned_episode = safe_int(
                    episode_data.get("ep"),
                    default=0,
                )

                if (
                    returned_episode
                    != int(episode_number)
                ):
                    logger.warning(
                        "[%s] Requested episode %s "
                        "but received episode %s.",
                        drama.title,
                        episode_number,
                        returned_episode,
                    )

                    time.sleep(
                        RETRY_DELAY * attempt
                    )
                    continue

                return (
                    episode_data,
                    metadata,
                )

            if is_empty_watch_page(
                response.text,
                episode_number,
            ):
                raise DramaUnavailableError(
                    "VSKit returned an empty watch page "
                    f"for slug={drama.slug}"
                )

            logger.warning(
                "[%s] Episode %s not found in RSC response "
                "(%s/%s). preview=%r",
                drama.title,
                episode_number,
                attempt,
                RETRY_LIMIT,
                response.text[:500],
            )

        except DramaUnavailableError:
            raise

        except requests.Timeout:
            logger.warning(
                "[%s] Episode %s timed out "
                "on attempt %s/%s.",
                drama.title,
                episode_number,
                attempt,
                RETRY_LIMIT,
            )

        except requests.RequestException as exc:
            logger.warning(
                "[%s] Episode %s request error: %s",
                drama.title,
                episode_number,
                exc,
            )

        time.sleep(
            RETRY_DELAY * attempt
        )

    return None, {}


# --------------------------------------------------
# DRAMA STATUS
# --------------------------------------------------
def mark_drama_inactive(
    drama,
    reason,
):
    if drama.is_active:
        drama.is_active = False

        drama.save(
            update_fields=[
                "is_active",
            ]
        )

    logger.error(
        "[%s] Marked inactive: %s",
        drama.title,
        reason,
    )


# --------------------------------------------------
# SCRAPE DRAMA EPISODES
# --------------------------------------------------
def scrape_drama_episodes(
    drama,
):
    total_episodes = safe_int(
        drama.total_episodes,
        default=0,
    )

    if total_episodes <= 0:
        logger.warning(
            "[%s] No total_episodes found.",
            drama.title,
        )
        return

    if not drama.slug:
        logger.warning(
            "[%s] No slug found.",
            drama.title,
        )
        return

    existing_eps = set(
        drama.episodes.values_list(
            "episode_number",
            flat=True,
        )
    )

    pending_eps = [
        episode_number
        for episode_number in range(
            1,
            total_episodes + 1,
        )
        if episode_number
        not in existing_eps
    ]

    if not pending_eps:
        logger.info(
            "[%s] Episodes already complete.",
            drama.title,
        )
        return

    logger.info(
        "[%s] Existing=%s pending=%s total=%s",
        drama.title,
        len(existing_eps),
        len(pending_eps),
        total_episodes,
    )

    skipped_eps = []

    # Sequential by design.
    # This lets us stop immediately when the first empty watch page appears.
    for episode_number in pending_eps:
        try:
            episode_data, metadata = (
                fetch_episode(
                    drama,
                    episode_number,
                )
            )

        except DramaUnavailableError as exc:
            mark_drama_inactive(
                drama,
                str(exc),
            )
            return

        if not episode_data:
            skipped_eps.append(
                episode_number
            )
            continue

        try:
            save_episode(
                drama,
                episode_data,
                metadata,
            )

            logger.info(
                "[%s] Saved episode %s",
                drama.title,
                episode_number,
            )

        except Exception:
            logger.exception(
                "[%s] Failed saving episode %s",
                drama.title,
                episode_number,
            )

            skipped_eps.append(
                episode_number
            )

        time.sleep(
            DELAY_BETWEEN_EPISODES
        )

    if skipped_eps:
        skipped_eps = sorted(
            set(skipped_eps)
        )

        logger.info(
            "[%s] Recovery pass: %s",
            drama.title,
            skipped_eps,
        )

        final_failed = []

        for episode_number in skipped_eps:
            try:
                episode_data, metadata = (
                    fetch_episode(
                        drama,
                        episode_number,
                    )
                )

            except DramaUnavailableError as exc:
                mark_drama_inactive(
                    drama,
                    str(exc),
                )
                return

            if not episode_data:
                final_failed.append(
                    episode_number
                )
                continue

            try:
                save_episode(
                    drama,
                    episode_data,
                    metadata,
                )

                logger.info(
                    "[%s] Recovery saved episode %s",
                    drama.title,
                    episode_number,
                )

            except Exception:
                logger.exception(
                    "[%s] Recovery save failed "
                    "for episode %s",
                    drama.title,
                    episode_number,
                )

                final_failed.append(
                    episode_number
                )

            time.sleep(
                DELAY_BETWEEN_EPISODES
            )

        if final_failed:
            logger.error(
                "[%s] Final failed episodes: %s",
                drama.title,
                final_failed,
            )

    final_count = (
        drama.episodes
        .filter(
            episode_number__gte=1,
            episode_number__lte=(
                total_episodes
            ),
        )
        .count()
    )

    logger.info(
        "[%s] Stored %s/%s episodes.",
        drama.title,
        final_count,
        total_episodes,
    )

    time.sleep(
        DELAY_BETWEEN_DRAMAS
    )


def scrape_episodes_for_dramas(
    drama_ids,
):
    unique_ids = list(
        dict.fromkeys(
            drama_ids
        )
    )

    if not unique_ids:
        return

    logger.info(
        "Scraping episodes for %s unique dramas.",
        len(unique_ids),
    )

    for drama_id in unique_ids:
        close_old_connections()

        try:
            drama = ShortDrama.objects.get(
                pk=drama_id
            )

        except ShortDrama.DoesNotExist:
            continue

        try:
            scrape_drama_episodes(
                drama
            )

        except Exception:
            logger.exception(
                "[%s] Unexpected episode scrape error",
                drama.title,
            )

        finally:
            close_old_connections()


# --------------------------------------------------
# SAVE FORYOU CATEGORY
# --------------------------------------------------
def save_category(
    category,
    index,
):
    close_old_connections()

    try:
        title = (
            category.get("title")
            or "Untitled"
        )

        cat, _ = (
            ShortDramaForyou.objects
            .update_or_create(
                title=title,
                defaults={
                    "order_by": index + 1,
                    "is_active": True,
                },
            )
        )

        if (
            title.casefold()
            != "trending now"
        ):
            cat.dramas.clear()

        existing = set(
            cat.dramas.values_list(
                "subject_id",
                flat=True,
            )
        )

        added = 0
        saved_drama_ids = []

        for drama_data in (
            category.get("novelItems")
            or []
        ):
            obj = save_drama(
                drama_data
            )

            saved_drama_ids.append(
                obj.id
            )

            if (
                obj.subject_id
                not in existing
            ):
                cat.dramas.add(
                    obj
                )

                existing.add(
                    obj.subject_id
                )

                added += 1

        logger.info(
            "Saved category: %s (%s added)",
            title,
            added,
        )

        return saved_drama_ids

    finally:
        close_old_connections()


# --------------------------------------------------
# EXTEND TRENDING NOW
# --------------------------------------------------
def extend_trending_now():
    try:
        trending = (
            ShortDramaForyou.objects
            .get(
                title__iexact=(
                    "Trending Now"
                ),
                is_active=True,
            )
        )

    except ShortDramaForyou.DoesNotExist:
        logger.warning(
            "Trending Now category not found."
        )
        return []

    existing = set(
        trending.dramas.values_list(
            "subject_id",
            flat=True,
        )
    )

    added = 0
    saved_drama_ids = []

    for page in range(
        1,
        TRENDING_PAGES + 1,
    ):
        dramas = fetch_recommend_page(
            page
        )

        logger.info(
            "Trending page %s: %s dramas",
            page,
            len(dramas),
        )

        for drama_data in dramas:
            obj = save_drama(
                drama_data
            )

            saved_drama_ids.append(
                obj.id
            )

            if obj.subject_id in existing:
                continue

            trending.dramas.add(
                obj
            )

            existing.add(
                obj.subject_id
            )

            added += 1

        time.sleep(
            DELAY_BETWEEN_TRENDING_PAGES
        )

    logger.info(
        "Added %s additional dramas to Trending Now.",
        added,
    )

    return saved_drama_ids


# --------------------------------------------------
# MAIN PIPELINE
# --------------------------------------------------
def scrape_and_save_foryou(
    max_workers=CATEGORY_WORKERS,
):
    categories = fetch_foryou()

    if not categories:
        logger.warning(
            "No categories found."
        )
        return

    logger.info(
        "Found %s categories.",
        len(categories),
    )

    all_drama_ids = []

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        futures = [
            executor.submit(
                save_category,
                category,
                index,
            )
            for index, category
            in enumerate(categories)
        ]

        for future in as_completed(
            futures
        ):
            try:
                saved_ids = (
                    future.result()
                )

                all_drama_ids.extend(
                    saved_ids
                )

            except Exception:
                logger.exception(
                    "Category worker failed."
                )

    logger.info(
        "Extending Trending Now."
    )

    trending_ids = (
        extend_trending_now()
    )

    all_drama_ids.extend(
        trending_ids
    )

    if SCRAPE_EPISODES:
        scrape_episodes_for_dramas(
            all_drama_ids
        )

    logger.info(
        "Done."
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------
if __name__ == "__main__":
    logger.info(
        "Starting ForYou scraper."
    )

    try:
        scrape_and_save_foryou(
            max_workers=(
                CATEGORY_WORKERS
            )
        )

    except KeyboardInterrupt:
        logger.info(
            "ForYou scraper stopped by user."
        )

    finally:
        api_session.close()
        close_old_connections()

        logger.info(
            "ForYou scraper finished."
        )