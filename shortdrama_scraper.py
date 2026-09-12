# import hashlib
# import json
# import logging
# import os
# import random
# import re
# import string
# import time
# from datetime import datetime, timezone
# from urllib.parse import parse_qs, quote, urlparse
#
# import django
# import requests
# from requests.adapters import HTTPAdapter
#
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
# django.setup()
#
# from django.db import close_old_connections
# from django.utils.text import slugify
#
# from api.models import (
#     ShortDrama,
#     ShortDramaCountry,
#     ShortDramaEpisode,
#     ShortDramaGenre,
# )
#
#
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(message)s",
# )
# logger = logging.getLogger(__name__)
#
#
# # --------------------------------------------------
# # REQUEST CONFIG
# # --------------------------------------------------
# REQUEST_TIMEOUT = 30
# RETRY_LIMIT = 3
# RETRY_DELAY = 2
#
# WATCH_BASE_URL = "https://vskit.online/watch"
#
# RECOMMEND_API_URL = (
#     "https://h5-api.aoneroom.com/"
#     "wefeed-h5api-bff/vskit/recommend-list"
# )
#
# GENRE_CACHE = {}
# COUNTRY_CACHE = {}
#
#
# # --------------------------------------------------
# # MAIN SCRAPER CONFIG
# # --------------------------------------------------
# MAX_PAGES = 3
# PER_PAGE = 20
# DELAY_BETWEEN_EPISODES = 0.7
# DELAY_BETWEEN_DRAMAS = 5
# DELAY_BETWEEN_PAGES = 5
#
#
# # --------------------------------------------------
# # AUTH
# # --------------------------------------------------
# def normalize_bearer_token(value):
#     value = (value or "").strip()
#
#     if value.lower().startswith("bearer "):
#         value = value[7:].strip()
#
#     return value
#
#
# BEARER_TOKEN = normalize_bearer_token(
#     os.getenv("VSKIT_BEARER_TOKEN", "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOjQ2Mjg4NjM1NjEzNTAyNDQzNDQsImF0cCI6MywiZXh0IjoiMTc4NjE5OTgyOCIsImV4cCI6MTc5Mzk3NTgyOCwiaWF0IjoxNzg2MTk5NTI4fQ.D3f4vFQwICvmyl8L7Qijv3SPEnZdsn_2xv0F-cwqOl0")
# )
#
# COOKIE_STRING = os.getenv(
#     "VSKIT_COOKIE_STRING",
#     "",
# )
#
#
# # --------------------------------------------------
# # EXCEPTIONS
# # --------------------------------------------------
# class DramaUnavailableError(Exception):
#     """Raised when VSKit returns an empty watch page for a drama."""
#
#
# # --------------------------------------------------
# # HELPERS
# # --------------------------------------------------
# def safe_int(value, default=0):
#     try:
#         return int(value)
#     except (TypeError, ValueError):
#         return default
#
#
# def random_rsc_value(length=8):
#     alphabet = (
#         string.ascii_lowercase
#         + string.digits
#     )
#
#     return "".join(
#         random.choice(alphabet)
#         for _ in range(length)
#     )
#
#
# def extract_expiry(play_url):
#     if not play_url:
#         return None
#
#     try:
#         query = parse_qs(
#             urlparse(play_url).query
#         )
#
#         values = (
#             query.get("Expires")
#             or query.get("expires")
#             or query.get("expire")
#         )
#
#         if not values:
#             return None
#
#         return datetime.fromtimestamp(
#             int(values[0]),
#             tz=timezone.utc,
#         )
#
#     except (
#         TypeError,
#         ValueError,
#         OverflowError,
#         IndexError,
#     ):
#         return None
#
#
# # --------------------------------------------------
# # NEXT.JS ROUTER STATE
# # --------------------------------------------------
# def build_next_router_state_tree(drama_slug):
#     state = [
#         "",
#         {
#             "children": [
#                 ["locale", "en", "d"],
#                 {
#                     "children": [
#                         "watch",
#                         {
#                             "children": [
#                                 [
#                                     "slug",
#                                     drama_slug,
#                                     "d",
#                                 ],
#                                 {
#                                     "children": [
#                                         "__PAGE__",
#                                         {},
#                                         None,
#                                         "refetch",
#                                     ]
#                                 },
#                                 None,
#                                 None,
#                             ]
#                         },
#                         None,
#                         None,
#                     ]
#                 },
#                 None,
#                 None,
#             ]
#         },
#         None,
#         None,
#     ]
#
#     compact_json = json.dumps(
#         state,
#         separators=(",", ":"),
#     )
#
#     return quote(
#         compact_json,
#         safe="",
#     )
#
#
# # --------------------------------------------------
# # SESSION
# # --------------------------------------------------
# def build_session():
#     http_session = requests.Session()
#
#     http_session.headers.update(
#         {
#             "Accept": "*/*",
#             "Accept-Language": "en-US,en;q=0.9",
#             "User-Agent": (
#                 "Mozilla/5.0 "
#                 "(X11; Ubuntu; Linux x86_64; rv:152.0) "
#                 "Gecko/20100101 Firefox/152.0"
#             ),
#             "Origin": "https://vskit.online",
#             "Referer": "https://vskit.online/",
#             "RSC": "1",
#             "Priority": "u=4",
#         }
#     )
#
#     if BEARER_TOKEN:
#         http_session.headers[
#             "Authorization"
#         ] = f"Bearer {BEARER_TOKEN}"
#
#     adapter = HTTPAdapter(
#         pool_connections=10,
#         pool_maxsize=10,
#         max_retries=0,
#     )
#
#     http_session.mount(
#         "https://",
#         adapter,
#     )
#
#     found_token_cookie = False
#
#     cookie_text = (
#         COOKIE_STRING
#         .replace("…", "")
#         .encode("ascii", "ignore")
#         .decode()
#     )
#
#     for item in cookie_text.split(";"):
#         item = item.strip()
#
#         if "=" not in item:
#             continue
#
#         key, value = item.split("=", 1)
#         key = key.strip()
#         value = value.strip()
#
#         if not key:
#             continue
#
#         if key == "token":
#             found_token_cookie = True
#
#         http_session.cookies.set(
#             key,
#             value,
#             domain="vskit.online",
#             path="/",
#         )
#
#     if BEARER_TOKEN and not found_token_cookie:
#         http_session.cookies.set(
#             "token",
#             BEARER_TOKEN,
#             domain="vskit.online",
#             path="/",
#         )
#
#         logger.warning(
#             "No token cookie was found in VSKIT_COOKIE_STRING; "
#             "a token cookie was created from VSKIT_BEARER_TOKEN."
#         )
#
#     logger.info(
#         "Session bearer=%s cookie_string=%s cookie_names=%s",
#         bool(BEARER_TOKEN),
#         bool(COOKIE_STRING.strip()),
#         list(http_session.cookies.keys()),
#     )
#
#     return http_session
#
#
# session = build_session()
#
#
# # --------------------------------------------------
# # RSC PARSING
# # --------------------------------------------------
# def extract_json_object_after_key(
#     raw_text,
#     key,
# ):
#     marker = re.search(
#         rf'"{re.escape(key)}"\s*:\s*',
#         raw_text,
#     )
#
#     if not marker:
#         return None
#
#     start = marker.end()
#
#     while (
#         start < len(raw_text)
#         and raw_text[start].isspace()
#     ):
#         start += 1
#
#     if (
#         start >= len(raw_text)
#         or raw_text[start] != "{"
#     ):
#         return None
#
#     depth = 0
#     in_string = False
#     escaped = False
#
#     for index in range(
#         start,
#         len(raw_text),
#     ):
#         char = raw_text[index]
#
#         if in_string:
#             if escaped:
#                 escaped = False
#             elif char == "\\":
#                 escaped = True
#             elif char == '"':
#                 in_string = False
#
#             continue
#
#         if char == '"':
#             in_string = True
#         elif char == "{":
#             depth += 1
#         elif char == "}":
#             depth -= 1
#
#             if depth == 0:
#                 return raw_text[
#                     start:index + 1
#                 ]
#
#     return None
#
#
# def extract_json_string(
#     raw_text,
#     key,
# ):
#     match = re.search(
#         rf'"{re.escape(key)}"\s*:\s*'
#         r'("(?:\\.|[^"\\])*")',
#         raw_text,
#     )
#
#     if not match:
#         return None
#
#     try:
#         return json.loads(
#             match.group(1)
#         )
#     except json.JSONDecodeError:
#         return None
#
#
# def extract_json_integer(
#     raw_text,
#     key,
# ):
#     match = re.search(
#         rf'"{re.escape(key)}"\s*:\s*(-?\d+)',
#         raw_text,
#     )
#
#     if not match:
#         return None
#
#     return safe_int(
#         match.group(1),
#         default=None,
#     )
#
#
# def extract_json_array(
#     raw_text,
#     key,
# ):
#     marker = re.search(
#         rf'"{re.escape(key)}"\s*:\s*',
#         raw_text,
#     )
#
#     if not marker:
#         return None
#
#     start = marker.end()
#
#     while (
#         start < len(raw_text)
#         and raw_text[start].isspace()
#     ):
#         start += 1
#
#     if (
#         start >= len(raw_text)
#         or raw_text[start] != "["
#     ):
#         return None
#
#     depth = 0
#     in_string = False
#     escaped = False
#
#     for index in range(
#         start,
#         len(raw_text),
#     ):
#         char = raw_text[index]
#
#         if in_string:
#             if escaped:
#                 escaped = False
#             elif char == "\\":
#                 escaped = True
#             elif char == '"':
#                 in_string = False
#
#             continue
#
#         if char == '"':
#             in_string = True
#         elif char == "[":
#             depth += 1
#         elif char == "]":
#             depth -= 1
#
#             if depth == 0:
#                 try:
#                     value = json.loads(
#                         raw_text[
#                             start:index + 1
#                         ]
#                     )
#
#                     return (
#                         value
#                         if isinstance(
#                             value,
#                             list,
#                         )
#                         else None
#                     )
#
#                 except json.JSONDecodeError:
#                     return None
#
#     return None
#
#
# def extract_episode_and_metadata(
#     raw_text,
# ):
#     current_episode_text = (
#         extract_json_object_after_key(
#             raw_text,
#             "currentEpisode",
#         )
#     )
#
#     if not current_episode_text:
#         return None, {}
#
#     try:
#         episode_data = json.loads(
#             current_episode_text
#         )
#
#     except json.JSONDecodeError as exc:
#         logger.warning(
#             "Could not decode currentEpisode: %s",
#             exc,
#         )
#
#         return None, {}
#
#     metadata = {
#         "genre": extract_json_string(
#             raw_text,
#             "genre",
#         ),
#         "countryName": extract_json_string(
#             raw_text,
#             "countryName",
#         ),
#         "releaseDate": extract_json_string(
#             raw_text,
#             "releaseDate",
#         ),
#         "description": extract_json_string(
#             raw_text,
#             "description",
#         ),
#         "dramaTitle": extract_json_string(
#             raw_text,
#             "dramaTitle",
#         ),
#         "subjectSeoKey": extract_json_string(
#             raw_text,
#             "subjectSeoKey",
#         ),
#         "totalEpisode": extract_json_integer(
#             raw_text,
#             "totalEpisode",
#         ),
#         "tags": extract_json_array(
#             raw_text,
#             "tags",
#         ),
#     }
#
#     return (
#         episode_data,
#         {
#             key: value
#             for key, value in metadata.items()
#             if value is not None
#         },
#     )
#
#
# def is_empty_watch_page(
#     raw_text,
#     episode_number,
# ):
#     empty_title = (
#         f"Watch  Episode {episode_number} - VSKit | VSKit"
#         in raw_text
#     )
#
#     empty_description = (
#         f"Stream  episode {episode_number} free in HD on VSKit."
#         in raw_text
#     )
#
#     return (
#         empty_title
#         and empty_description
#         and "currentEpisode" not in raw_text
#     )
#
#
# # --------------------------------------------------
# # FETCH EPISODE
# # --------------------------------------------------
# def fetch_rsc_episode(
#     drama,
#     episode_number,
# ):
#     base_url = (
#         f"{WATCH_BASE_URL}/"
#         f"{drama.slug}"
#     )
#
#     params = {
#         "ep": episode_number,
#         "_rsc": random_rsc_value(),
#     }
#
#     visible_url = (
#         f"{base_url}?ep={episode_number}"
#     )
#
#     headers = {
#         "Accept": "*/*",
#         "Accept-Language": "en-US,en;q=0.9",
#         "Referer": visible_url,
#         "Next-Url": (
#             f"/en/watch/{drama.slug}"
#             f"?ep={episode_number}"
#         ),
#         "Next-Router-State-Tree": (
#             build_next_router_state_tree(
#                 drama.slug
#             )
#         ),
#         "RSC": "1",
#         "Priority": "u=4",
#         "Cache-Control": "no-cache",
#         "Pragma": "no-cache",
#     }
#
#     for attempt in range(
#         1,
#         RETRY_LIMIT + 1,
#     ):
#         try:
#             response = session.get(
#                 base_url,
#                 params=params,
#                 headers=headers,
#                 timeout=REQUEST_TIMEOUT,
#                 allow_redirects=True,
#             )
#
#             content_type = (
#                 response.headers.get(
#                     "Content-Type",
#                     "",
#                 )
#             )
#
#             body_hash = hashlib.sha256(
#                 response.content
#             ).hexdigest()[:16]
#
#             logger.info(
#                 "[%s] Episode %s | attempt=%s | "
#                 "status=%s | content-type=%s | "
#                 "length=%s | sha256=%s | final-url=%s",
#                 drama.title,
#                 episode_number,
#                 attempt,
#                 response.status_code,
#                 content_type,
#                 len(response.content),
#                 body_hash,
#                 response.url,
#             )
#
#             if response.status_code != 200:
#                 logger.warning(
#                     "[%s] Episode %s returned HTTP %s: %s",
#                     drama.title,
#                     episode_number,
#                     response.status_code,
#                     response.text[:500],
#                 )
#
#                 time.sleep(
#                     RETRY_DELAY * attempt
#                 )
#
#                 continue
#
#             episode_data, metadata = (
#                 extract_episode_and_metadata(
#                     response.text
#                 )
#             )
#
#             if episode_data:
#                 returned_episode = safe_int(
#                     episode_data.get("ep"),
#                     default=0,
#                 )
#
#                 if (
#                     returned_episode
#                     != int(episode_number)
#                 ):
#                     logger.warning(
#                         "[%s] Requested episode %s "
#                         "but received episode %s.",
#                         drama.title,
#                         episode_number,
#                         returned_episode,
#                     )
#
#                     time.sleep(
#                         RETRY_DELAY * attempt
#                     )
#
#                     continue
#
#                 return episode_data, metadata
#
#             if is_empty_watch_page(
#                 response.text,
#                 episode_number,
#             ):
#                 raise DramaUnavailableError(
#                     f"VSKit returned an empty watch page "
#                     f"for slug={drama.slug}"
#                 )
#
#             logger.warning(
#                 "[%s] Episode %s not found in RSC response "
#                 "(%s/%s). preview=%r",
#                 drama.title,
#                 episode_number,
#                 attempt,
#                 RETRY_LIMIT,
#                 response.text[:500],
#             )
#
#         except DramaUnavailableError:
#             raise
#
#         except requests.Timeout:
#             logger.warning(
#                 "[%s] Episode %s timed out "
#                 "on attempt %s/%s.",
#                 drama.title,
#                 episode_number,
#                 attempt,
#                 RETRY_LIMIT,
#             )
#
#         except requests.RequestException as exc:
#             logger.warning(
#                 "[%s] Episode %s request error: %s",
#                 drama.title,
#                 episode_number,
#                 exc,
#             )
#
#         time.sleep(
#             RETRY_DELAY * attempt
#         )
#
#     return None, {}
#
#
# # --------------------------------------------------
# # METADATA
# # --------------------------------------------------
# def get_or_create_genre(
#     genre_name,
# ):
#     genre_name = (
#         genre_name or ""
#     ).strip()
#
#     if not genre_name:
#         return None
#
#     cache_key = genre_name.casefold()
#
#     if cache_key in GENRE_CACHE:
#         return GENRE_CACHE[
#             cache_key
#         ]
#
#     genre = (
#         ShortDramaGenre.objects
#         .filter(
#             name__iexact=genre_name,
#         )
#         .first()
#     )
#
#     if genre is None:
#         genre = (
#             ShortDramaGenre.objects
#             .create(
#                 name=genre_name,
#                 slug=slugify(
#                     genre_name
#                 ),
#             )
#         )
#
#     GENRE_CACHE[cache_key] = genre
#
#     return genre
#
#
# def get_or_create_country(
#     country_name,
# ):
#     country_name = (
#         country_name or ""
#     ).strip()
#
#     if not country_name:
#         return None
#
#     cache_key = country_name.casefold()
#
#     if cache_key in COUNTRY_CACHE:
#         return COUNTRY_CACHE[
#             cache_key
#         ]
#
#     country = (
#         ShortDramaCountry.objects
#         .filter(
#             name__iexact=country_name,
#         )
#         .first()
#     )
#
#     if country is None:
#         country = (
#             ShortDramaCountry.objects
#             .create(
#                 name=country_name,
#                 slug=slugify(
#                     country_name
#                 ),
#             )
#         )
#
#     COUNTRY_CACHE[cache_key] = country
#
#     return country
#
#
# def update_drama_metadata(
#     drama,
#     metadata,
# ):
#     if not metadata:
#         return False
#
#     changed = False
#     update_fields = []
#
#     country_name = metadata.get(
#         "countryName"
#     )
#
#     if (
#         drama.country_id is None
#         and country_name
#     ):
#         country = get_or_create_country(
#             country_name
#         )
#
#         if country:
#             drama.country = country
#             update_fields.append(
#                 "country"
#             )
#             changed = True
#
#             logger.info(
#                 "[%s] Added country: %s",
#                 drama.title,
#                 country.name,
#             )
#
#     release_date_value = metadata.get(
#         "releaseDate"
#     )
#
#     if (
#         drama.release_date is None
#         and release_date_value
#     ):
#         try:
#             release_date = (
#                 datetime.strptime(
#                     release_date_value,
#                     "%Y-%m-%d",
#                 )
#                 .date()
#             )
#
#             drama.release_date = (
#                 release_date
#             )
#             update_fields.append(
#                 "release_date"
#             )
#             changed = True
#
#             logger.info(
#                 "[%s] Added release date: %s",
#                 drama.title,
#                 release_date,
#             )
#
#         except ValueError:
#             logger.warning(
#                 "[%s] Invalid release date: %r",
#                 drama.title,
#                 release_date_value,
#             )
#
#     description = metadata.get(
#         "description"
#     )
#
#     if (
#         not drama.description
#         and description
#     ):
#         drama.description = description
#         update_fields.append(
#             "description"
#         )
#         changed = True
#
#     total_episode = safe_int(
#         metadata.get(
#             "totalEpisode"
#         ),
#         default=0,
#     )
#
#     if (
#         total_episode > 0
#         and drama.total_episodes
#         != total_episode
#     ):
#         drama.total_episodes = (
#             total_episode
#         )
#         update_fields.append(
#             "total_episodes"
#         )
#         changed = True
#
#     tags = metadata.get("tags")
#
#     if tags and not drama.tags:
#         drama.tags = tags
#         update_fields.append("tags")
#         changed = True
#
#     if update_fields:
#         drama.save(
#             update_fields=list(
#                 dict.fromkeys(
#                     update_fields
#                 )
#             )
#         )
#
#     if not drama.genres.exists():
#         genre_string = metadata.get(
#             "genre"
#         )
#
#         if genre_string:
#             normalized = (
#                 genre_string
#                 .replace("|", ",")
#                 .replace("/", ",")
#                 .replace(";", ",")
#             )
#
#             genres = []
#
#             for genre_name in (
#                 normalized.split(",")
#             ):
#                 genre = get_or_create_genre(
#                     genre_name
#                 )
#
#                 if genre:
#                     genres.append(genre)
#
#             if genres:
#                 unique_genres = {
#                     genre.pk: genre
#                     for genre in genres
#                 }
#
#                 drama.genres.set(
#                     unique_genres.values()
#                 )
#
#                 changed = True
#
#                 logger.info(
#                     "[%s] Added genres: %s",
#                     drama.title,
#                     ", ".join(
#                         genre.name
#                         for genre
#                         in unique_genres.values()
#                     ),
#                 )
#
#     return changed
#
#
# # --------------------------------------------------
# # SAVE EPISODE
# # --------------------------------------------------
# def save_episode(
#     drama,
#     episode_data,
#     metadata=None,
# ):
#     episode_number = safe_int(
#         episode_data.get("ep"),
#         default=0,
#     )
#
#     if episode_number <= 0:
#         logger.error(
#             "[%s] Invalid episode number: %r",
#             drama.title,
#             episode_data.get("ep"),
#         )
#
#         return False
#
#     if metadata:
#         update_drama_metadata(
#             drama,
#             metadata,
#         )
#
#     video = (
#         episode_data.get("video")
#         or {}
#     )
#
#     video_address = (
#         video.get("videoAddress")
#         or {}
#     )
#
#     cover = (
#         video.get("cover")
#         or {}
#     )
#
#     play_url = (
#         video_address.get("url")
#     )
#
#     _, created = (
#         ShortDramaEpisode.objects
#         .update_or_create(
#             drama=drama,
#             episode_number=episode_number,
#             defaults={
#                 "mini_id": (
#                     episode_data.get(
#                         "miniId"
#                     )
#                 ),
#                 "subject_id": (
#                     episode_data.get(
#                         "subjectId"
#                     )
#                     or drama.subject_id
#                 ),
#                 "season": safe_int(
#                     episode_data.get(
#                         "se"
#                     ),
#                     default=1,
#                 ),
#                 "play_url": play_url,
#                 "expires_at": (
#                     extract_expiry(
#                         play_url
#                     )
#                 ),
#                 "thumbnail": (
#                     cover.get("url")
#                 ),
#                 "duration": safe_int(
#                     video_address.get(
#                         "duration"
#                     ),
#                     default=0,
#                 ),
#                 "width": safe_int(
#                     video_address.get(
#                         "width"
#                     ),
#                     default=0,
#                 ),
#                 "height": safe_int(
#                     video_address.get(
#                         "height"
#                     ),
#                     default=0,
#                 ),
#                 "file_size": safe_int(
#                     video_address.get(
#                         "size"
#                     ),
#                     default=0,
#                 ),
#                 "lock_status": safe_int(
#                     episode_data.get(
#                         "lockStatus"
#                     ),
#                     default=0,
#                 ),
#                 "is_active": True,
#             },
#         )
#     )
#
#     logger.info(
#         "[%s] %s episode %s",
#         drama.title,
#         (
#             "Created"
#             if created
#             else "Updated"
#         ),
#         episode_number,
#     )
#
#     return True
#
#
# # --------------------------------------------------
# # RECOMMENDATION API
# # --------------------------------------------------
# def request_json(
#     url,
#     params=None,
#     description="request",
# ):
#     if not BEARER_TOKEN:
#         raise RuntimeError(
#             "VSKIT_BEARER_TOKEN is required "
#             "for the recommendation API."
#         )
#
#     headers = {
#         "Accept": "application/json",
#         "Authorization": (
#             f"Bearer {BEARER_TOKEN}"
#         ),
#         "Origin": "https://vskit.online",
#         "Referer": "https://vskit.online/",
#         "X-Client-Info": (
#             '{"timezone":"Asia/Karachi"}'
#         ),
#         "X-Request-Lang": "en",
#         "X-Site-Domain": (
#             "https://vskit.online"
#         ),
#     }
#
#     for attempt in range(
#         1,
#         RETRY_LIMIT + 1,
#     ):
#         try:
#             response = session.get(
#                 url,
#                 params=params,
#                 headers=headers,
#                 timeout=REQUEST_TIMEOUT,
#             )
#
#             logger.info(
#                 "%s | attempt=%s | status=%s",
#                 description,
#                 attempt,
#                 response.status_code,
#             )
#
#             if response.status_code == 401:
#                 logger.error(
#                     "Bearer token is missing or expired."
#                 )
#                 return None
#
#             if response.status_code == 429:
#                 retry_after = safe_int(
#                     response.headers.get(
#                         "Retry-After"
#                     ),
#                     RETRY_DELAY * attempt,
#                 )
#
#                 time.sleep(
#                     retry_after
#                 )
#                 continue
#
#             if response.status_code != 200:
#                 logger.warning(
#                     "%s returned HTTP %s: %s",
#                     description,
#                     response.status_code,
#                     response.text[:500],
#                 )
#
#                 time.sleep(
#                     RETRY_DELAY * attempt
#                 )
#                 continue
#
#             try:
#                 payload = response.json()
#
#             except requests.exceptions.JSONDecodeError as exc:
#                 logger.warning(
#                     "%s returned invalid JSON: %s",
#                     description,
#                     exc,
#                 )
#
#                 time.sleep(
#                     RETRY_DELAY * attempt
#                 )
#                 continue
#
#             if payload.get("code") not in (
#                 None,
#                 0,
#             ):
#                 logger.warning(
#                     "%s API error code=%s message=%s",
#                     description,
#                     payload.get("code"),
#                     payload.get("message"),
#                 )
#
#                 time.sleep(
#                     RETRY_DELAY * attempt
#                 )
#                 continue
#
#             return payload
#
#         except requests.RequestException as exc:
#             logger.warning(
#                 "%s failed on attempt %s/%s: %s",
#                 description,
#                 attempt,
#                 RETRY_LIMIT,
#                 exc,
#             )
#
#         time.sleep(
#             RETRY_DELAY * attempt
#         )
#
#     return None
#
#
# def fetch_page(
#     page,
# ):
#     payload = request_json(
#         RECOMMEND_API_URL,
#         params={
#             "page": page,
#             "perPage": PER_PAGE,
#             "novelType": 3,
#         },
#         description=(
#             f"Fetch drama page {page}"
#         ),
#     )
#
#     if not payload:
#         return []
#
#     data = payload.get("data") or {}
#     dramas = data.get("list") or []
#
#     return (
#         dramas
#         if isinstance(dramas, list)
#         else []
#     )
#
#
# # --------------------------------------------------
# # DRAMA SAVE
# # --------------------------------------------------
# def save_drama(
#     drama_data,
# ):
#     subject_id = drama_data.get(
#         "subjectId"
#     )
#
#     slug = drama_data.get(
#         "subjectSeoKey"
#     )
#
#     if not subject_id or not slug:
#         raise ValueError(
#             "Drama is missing subjectId "
#             "or subjectSeoKey."
#         )
#
#     drama, created = (
#         ShortDrama.objects
#         .update_or_create(
#             subject_id=subject_id,
#             defaults={
#                 "title": (
#                     drama_data.get("title")
#                     or ""
#                 ),
#                 "slug": slug,
#                 "cover": (
#                     drama_data.get("cover")
#                     or {}
#                 ),
#                 "tags": (
#                     drama_data.get("tags")
#                     or []
#                 ),
#                 "total_episodes": safe_int(
#                     drama_data.get(
#                         "totalEpisode"
#                     ),
#                     default=0,
#                 ),
#                 "total_views": (
#                     drama_data.get(
#                         "totalViews"
#                     )
#                 ),
#                 "description": (
#                     drama_data.get(
#                         "description"
#                     )
#                     or ""
#                 ),
#                 "is_active": True,
#             },
#         )
#     )
#
#     logger.info(
#         "%s drama: %s | episodes=%s",
#         (
#             "Created"
#             if created
#             else "Updated"
#         ),
#         drama.title,
#         drama.total_episodes,
#     )
#
#     return drama
#
#
# # --------------------------------------------------
# # SCRAPE ONE DRAMA
# # --------------------------------------------------
# def mark_drama_inactive(
#     drama,
#     reason,
# ):
#     if drama.is_active:
#         drama.is_active = False
#         drama.save(
#             update_fields=[
#                 "is_active",
#             ]
#         )
#
#     logger.error(
#         "[%s] Marked inactive: %s",
#         drama.title,
#         reason,
#     )
#
#
# def scrape_drama(
#     drama,
# ):
#     total_episodes = safe_int(
#         drama.total_episodes,
#         default=0,
#     )
#
#     if total_episodes <= 0:
#         logger.warning(
#             "[%s] Invalid total episode count.",
#             drama.title,
#         )
#         return
#
#     existing = set(
#         drama.episodes.values_list(
#             "episode_number",
#             flat=True,
#         )
#     )
#
#     pending = [
#         episode_number
#         for episode_number in range(
#             1,
#             total_episodes + 1,
#         )
#         if episode_number
#         not in existing
#     ]
#
#     if not pending:
#         logger.info(
#             "[%s] All %s episodes already exist.",
#             drama.title,
#             total_episodes,
#         )
#
#         if (
#             drama.country_id is None
#             or drama.release_date is None
#             or not drama.genres.exists()
#         ):
#             try:
#                 episode_data, metadata = (
#                     fetch_rsc_episode(
#                         drama,
#                         1,
#                     )
#                 )
#
#             except DramaUnavailableError as exc:
#                 mark_drama_inactive(
#                     drama,
#                     str(exc),
#                 )
#                 return
#
#             if episode_data and metadata:
#                 update_drama_metadata(
#                     drama,
#                     metadata,
#                 )
#
#         return
#
#     logger.info(
#         "[%s] Existing=%s pending=%s total=%s",
#         drama.title,
#         len(existing),
#         len(pending),
#         total_episodes,
#     )
#
#     failed = []
#
#     for episode_number in pending:
#         try:
#             episode_data, metadata = (
#                 fetch_rsc_episode(
#                     drama,
#                     episode_number,
#                 )
#             )
#
#         except DramaUnavailableError as exc:
#             mark_drama_inactive(
#                 drama,
#                 str(exc),
#             )
#             return
#
#         if not episode_data:
#             failed.append(
#                 episode_number
#             )
#             continue
#
#         try:
#             save_episode(
#                 drama,
#                 episode_data,
#                 metadata,
#             )
#
#         except Exception:
#             logger.exception(
#                 "[%s] Failed saving episode %s",
#                 drama.title,
#                 episode_number,
#             )
#
#             failed.append(
#                 episode_number
#             )
#
#         time.sleep(
#             DELAY_BETWEEN_EPISODES
#         )
#
#     if failed:
#         logger.info(
#             "[%s] Recovery pass for episodes: %s",
#             drama.title,
#             failed,
#         )
#
#         final_failed = []
#
#         for episode_number in failed:
#             try:
#                 episode_data, metadata = (
#                     fetch_rsc_episode(
#                         drama,
#                         episode_number,
#                     )
#                 )
#
#             except DramaUnavailableError as exc:
#                 mark_drama_inactive(
#                     drama,
#                     str(exc),
#                 )
#                 return
#
#             if not episode_data:
#                 final_failed.append(
#                     episode_number
#                 )
#                 continue
#
#             try:
#                 save_episode(
#                     drama,
#                     episode_data,
#                     metadata,
#                 )
#
#             except Exception:
#                 logger.exception(
#                     "[%s] Recovery save failed "
#                     "for episode %s",
#                     drama.title,
#                     episode_number,
#                 )
#
#                 final_failed.append(
#                     episode_number
#                 )
#
#             time.sleep(
#                 DELAY_BETWEEN_EPISODES
#             )
#
#         if final_failed:
#             logger.error(
#                 "[%s] Final failed episodes: %s",
#                 drama.title,
#                 final_failed,
#             )
#
#     final_count = (
#         drama.episodes
#         .filter(
#             episode_number__gte=1,
#             episode_number__lte=(
#                 total_episodes
#             ),
#         )
#         .count()
#     )
#
#     logger.info(
#         "[%s] Stored %s/%s episodes.",
#         drama.title,
#         final_count,
#         total_episodes,
#     )
#
#
# # --------------------------------------------------
# # SCRAPE ALL
# # --------------------------------------------------
# def scrape_all():
#     seen_subject_ids = set()
#
#     for page in range(
#         1,
#         MAX_PAGES + 1,
#     ):
#         dramas = fetch_page(
#             page
#         )
#
#         if not dramas:
#             logger.info(
#                 "No dramas returned for page %s.",
#                 page,
#             )
#             break
#
#         for drama_data in dramas:
#             subject_id = drama_data.get(
#                 "subjectId"
#             )
#
#             if (
#                 not subject_id
#                 or subject_id
#                 in seen_subject_ids
#             ):
#                 continue
#
#             seen_subject_ids.add(
#                 subject_id
#             )
#
#             try:
#                 drama = save_drama(
#                     drama_data
#                 )
#
#                 scrape_drama(
#                     drama
#                 )
#
#             except Exception:
#                 logger.exception(
#                     "Failed processing drama %r",
#                     (
#                         drama_data.get("title")
#                         or subject_id
#                     ),
#                 )
#
#             finally:
#                 close_old_connections()
#
#             time.sleep(
#                 DELAY_BETWEEN_DRAMAS
#             )
#
#         if page < MAX_PAGES:
#             time.sleep(
#                 DELAY_BETWEEN_PAGES
#             )
#
#
# if __name__ == "__main__":
#     logger.info(
#         "Starting VSKit short-drama scraper."
#     )
#
#     try:
#         scrape_all()
#
#     except KeyboardInterrupt:
#         logger.info(
#             "Scraper stopped by user."
#         )
#
#     finally:
#         session.close()
#         close_old_connections()
#
#         logger.info(
#             "Scraper finished."
#         )

import hashlib
import json
import logging
import os
import random
import re
import string
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

import django
import requests
from requests.adapters import HTTPAdapter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
django.setup()

from django.db import close_old_connections
from django.db.models import Q
from django.utils.text import slugify

from api.models import (
    ShortDrama,
    ShortDramaCountry,
    ShortDramaEpisode,
    ShortDramaGenre,
)


# ==================================================
# LOGGING
# ==================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ==================================================
# CONFIG
# ==================================================
REQUEST_TIMEOUT = int(os.getenv("VSKIT_REQUEST_TIMEOUT", "30"))
RETRY_LIMIT = int(os.getenv("VSKIT_RETRY_LIMIT", "3"))
RETRY_DELAY = float(os.getenv("VSKIT_RETRY_DELAY", "2"))

# 0 means: follow pager.hasMore until the API says there are no more pages.
MAX_PAGES = int(os.getenv("VSKIT_MAX_PAGES", "0"))
PER_PAGE = int(os.getenv("VSKIT_PER_PAGE", "18"))
CHANNEL_ID = os.getenv("VSKIT_CHANNEL_ID", "1220")
SUBJECT_SORT = os.getenv("VSKIT_SUBJECT_SORT", "ForYou")
START_PAGE = int(os.getenv("VSKIT_START_PAGE", "1"))

DELAY_BETWEEN_EPISODES = float(
    os.getenv("VSKIT_DELAY_BETWEEN_EPISODES", "0.7")
)
DELAY_BETWEEN_DRAMAS = float(
    os.getenv("VSKIT_DELAY_BETWEEN_DRAMAS", "2")
)
DELAY_BETWEEN_PAGES = float(
    os.getenv("VSKIT_DELAY_BETWEEN_PAGES", "2")
)

CLIENT_TIMEZONE = os.getenv(
    "VSKIT_CLIENT_TIMEZONE",
    "Asia/Karachi",
)

# Refresh country/genre/releaseDate from the watch payload even when the
# database already has values. This fixes stale/default metadata.
REFRESH_METADATA_ALWAYS = env_bool("VSKIT_REFRESH_METADATA", True)

# Optional raw Cookie header copied from your own logged-in browser request.
# Usually the bearer token is enough; only set this if DevTools shows Cookie.
COOKIE_STRING = os.getenv("VSKIT_COOKIE_STRING", "").strip()

# Mirror the browser profile captured from VSKit DevTools.
USER_AGENT = os.getenv(
    "VSKIT_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
)

API_BASE = "https://h5-api.aoneroom.com/wefeed-h5api-bff/vskit"
SUBJECT_LIST_API_URL = f"{API_BASE}/subject/list"
MINI_LIST_API_URL = f"{API_BASE}/shorts/mini-list"
WATCH_BASE_URL = "https://vskit.online/watch"

# Safety guard in case an API accidentally reports hasMore forever.
ABSOLUTE_PAGE_LIMIT = int(os.getenv("VSKIT_ABSOLUTE_PAGE_LIMIT", "1000"))


# ==================================================
# AUTH
# ==================================================
def normalize_bearer_token(value):
    value = (value or "").strip()

    if value.lower().startswith("bearer "):
        value = value[7:].strip()

    return value


# Premium bearer captured from the user's own authenticated VSKit session.
# Environment variable still overrides this value when VSKIT_BEARER_TOKEN is set.
HARDCODED_BEARER_TOKEN = (
    "Bearer "
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1aWQiOjgzNTkxNzY2MDkzNjYxNzExNTIsInV0cCI6MSwiZXhwIjoxNzk2OTg2MTQ4LCJpYXQiOjE3ODkyMDk4NDh9."
    "6hNJ_w5DwcsHobS3N7-MDhGplU0PIDqdpcZ6q4N51ZQ"
)

BEARER_TOKEN = normalize_bearer_token(
    os.getenv("VSKIT_BEARER_TOKEN", HARDCODED_BEARER_TOKEN)
)

if not BEARER_TOKEN:
    raise RuntimeError(
        "No VSKit bearer token is configured."
    )


# ==================================================
# SESSION
# ==================================================
def build_session():
    http_session = requests.Session()

    http_session.headers.update(
        {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "User-Agent": USER_AGENT,
            "Origin": "https://vskit.online",
            "Referer": "https://vskit.online/",
            "Priority": "u=1, i",
            "Sec-CH-UA": '"Chromium";v="152", "Not_A Brand";v="99", "Google Chrome";v="152"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Linux"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "X-Client-Info": json.dumps(
                {"timezone": CLIENT_TIMEZONE},
                separators=(",", ":"),
            ),
            "X-Request-Lang": "en",
            "X-Site-Domain": "https://vskit.online",
            "X-Site-Type": "VskitWeb",
            # Keep this exactly as the browser request sends it.
            "X-Vip-Restrict": "1",
        }
    )

    if COOKIE_STRING:
        # Use only cookies from your own authenticated VSKit browser session.
        http_session.headers["Cookie"] = COOKIE_STRING

    adapter = HTTPAdapter(
        pool_connections=10,
        pool_maxsize=10,
        max_retries=0,
    )
    http_session.mount("https://", adapter)

    return http_session


session = build_session()

TOKEN_FINGERPRINT = hashlib.sha256(
    BEARER_TOKEN.encode("utf-8")
).hexdigest()[:12]

logger.info(
    "VSKit session initialized | bearer=%s token_fp=%s cookie=%s | "
    "timezone=%s refresh_metadata=%s",
    bool(BEARER_TOKEN),
    TOKEN_FINGERPRINT,
    bool(COOKIE_STRING),
    CLIENT_TIMEZONE,
    REFRESH_METADATA_ALWAYS,
)


# ==================================================
# BASIC HELPERS
# ==================================================
def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_expiry(play_url):
    if not play_url:
        return None

    try:
        query = parse_qs(urlparse(play_url).query)
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


def random_rsc_value(length=12):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def request_json(
    url,
    *,
    method="GET",
    params=None,
    json_body=None,
    description="request",
):
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            if method.upper() == "POST":
                response = session.post(
                    url,
                    params=params,
                    json=json_body,
                    timeout=REQUEST_TIMEOUT,
                )
            else:
                response = session.get(
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

            if response.status_code in (401, 403):
                logger.error(
                    "%s authentication/authorization failed (HTTP %s). "
                    "Refresh VSKIT_BEARER_TOKEN from the logged-in Premium session.",
                    description,
                    response.status_code,
                )
                return None

            if response.status_code == 429:
                retry_after = safe_int(
                    response.headers.get("Retry-After"),
                    int(RETRY_DELAY * attempt),
                )
                logger.warning(
                    "%s rate limited; sleeping %ss.",
                    description,
                    retry_after,
                )
                time.sleep(max(retry_after, 1))
                continue

            if response.status_code != 200:
                logger.warning(
                    "%s returned HTTP %s: %s",
                    description,
                    response.status_code,
                    response.text[:300],
                )
                time.sleep(RETRY_DELAY * attempt)
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                logger.warning(
                    "%s returned invalid JSON: %s",
                    description,
                    exc,
                )
                time.sleep(RETRY_DELAY * attempt)
                continue

            if payload.get("code") not in (None, 0):
                logger.warning(
                    "%s API error code=%s message=%s",
                    description,
                    payload.get("code"),
                    payload.get("message"),
                )
                time.sleep(RETRY_DELAY * attempt)
                continue

            return payload

        except requests.Timeout:
            logger.warning(
                "%s timed out on attempt %s/%s.",
                description,
                attempt,
                RETRY_LIMIT,
            )

        except requests.RequestException as exc:
            logger.warning(
                "%s request failed on attempt %s/%s: %s",
                description,
                attempt,
                RETRY_LIMIT,
                exc,
            )

        time.sleep(RETRY_DELAY * attempt)

    return None


def request_text(url, *, params=None, headers=None, description="request"):
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            logger.info(
                "%s | attempt=%s | status=%s | content-type=%s | length=%s",
                description,
                attempt,
                response.status_code,
                response.headers.get("Content-Type", ""),
                len(response.content),
            )

            if response.status_code == 200:
                return response.text

            if response.status_code == 429:
                retry_after = safe_int(
                    response.headers.get("Retry-After"),
                    int(RETRY_DELAY * attempt),
                )
                time.sleep(max(retry_after, 1))
                continue

            logger.warning(
                "%s returned HTTP %s: %s",
                description,
                response.status_code,
                response.text[:300],
            )

        except requests.RequestException as exc:
            logger.warning(
                "%s failed on attempt %s/%s: %s",
                description,
                attempt,
                RETRY_LIMIT,
                exc,
            )

        time.sleep(RETRY_DELAY * attempt)

    return None


def choose_video_address(episode_data):
    video = episode_data.get("video") or {}
    primary = video.get("videoAddress") or {}

    if isinstance(primary, dict) and primary.get("url"):
        return primary

    address_list = video.get("addressList") or []
    if isinstance(address_list, list):
        for address in address_list:
            if isinstance(address, dict) and address.get("url"):
                return address

    return primary if isinstance(primary, dict) else {}


# ==================================================
# RAW PAGE METADATA PARSING
# ==================================================
def extract_json_string(raw_text, key):
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*'
        r'("(?:\\.|[^"\\])*")',
        raw_text,
    )

    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def extract_json_integer(raw_text, key):
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*(-?\d+)',
        raw_text,
    )
    return safe_int(match.group(1), None) if match else None


def extract_json_array(raw_text, key):
    marker = re.search(
        rf'"{re.escape(key)}"\s*:\s*',
        raw_text,
    )
    if not marker:
        return None

    start = marker.end()
    while start < len(raw_text) and raw_text[start].isspace():
        start += 1

    if start >= len(raw_text) or raw_text[start] != "[":
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(raw_text)):
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
                    value = json.loads(raw_text[start:index + 1])
                    return value if isinstance(value, list) else None
                except json.JSONDecodeError:
                    return None

    return None


def extract_metadata_from_text(raw_text):
    if not raw_text:
        return {}

    metadata = {
        "genre": extract_json_string(raw_text, "genre"),
        "countryName": extract_json_string(raw_text, "countryName"),
        "releaseDate": extract_json_string(raw_text, "releaseDate"),
        "description": extract_json_string(raw_text, "description"),
        "dramaTitle": extract_json_string(raw_text, "dramaTitle"),
        "subjectSeoKey": extract_json_string(raw_text, "subjectSeoKey"),
        "totalEpisode": extract_json_integer(raw_text, "totalEpisode"),
        "tags": extract_json_array(raw_text, "tags"),
    }

    return {
        key: value
        for key, value in metadata.items()
        if value is not None
    }


def build_next_router_state_tree(drama_slug, episode_number=1):
    page_segment = "__PAGE__?" + json.dumps(
        {"ep": str(episode_number)},
        separators=(",", ":"),
    )

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
                                ["slug", drama_slug, "d"],
                                {
                                    "children": [
                                        page_segment,
                                        {},
                                    ]
                                },
                            ]
                        },
                    ]
                },
            ]
        },
    ]

    return quote(
        json.dumps(state, separators=(",", ":")),
        safe="",
    )


def fetch_drama_metadata(drama):
    """
    subject/list does not include countryName / genre / releaseDate.
    Enrich each drama from the VSKit watch page. The parser searches the
    raw Next.js payload for metadata only; episode media still comes from
    the JSON mini-list API.
    """
    url = f"{WATCH_BASE_URL}/{drama.slug}"

    html_headers = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Referer": "https://vskit.online/",
    }

    raw_text = request_text(
        url,
        params={"ep": 1},
        headers=html_headers,
        description=f"[{drama.title}] Metadata HTML",
    )

    metadata = extract_metadata_from_text(raw_text or "")

    # A normal HTML response can occasionally omit some Flight data.
    # Retry with the RSC route only when the important metadata is absent.
    needs_rsc = not (
        metadata.get("countryName")
        and metadata.get("releaseDate")
        and metadata.get("genre")
    )

    if needs_rsc:
        visible_url = f"{url}?ep=1"
        rsc_headers = {
            "Accept": "*/*",
            "Referer": visible_url,
            "Next-Url": f"/en/watch/{drama.slug}?ep=1",
            "Next-Router-State-Tree": build_next_router_state_tree(
                drama.slug,
                1,
            ),
            "RSC": "1",
            "Priority": "u=4",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        rsc_text = request_text(
            url,
            params={
                "ep": 1,
                "_rsc": random_rsc_value(),
            },
            headers=rsc_headers,
            description=f"[{drama.title}] Metadata RSC",
        )

        rsc_metadata = extract_metadata_from_text(rsc_text or "")

        for key, value in rsc_metadata.items():
            if metadata.get(key) in (None, "", []):
                metadata[key] = value

    logger.info(
        "[%s] Metadata resolved | country=%r genre=%r releaseDate=%r",
        drama.title,
        metadata.get("countryName"),
        metadata.get("genre"),
        metadata.get("releaseDate"),
    )

    return metadata


# ==================================================
# GENRE / COUNTRY
# ==================================================
GENRE_CACHE = {}
COUNTRY_CACHE = {}


def get_or_create_genre(genre_name):
    genre_name = (genre_name or "").strip()
    if not genre_name:
        return None

    cache_key = genre_name.casefold()
    if cache_key in GENRE_CACHE:
        return GENRE_CACHE[cache_key]

    genre = (
        ShortDramaGenre.objects
        .filter(name__iexact=genre_name)
        .first()
    )

    if genre is None:
        base_slug = slugify(genre_name) or "genre"
        slug = base_slug
        suffix = 2

        while ShortDramaGenre.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        genre = ShortDramaGenre.objects.create(
            name=genre_name,
            slug=slug,
        )

    GENRE_CACHE[cache_key] = genre
    return genre


def get_or_create_country(country_name):
    country_name = (country_name or "").strip()
    if not country_name:
        return None

    cache_key = country_name.casefold()
    if cache_key in COUNTRY_CACHE:
        return COUNTRY_CACHE[cache_key]

    country = (
        ShortDramaCountry.objects
        .filter(name__iexact=country_name)
        .first()
    )

    if country is None:
        base_slug = slugify(country_name) or "country"
        slug = base_slug
        suffix = 2

        while ShortDramaCountry.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        country = ShortDramaCountry.objects.create(
            name=country_name,
            slug=slug,
        )

    COUNTRY_CACHE[cache_key] = country
    return country


def parse_release_date(value):
    if not value:
        return None

    text = str(value).strip()
    candidates = [text]
    if "T" in text:
        candidates.append(text.split("T", 1)[0])
    if " " in text:
        candidates.append(text.split(" ", 1)[0])

    for candidate in candidates:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass

    return None


def update_drama_metadata(drama, source):
    if not source:
        return False

    changed = False
    update_fields = []

    country_name = (source.get("countryName") or "").strip()
    if country_name:
        country = get_or_create_country(country_name)
        if country is not None and drama.country_id != country.pk:
            drama.country = country
            update_fields.append("country")
            changed = True

    release_date_value = source.get("releaseDate")
    if release_date_value:
        release_date = parse_release_date(release_date_value)
        if release_date is None:
            logger.warning(
                "[%s] Invalid release date: %r",
                drama.title,
                release_date_value,
            )
        elif drama.release_date != release_date:
            drama.release_date = release_date
            update_fields.append("release_date")
            changed = True

    description = source.get("description")
    if description and drama.description != description:
        drama.description = description
        update_fields.append("description")
        changed = True

    tags = source.get("tags")
    if tags and drama.tags != tags:
        drama.tags = tags
        update_fields.append("tags")
        changed = True

    total_episode = safe_int(source.get("totalEpisode"), 0)
    if total_episode > 0 and drama.total_episodes != total_episode:
        drama.total_episodes = total_episode
        update_fields.append("total_episodes")
        changed = True

    if update_fields:
        drama.save(
            update_fields=list(dict.fromkeys(update_fields))
        )

    genre_value = source.get("genre")
    if genre_value:
        if isinstance(genre_value, list):
            genre_names = [str(item) for item in genre_value]
        else:
            normalized = (
                str(genre_value)
                .replace("|", ",")
                .replace("/", ",")
                .replace(";", ",")
            )
            genre_names = normalized.split(",")

        genres = []
        for genre_name in genre_names:
            genre = get_or_create_genre(genre_name)
            if genre is not None:
                genres.append(genre)

        if genres:
            unique = {obj.pk: obj for obj in genres}
            new_ids = set(unique)
            old_ids = set(
                drama.genres.values_list("pk", flat=True)
            )

            if old_ids != new_ids:
                drama.genres.set(unique.values())
                changed = True

    return changed


def drama_needs_metadata(drama):
    return (
        drama.country_id is None
        or drama.release_date is None
        or not drama.genres.exists()
    )


# ==================================================
# SUBJECT LIST DISCOVERY API
# ==================================================
def fetch_subject_page(page):
    payload = request_json(
        SUBJECT_LIST_API_URL,
        method="POST",
        json_body={
            "channelId": CHANNEL_ID,
            "page": page,
            "perPage": PER_PAGE,
            "classify": "",
            "country": "",
            "dub": "",
            "dub_type": "",
            "tag": "",
            "sort": SUBJECT_SORT,
        },
        description=f"Fetch subject/list page {page}",
    )

    if not payload:
        return [], {}

    data = payload.get("data") or {}
    items = data.get("items") or []
    pager = data.get("pager") or {}

    if not isinstance(items, list):
        items = []

    return items, pager


# ==================================================
# MINI-LIST EPISODE API
# ==================================================
def fetch_episode(drama, episode_number):
    payload = request_json(
        MINI_LIST_API_URL,
        params={
            "subjectSeoKey": drama.slug,
            "pagerMode": 1,
            "startPosition": episode_number,
            "endPosition": episode_number,
        },
        description=(
            f"[{drama.title}] Episode {episode_number} mini-list"
        ),
    )

    if not payload:
        return None, None

    data = payload.get("data") or {}
    items = data.get("items") or []
    access_strategy = data.get("accessStrategy") or {}

    if not isinstance(items, list):
        items = []

    episode_data = None
    for item in items:
        if not isinstance(item, dict):
            continue

        if safe_int(item.get("ep"), 0) == int(episode_number):
            episode_data = item
            break

    if episode_data is None:
        logger.warning(
            "[%s] Episode %s was not returned by mini-list.",
            drama.title,
            episode_number,
        )
        return None, access_strategy

    video = episode_data.get("video") or {}
    primary_address = video.get("videoAddress") or {}
    selected_address = choose_video_address(episode_data)
    play_url = selected_address.get("url") if selected_address else None

    episode_vip = bool(episode_data.get("vipLocked"))
    address_vip = bool(
        primary_address.get("vipLocked")
        if isinstance(primary_address, dict)
        else False
    )

    logger.info(
        "[%s] Episode %s resolved | miniId=%s | "
        "lockStatus=%s vipLocked=%s addressVip=%s playUrl=%s | "
        "freeEpisodeCount=%s requiredVipLevel=%s",
        drama.title,
        episode_number,
        episode_data.get("miniId"),
        safe_int(episode_data.get("lockStatus"), 0),
        episode_vip,
        address_vip,
        bool(play_url),
        access_strategy.get("freeEpisodeCount"),
        access_strategy.get("requiredVipLevel"),
    )

    if not play_url:
        logger.warning(
            "[%s] Episode %s has no media URL | vipLocked=%s addressVip=%s | "
            "token_fp=%s cookie=%s.",
            drama.title,
            episode_number,
            episode_vip,
            address_vip,
            TOKEN_FINGERPRINT,
            bool(COOKIE_STRING),
        )

        if episode_vip or address_vip:
            logger.error(
                "[%s] Premium access is NOT being recognized by mini-list for "
                "episode %s. If this exact episode plays in your browser, "
                "capture that browser mini-list request AFTER the purchase and "
                "compare its Authorization token/cookies with this run. Do not "
                "change X-Vip-Restrict; the browser sends 1.",
                drama.title,
                episode_number,
            )

        return None, access_strategy

    normalized = dict(episode_data)
    normalized_video = dict(video)
    normalized_video["videoAddress"] = selected_address
    normalized["video"] = normalized_video

    return normalized, access_strategy


# ==================================================
# SAVE DRAMA
# ==================================================
def save_drama(drama_data):
    subject_id = drama_data.get("subjectId")
    slug = drama_data.get("subjectSeoKey")

    if not subject_id or not slug:
        raise ValueError(
            "Drama is missing subjectId or subjectSeoKey."
        )

    drama, created = ShortDrama.objects.update_or_create(
        subject_id=subject_id,
        defaults={
            "title": drama_data.get("title") or "",
            "slug": slug,
            "cover": drama_data.get("cover") or {},
            "tags": drama_data.get("tags") or [],
            "total_episodes": safe_int(
                drama_data.get("totalEpisode"),
                0,
            ),
            "total_views": drama_data.get("totalViews"),
            "description": drama_data.get("description") or "",
            "is_active": True,
        },
    )

    # subject/list gives the base fields above. It usually does not include
    # countryName / genre / releaseDate, so those are enriched separately.
    update_drama_metadata(drama, drama_data)

    if REFRESH_METADATA_ALWAYS or drama_needs_metadata(drama):
        metadata = fetch_drama_metadata(drama)
        if metadata:
            update_drama_metadata(drama, metadata)

    # Reload relation-backed fields so the log reflects the committed DB state.
    drama.refresh_from_db()

    logger.info(
        "%s drama: %s | episodes=%s | country=%s | genres=%s | release=%s",
        "Created" if created else "Updated",
        drama.title,
        drama.total_episodes,
        drama.country.name if drama.country_id else None,
        list(drama.genres.values_list("name", flat=True)),
        drama.release_date,
    )

    return drama


# ==================================================
# SAVE EPISODE
# ==================================================
def save_episode(drama, episode_data):
    episode_number = safe_int(episode_data.get("ep"), 0)

    if episode_number <= 0:
        logger.error(
            "[%s] Invalid episode number: %r",
            drama.title,
            episode_data.get("ep"),
        )
        return False

    video = episode_data.get("video") or {}
    video_address = choose_video_address(episode_data)
    cover = video.get("cover") or {}
    play_url = video_address.get("url")

    if not play_url:
        logger.warning(
            "[%s] Episode %s not saved because no play URL was returned.",
            drama.title,
            episode_number,
        )
        return False

    _, created = ShortDramaEpisode.objects.update_or_create(
        drama=drama,
        episode_number=episode_number,
        defaults={
            "mini_id": episode_data.get("miniId"),
            "subject_id": (
                episode_data.get("subjectId")
                or drama.subject_id
            ),
            "season": safe_int(episode_data.get("se"), 1),
            "play_url": play_url,
            "expires_at": extract_expiry(play_url),
            "thumbnail": cover.get("url"),
            "duration": safe_int(video_address.get("duration"), 0),
            "width": safe_int(video_address.get("width"), 0),
            "height": safe_int(video_address.get("height"), 0),
            "file_size": safe_int(video_address.get("size"), 0),
            "lock_status": safe_int(
                episode_data.get("lockStatus"),
                0,
            ),
            "is_active": True,
        },
    )

    logger.info(
        "[%s] %s episode %s | miniId=%s | expires=%s",
        drama.title,
        "Created" if created else "Updated",
        episode_number,
        episode_data.get("miniId"),
        extract_expiry(play_url),
    )

    return True


# ==================================================
# SCRAPE ONE DRAMA
# ==================================================
def scrape_drama(drama):
    total_episodes = safe_int(drama.total_episodes, 0)

    if total_episodes <= 0:
        logger.warning(
            "[%s] Invalid total episode count.",
            drama.title,
        )
        return

    existing_numbers = set(
        drama.episodes.values_list(
            "episode_number",
            flat=True,
        )
    )

    no_url_numbers = set(
        drama.episodes.filter(
            Q(play_url__isnull=True) | Q(play_url="")
        ).values_list(
            "episode_number",
            flat=True,
        )
    )

    pending = [
        episode_number
        for episode_number in range(1, total_episodes + 1)
        if (
            episode_number not in existing_numbers
            or episode_number in no_url_numbers
        )
    ]

    if not pending:
        logger.info(
            "[%s] All %s episodes already exist with media URLs.",
            drama.title,
            total_episodes,
        )
        return

    logger.info(
        "[%s] Existing=%s missing/no-url=%s pending=%s total=%s",
        drama.title,
        len(existing_numbers),
        len(no_url_numbers),
        len(pending),
        total_episodes,
    )

    failed = []

    for episode_number in pending:
        episode_data, _access_strategy = fetch_episode(
            drama,
            episode_number,
        )

        if not episode_data:
            failed.append(episode_number)
            time.sleep(DELAY_BETWEEN_EPISODES)
            continue

        try:
            if not save_episode(drama, episode_data):
                failed.append(episode_number)
        except Exception:
            logger.exception(
                "[%s] Failed saving episode %s",
                drama.title,
                episode_number,
            )
            failed.append(episode_number)

        time.sleep(DELAY_BETWEEN_EPISODES)

    if failed:
        logger.info(
            "[%s] Recovery pass for %s episode(s): %s",
            drama.title,
            len(failed),
            failed,
        )

        final_failed = []

        for episode_number in failed:
            episode_data, _access_strategy = fetch_episode(
                drama,
                episode_number,
            )

            if not episode_data:
                final_failed.append(episode_number)
                time.sleep(DELAY_BETWEEN_EPISODES)
                continue

            try:
                if not save_episode(drama, episode_data):
                    final_failed.append(episode_number)
            except Exception:
                logger.exception(
                    "[%s] Recovery save failed for episode %s",
                    drama.title,
                    episode_number,
                )
                final_failed.append(episode_number)

            time.sleep(DELAY_BETWEEN_EPISODES)

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
            episode_number__lte=total_episodes,
        )
        .exclude(
            Q(play_url__isnull=True) | Q(play_url="")
        )
        .count()
    )

    logger.info(
        "[%s] Stored playable episodes %s/%s.",
        drama.title,
        final_count,
        total_episodes,
    )


# ==================================================
# SCRAPE ALL SUBJECT/LIST PAGES
# ==================================================
def scrape_all():
    seen_subject_ids = set()
    page = START_PAGE
    pages_processed = 0

    while True:
        if pages_processed >= ABSOLUTE_PAGE_LIMIT:
            logger.error(
                "Stopped at absolute page safety limit=%s.",
                ABSOLUTE_PAGE_LIMIT,
            )
            break

        if MAX_PAGES > 0 and pages_processed >= MAX_PAGES:
            logger.info(
                "Reached configured VSKIT_MAX_PAGES=%s.",
                MAX_PAGES,
            )
            break

        dramas, pager = fetch_subject_page(page)

        if not dramas:
            logger.info(
                "No dramas returned for subject/list page %s.",
                page,
            )
            break

        logger.info(
            "subject/list page=%s items=%s hasMore=%s nextPage=%s",
            page,
            len(dramas),
            pager.get("hasMore"),
            pager.get("nextPage"),
        )

        for drama_data in dramas:
            subject_id = drama_data.get("subjectId")

            if not subject_id or subject_id in seen_subject_ids:
                continue

            seen_subject_ids.add(subject_id)

            try:
                drama = save_drama(drama_data)
                scrape_drama(drama)

            except Exception:
                logger.exception(
                    "Failed processing drama %r",
                    drama_data.get("title") or subject_id,
                )

            finally:
                close_old_connections()

            time.sleep(DELAY_BETWEEN_DRAMAS)

        pages_processed += 1

        has_more = bool(pager.get("hasMore"))
        if not has_more:
            logger.info("subject/list reports hasMore=false.")
            break

        next_page = safe_int(pager.get("nextPage"), page + 1)
        if next_page <= page:
            next_page = page + 1

        page = next_page
        time.sleep(DELAY_BETWEEN_PAGES)


# ==================================================
# RUN
# ==================================================
if __name__ == "__main__":
    logger.info(
        "Starting VSKit scraper | discovery=subject/list | "
        "metadata=watch page | episodes=shorts/mini-list"
    )

    try:
        scrape_all()

    except KeyboardInterrupt:
        logger.info("Scraper stopped by user.")

    finally:
        session.close()
        close_old_connections()
        logger.info("Scraper finished.")