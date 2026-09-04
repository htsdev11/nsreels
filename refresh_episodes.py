import hashlib
import json
import logging
import os
import random
import re
import string
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlparse

import django
import requests
from requests.adapters import HTTPAdapter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
django.setup()

from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone as dj_timezone
from django.utils.text import slugify

from api.models import (
    ShortDrama,
    ShortDramaCountry,
    ShortDramaEpisode,
    ShortDramaGenre,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------
# REQUEST CONFIG
# --------------------------------------------------
REQUEST_TIMEOUT = 30
RETRY_LIMIT = 3
RETRY_DELAY = 2

WATCH_BASE_URL = "https://vskit.online/watch"

GENRE_CACHE = {}
COUNTRY_CACHE = {}


# --------------------------------------------------
# URL REFRESH CONFIG
# --------------------------------------------------
REFRESH_BUFFER = timedelta(minutes=30)
DELAY_BETWEEN_EPISODES = 0.5
DELAY_BETWEEN_DRAMAS = 5
LOCK_TIMEOUT = 900


# --------------------------------------------------
# AUTH
# --------------------------------------------------
def normalize_bearer_token(value):
    value = (value or "").strip()

    if value.lower().startswith("bearer "):
        value = value[7:].strip()

    return value


BEARER_TOKEN = normalize_bearer_token(
    os.getenv("VSKIT_BEARER_TOKEN", "")
)

COOKIE_STRING = os.getenv(
    "VSKIT_COOKIE_STRING",
    "",
)


# --------------------------------------------------
# EXCEPTIONS
# --------------------------------------------------
class DramaUnavailableError(Exception):
    """Raised when VSKit returns an empty watch page for the drama."""


# --------------------------------------------------
# HELPERS
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
# SESSION
# --------------------------------------------------
def build_session():
    http_session = requests.Session()

    http_session.headers.update(
        {
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
    )

    if BEARER_TOKEN:
        http_session.headers[
            "Authorization"
        ] = f"Bearer {BEARER_TOKEN}"

    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=0,
    )

    http_session.mount(
        "https://",
        adapter,
    )

    found_token_cookie = False

    cookie_text = (
        COOKIE_STRING
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

        if not key:
            continue

        if key == "token":
            found_token_cookie = True

        http_session.cookies.set(
            key,
            value,
            domain="vskit.online",
            path="/",
        )

    if BEARER_TOKEN and not found_token_cookie:
        http_session.cookies.set(
            "token",
            BEARER_TOKEN,
            domain="vskit.online",
            path="/",
        )

        logger.warning(
            "No token cookie was found in VSKIT_COOKIE_STRING; "
            "a token cookie was created from VSKIT_BEARER_TOKEN."
        )

    logger.info(
        "Session bearer=%s cookie_string=%s cookie_names=%s",
        bool(BEARER_TOKEN),
        bool(COOKIE_STRING.strip()),
        list(http_session.cookies.keys()),
    )

    return http_session


session = build_session()


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
                        if isinstance(
                            value,
                            list,
                        )
                        else None
                    )

                except json.JSONDecodeError:
                    return None

    return None


def extract_episode_and_metadata(
    raw_text,
):
    current_episode_text = (
        extract_json_object_after_key(
            raw_text,
            "currentEpisode",
        )
    )

    if not current_episode_text:
        return None, {}

    try:
        episode_data = json.loads(
            current_episode_text
        )

    except json.JSONDecodeError as exc:
        logger.warning(
            "Could not decode currentEpisode: %s",
            exc,
        )

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
# FETCH EPISODE
# --------------------------------------------------
def fetch_rsc_episode(
    drama,
    episode_number,
):
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

    for attempt in range(
        1,
        RETRY_LIMIT + 1,
    ):
        try:
            response = session.get(
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
                extract_episode_and_metadata(
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

                return episode_data, metadata

            if is_empty_watch_page(
                response.text,
                episode_number,
            ):
                raise DramaUnavailableError(
                    f"VSKit returned an empty watch page "
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
# METADATA HELPERS
# --------------------------------------------------
def get_or_create_genre(
    genre_name,
):
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


def get_or_create_country(
    country_name,
):
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

        if country is not None:
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
            release_date = (
                datetime.strptime(
                    release_date_value,
                    "%Y-%m-%d",
                )
                .date()
            )

            drama.release_date = (
                release_date
            )
            update_fields.append(
                "release_date"
            )
            changed = True

            logger.info(
                "[%s] Added release date: %s",
                drama.title,
                release_date,
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
        update_fields.append("tags")
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

            genre_objects = []

            for genre_name in (
                normalized.split(",")
            ):
                genre = (
                    get_or_create_genre(
                        genre_name
                    )
                )

                if genre is not None:
                    genre_objects.append(
                        genre
                    )

            if genre_objects:
                unique_genres = {
                    genre.pk: genre
                    for genre
                    in genre_objects
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
# REFRESH LOGIC
# --------------------------------------------------
def episode_needs_refresh(
    episode,
    refresh_before,
):
    return (
        not episode.play_url
        or episode.expires_at is None
        or episode.expires_at
        <= refresh_before
    )


def refresh_episode(
    ep_obj,
):
    episode_data, metadata = (
        fetch_rsc_episode(
            ep_obj.drama,
            ep_obj.episode_number,
        )
    )

    if not episode_data:
        logger.error(
            "[%s] Failed episode %s",
            ep_obj.drama.title,
            ep_obj.episode_number,
        )

        return False

    if metadata:
        update_drama_metadata(
            ep_obj.drama,
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

    if not play_url:
        logger.error(
            "[%s] Episode %s returned no play URL.",
            ep_obj.drama.title,
            ep_obj.episode_number,
        )

        return False

    ep_obj.mini_id = (
        episode_data.get("miniId")
    )

    ep_obj.subject_id = (
        episode_data.get("subjectId")
        or ep_obj.drama.subject_id
    )

    ep_obj.season = safe_int(
        episode_data.get("se"),
        default=1,
    )

    ep_obj.play_url = play_url
    ep_obj.expires_at = (
        extract_expiry(
            play_url
        )
    )
    ep_obj.thumbnail = (
        cover.get("url")
    )

    ep_obj.duration = safe_int(
        video_address.get("duration"),
        default=0,
    )

    ep_obj.width = safe_int(
        video_address.get("width"),
        default=0,
    )

    ep_obj.height = safe_int(
        video_address.get("height"),
        default=0,
    )

    ep_obj.file_size = safe_int(
        video_address.get("size"),
        default=0,
    )

    ep_obj.lock_status = safe_int(
        episode_data.get("lockStatus"),
        default=0,
    )

    ep_obj.is_active = True

    ep_obj.save(
        update_fields=[
            "mini_id",
            "subject_id",
            "season",
            "play_url",
            "expires_at",
            "thumbnail",
            "duration",
            "width",
            "height",
            "file_size",
            "lock_status",
            "is_active",
        ]
    )

    logger.info(
        "[%s] Updated episode %s | expires=%s",
        ep_obj.drama.title,
        ep_obj.episode_number,
        ep_obj.expires_at,
    )

    return True


def refresh_drama(
    drama,
):
    lock_key = (
        f"drama_refresh:{drama.pk}"
    )

    if not cache.add(
        lock_key,
        "1",
        timeout=LOCK_TIMEOUT,
    ):
        logger.info(
            "[%s] Skipped because it is locked.",
            drama.title,
        )

        return

    try:
        refresh_before = (
            dj_timezone.now()
            + REFRESH_BUFFER
        )

        episodes = list(
            drama.episodes
            .filter(
                is_active=True
            )
            .order_by(
                "episode_number"
            )
        )

        episodes_to_refresh = [
            episode
            for episode in episodes
            if episode_needs_refresh(
                episode,
                refresh_before,
            )
        ]

        if not episodes_to_refresh:
            logger.info(
                "[%s] No URLs need refresh.",
                drama.title,
            )

            return

        logger.info(
            "[%s] Refreshing %s episode URL(s).",
            drama.title,
            len(episodes_to_refresh),
        )

        updated = 0
        failed = []

        for episode in episodes_to_refresh:
            try:
                if refresh_episode(
                    episode
                ):
                    updated += 1
                else:
                    failed.append(
                        episode.episode_number
                    )

            except DramaUnavailableError as exc:
                logger.error(
                    "[%s] Drama unavailable during refresh: %s",
                    drama.title,
                    exc,
                )

                drama.is_active = False
                drama.save(
                    update_fields=[
                        "is_active",
                    ]
                )

                logger.warning(
                    "[%s] Marked inactive and stopped refreshing.",
                    drama.title,
                )

                return

            except Exception:
                logger.exception(
                    "[%s] Failed refreshing episode %s",
                    drama.title,
                    episode.episode_number,
                )

                failed.append(
                    episode.episode_number
                )

            time.sleep(
                DELAY_BETWEEN_EPISODES
            )

        drama.last_episode_refresh = (
            dj_timezone.now()
        )

        drama.save(
            update_fields=[
                "last_episode_refresh",
            ]
        )

        logger.info(
            "[%s] Refresh complete. "
            "Updated=%s failed=%s",
            drama.title,
            updated,
            failed,
        )

    finally:
        cache.delete(
            lock_key
        )

        close_old_connections()


def get_dramas_to_refresh():
    refresh_before = (
        dj_timezone.now()
        + REFRESH_BUFFER
    )

    return list(
        ShortDrama.objects
        .filter(
            is_active=True,
            episodes__is_active=True,
        )
        .filter(
            Q(
                episodes__expires_at__lte=(
                    refresh_before
                )
            )
            | Q(
                episodes__expires_at__isnull=True
            )
            | Q(
                episodes__play_url__isnull=True
            )
            | Q(
                episodes__play_url=""
            )
        )
        .distinct()
        .order_by("id")
    )


def main():
    dramas = (
        get_dramas_to_refresh()
    )

    logger.info(
        "Found %s drama(s) requiring URL refresh.",
        len(dramas),
    )

    for index, drama in enumerate(
        dramas,
        start=1,
    ):
        logger.info(
            "[%s/%s] Refreshing %s",
            index,
            len(dramas),
            drama.title,
        )

        try:
            refresh_drama(
                drama
            )

        except Exception:
            logger.exception(
                "[%s] Unexpected refresh error",
                drama.title,
            )

        finally:
            close_old_connections()

        if index < len(dramas):
            time.sleep(
                DELAY_BETWEEN_DRAMAS
            )


if __name__ == "__main__":
    logger.info(
        "Starting signed URL refresh."
    )

    try:
        main()

    except KeyboardInterrupt:
        logger.info(
            "Refresh stopped by user."
        )

    finally:
        session.close()
        close_old_connections()

        logger.info(
            "Refresh finished."
        )