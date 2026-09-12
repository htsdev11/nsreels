# import argparse
# import logging
# import os
# import sys
# import requests
# import django
#
# # Setup Django environment
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
# django.setup()
#
# from django.db import close_old_connections
# from django.db.models import Q
# from api.models import ShortDrama
# from shortdrama_scraper import (
#     BEARER_TOKEN,
#     save_drama,
#     scrape_drama,
#     safe_int,
# )
#
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(message)s",
# )
# logger = logging.getLogger("search_and_scrape")
#
# SEARCH_API_URL = "https://h5-api.aoneroom.com/wefeed-h5api-bff/vskit/search"
#
# HEADERS = {
#     "Accept": "application/json",
#     "Authorization": f"Bearer {BEARER_TOKEN}",
#     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
#     "Origin": "https://vskit.online",
#     "Referer": "https://vskit.online/",
#     "X-Client-Info": '{"timezone":"Asia/Karachi"}',
#     "X-Request-Lang": "en",
#     "X-Site-Domain": "https://vskit.online",
# }
#
#
# def search_vskit_dramas(keyword, page=1, per_page=10):
#     """
#     Queries the external VSKit H5 search API for a given keyword.
#     """
#     params = {
#         "keyword": keyword,
#         "page": page,
#         "perPage": per_page,
#     }
#
#     try:
#         response = requests.get(
#             SEARCH_API_URL,
#             headers=HEADERS,
#             params=params,
#             timeout=15,
#         )
#         response.raise_for_status()
#
#         data = response.json()
#         if data.get("code") == 0:
#             drama_list = data.get("data", {}).get("list", [])
#             logger.info("VSKit API returned %d search results for '%s'", len(drama_list), keyword)
#             return drama_list
#         else:
#             logger.warning("VSKit search API returned code %s: %s", data.get("code"), data.get("message"))
#             return []
#     except Exception as exc:
#         logger.error("Error calling VSKit search API for keyword '%s': %s", keyword, exc)
#         return []
#
#
# def get_or_scrape_drama_by_title(title, max_scrape=1, force_scrape=False):
#     """
#     Searches for drama by title in the local database.
#     If available in database (and not force_scrape), returns (queryset, 'database').
#     Otherwise, queries VSKit search API, scrapes metadata and episodes, saves to DB,
#     and returns (queryset, 'scraped').
#     """
#     if not title or not title.strip():
#         return ShortDrama.objects.none(), "invalid_input"
#
#     clean_title = title.strip()
#
#     # Step 1: Check Database
#     if not force_scrape:
#         existing_dramas = ShortDrama.objects.filter(
#             title__icontains=clean_title,
#             is_active=True,
#         ).prefetch_related("episodes").order_by("title")
#
#         if existing_dramas.exists():
#             logger.info("Found %d matching drama(s) in local database for title: '%s'", existing_dramas.count(), clean_title)
#             return existing_dramas, "database"
#
#     # Step 2: Query VSKit Search API
#     logger.info("Drama '%s' not found in database (or force_scrape=True). Searching VSKit API...", clean_title)
#     vskit_results = search_vskit_dramas(clean_title)
#
#     if not vskit_results:
#         logger.warning("No drama found on VSKit for title: '%s'", clean_title)
#         return ShortDrama.objects.none(), "not_found"
#
#     scraped_dramas = []
#     scraped_count = 0
#
#     for drama_data in vskit_results:
#         if scraped_count >= max_scrape:
#             break
#
#         subject_id = drama_data.get("subjectId")
#         title_name = drama_data.get("title") or subject_id
#
#         # Check if drama already exists by subject_id in local database
#         existing_obj = ShortDrama.objects.filter(subject_id=subject_id, is_active=True).first()
#         if existing_obj and existing_obj.episodes.count() >= (existing_obj.total_episodes or 1):
#             logger.info("Drama '%s' (subject_id=%s) already exists in DB with full episodes. Returning existing.", title_name, subject_id)
#             scraped_dramas.append(existing_obj)
#             scraped_count += 1
#             continue
#
#         try:
#             logger.info("Saving and scraping drama: %s (subject_id=%s)", title_name, subject_id)
#             drama_obj = save_drama(drama_data)
#             scrape_drama(drama_obj)
#             scraped_dramas.append(drama_obj)
#             scraped_count += 1
#         except Exception as exc:
#             logger.exception("Failed to scrape drama '%s': %s", title_name, exc)
#         finally:
#             close_old_connections()
#
#     # Step 3: Return updated queryset from DB (including scraped dramas and any keyword matches)
#     scraped_ids = [d.id for d in scraped_dramas]
#     result_qs = ShortDrama.objects.filter(
#         Q(title__icontains=clean_title) | Q(id__in=scraped_ids),
#         is_active=True,
#     ).prefetch_related("episodes").distinct().order_by("title")
#
#     source = "scraped" if result_qs.exists() else "not_found"
#     return result_qs, source
#
#
# def main():
#     parser = argparse.ArgumentParser(description="Search drama by title in database or scrape from VSKit")
#     parser.add_argument("title", type=str, help="Title of the drama to search")
#     parser.add_argument("--max-scrape", type=int, default=1, help="Maximum number of dramas to scrape if not found in DB")
#     parser.add_argument("--force-scrape", action="store_true", help="Force scraping from VSKit even if found in DB")
#
#     args = parser.parse_args()
#
#     print(f"\n=== Searching for Drama: '{args.title}' ===")
#     dramas_qs, source = get_or_scrape_drama_by_title(
#         title=args.title,
#         max_scrape=args.max_scrape,
#         force_scrape=args.force_scrape,
#     )
#
#     print(f"\nResult Source: {source.upper()}")
#     print(f"Total Dramas Found: {dramas_qs.count()}")
#
#     for drama in dramas_qs:
#         ep_count = drama.episodes.count()
#         print(f"\n- Drama ID: {drama.id}")
#         print(f"  Title: {drama.title}")
#         print(f"  Subject ID: {drama.subject_id}")
#         print(f"  Slug: {drama.slug}")
#         print(f"  Total Episodes: {drama.total_episodes} (Saved in DB: {ep_count})")
#         print(f"  Country: {drama.country.name if drama.country else 'N/A'}")
#         print(f"  Genres: {', '.join([g.name for g in drama.genres.all()]) if drama.genres.exists() else 'N/A'}")
#
#
# if __name__ == "__main__":
#     main()

import argparse
import logging
import os
import sys
import django

# Setup Django environment before importing scraper/models.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
django.setup()

from django.db import close_old_connections
from django.db.models import Q
from api.models import ShortDrama
import shortdrama_scraper as scraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("search_and_scrape")


# Reuse the exact same authenticated Premium session and scraper logic as the
# working main scraper. This avoids having a second copy of auth/browser headers
# that can drift out of sync.
BEARER_TOKEN = scraper.BEARER_TOKEN
session = scraper.session
request_json = scraper.request_json
save_drama = scraper.save_drama
scrape_drama = scraper.scrape_drama
safe_int = scraper.safe_int

SEARCH_API_URL = (
    "https://h5-api.aoneroom.com/"
    "wefeed-h5api-bff/vskit/search"
)

DEFAULT_PER_PAGE = int(os.getenv("VSKIT_SEARCH_PER_PAGE", "20"))
DEFAULT_SEARCH_PAGES = int(os.getenv("VSKIT_SEARCH_PAGES", "3"))


def normalize_title(value):
    return " ".join((value or "").casefold().split())


def playable_episode_count(drama):
    """Count stored episodes that currently have a non-empty media URL."""
    total = safe_int(drama.total_episodes, 0)

    queryset = drama.episodes.filter(is_active=True)

    if total > 0:
        queryset = queryset.filter(
            episode_number__gte=1,
            episode_number__lte=total,
        )

    return queryset.filter(
        play_url__isnull=False,
    ).exclude(
        play_url="",
    ).count()


def drama_is_complete(drama):
    """A drama is complete only when every expected episode has a media URL."""
    total = safe_int(drama.total_episodes, 0)

    if total <= 0:
        return False

    return playable_episode_count(drama) >= total


def extract_search_items(payload):
    """Support both known VSKit search response shapes: data.list/data.items."""
    if not payload:
        return [], {}

    data = payload.get("data") or {}
    items = data.get("list")

    if not isinstance(items, list):
        items = data.get("items")

    if not isinstance(items, list):
        items = []

    pager = data.get("pager") or {}
    return items, pager


def search_vskit_dramas(
    keyword,
    *,
    per_page=DEFAULT_PER_PAGE,
    max_pages=DEFAULT_SEARCH_PAGES,
):
    """
    Search VSKit using the same Premium-authenticated session as the main
    scraper. Results are deduplicated by subjectId.
    """
    keyword = (keyword or "").strip()

    if not keyword:
        return []

    max_pages = max(1, safe_int(max_pages, 1))
    per_page = max(1, safe_int(per_page, DEFAULT_PER_PAGE))

    results = []
    seen_subject_ids = set()
    page = 1

    while page <= max_pages:
        payload = request_json(
            SEARCH_API_URL,
            method="GET",
            params={
                "keyword": keyword,
                "page": page,
                "perPage": per_page,
            },
            description=(
                f"Search VSKit keyword={keyword!r} page={page}"
            ),
        )

        if not payload:
            break

        items, pager = extract_search_items(payload)

        logger.info(
            "VSKit search page=%s returned %s item(s) for %r.",
            page,
            len(items),
            keyword,
        )

        for item in items:
            if not isinstance(item, dict):
                continue

            subject_id = item.get("subjectId")
            dedupe_key = str(subject_id or item.get("subjectSeoKey") or "")

            if not dedupe_key or dedupe_key in seen_subject_ids:
                continue

            seen_subject_ids.add(dedupe_key)
            results.append(item)

        if not items:
            break

        has_more = pager.get("hasMore")
        next_page = safe_int(pager.get("nextPage"), 0)

        if has_more is False:
            break

        if next_page > page:
            page = next_page
        else:
            page += 1

    # Prefer an exact title match before looser search results.
    wanted = normalize_title(keyword)
    results.sort(
        key=lambda item: (
            normalize_title(item.get("title")) != wanted,
            normalize_title(item.get("title")),
        )
    )

    logger.info(
        "VSKit search returned %s unique result(s) for %r.",
        len(results),
        keyword,
    )

    return results


def repair_existing_matches(queryset):
    """Fill missing/no-url episodes for local matches with paid mini-list flow."""
    repaired_any = False

    for drama in queryset:
        if drama_is_complete(drama):
            continue

        logger.info(
            "Local drama %r is incomplete: playable=%s total=%s. "
            "Running paid scraper repair.",
            drama.title,
            playable_episode_count(drama),
            drama.total_episodes,
        )

        try:
            scrape_drama(drama)
            repaired_any = True
        except Exception:
            logger.exception(
                "Failed repairing existing drama %r.",
                drama.title,
            )
        finally:
            close_old_connections()

    return repaired_any


def get_or_scrape_drama_by_title(
    title,
    *,
    max_scrape=1,
    force_scrape=False,
    repair_existing=True,
    per_page=DEFAULT_PER_PAGE,
    search_pages=DEFAULT_SEARCH_PAGES,
):
    """
    1. Find matching active dramas in the local DB.
    2. Optionally repair local rows whose episode set is incomplete or has
       missing play URLs using the working paid mini-list scraper.
    3. If needed (or force_scrape=True), search VSKit and save/scrape results.

    Returns: (queryset, source)
    """
    if not title or not title.strip():
        return ShortDrama.objects.none(), "invalid_input"

    clean_title = title.strip()
    max_scrape = max(1, safe_int(max_scrape, 1))

    existing_dramas = (
        ShortDrama.objects
        .filter(
            title__icontains=clean_title,
            is_active=True,
        )
        .select_related("country")
        .prefetch_related("genres", "episodes")
        .order_by("title")
    )

    if not force_scrape and existing_dramas.exists():
        existing_count = existing_dramas.count()
        logger.info(
            "Found %s matching local drama(s) for %r.",
            existing_count,
            clean_title,
        )

        repaired = False
        if repair_existing:
            repaired = repair_existing_matches(existing_dramas)

        # Return a fresh queryset because scrape_drama may have added episodes.
        result_qs = (
            ShortDrama.objects
            .filter(
                title__icontains=clean_title,
                is_active=True,
            )
            .select_related("country")
            .prefetch_related("genres", "episodes")
            .order_by("title")
        )

        return (
            result_qs,
            "database_repaired" if repaired else "database",
        )

    logger.info(
        "Searching VSKit for %r (force_scrape=%s).",
        clean_title,
        force_scrape,
    )

    vskit_results = search_vskit_dramas(
        clean_title,
        per_page=per_page,
        max_pages=search_pages,
    )

    if not vskit_results:
        logger.warning(
            "No drama found on VSKit for title %r.",
            clean_title,
        )
        return ShortDrama.objects.none(), "not_found"

    processed_ids = []
    processed_count = 0

    for drama_data in vskit_results:
        if processed_count >= max_scrape:
            break

        subject_id = drama_data.get("subjectId")
        title_name = drama_data.get("title") or subject_id or "unknown"
        slug = drama_data.get("subjectSeoKey")

        if not subject_id or not slug:
            logger.warning(
                "Skipping VSKit search result without subjectId/subjectSeoKey: %r",
                title_name,
            )
            continue

        existing_obj = (
            ShortDrama.objects
            .filter(
                subject_id=subject_id,
                is_active=True,
            )
            .first()
        )

        if existing_obj and drama_is_complete(existing_obj) and not force_scrape:
            logger.info(
                "Drama %r already exists and is fully playable (%s/%s).",
                title_name,
                playable_episode_count(existing_obj),
                existing_obj.total_episodes,
            )
            processed_ids.append(existing_obj.id)
            processed_count += 1
            continue

        try:
            logger.info(
                "Saving/scraping VSKit result: %s | subject_id=%s",
                title_name,
                subject_id,
            )

            # The working main scraper's save_drama() also refreshes richer
            # metadata (country/genre/release date) from the watch payload.
            drama_obj = save_drama(drama_data)

            # The working main scraper's scrape_drama() uses shorts/mini-list
            # with the Premium session and repairs missing/no-url episodes.
            scrape_drama(drama_obj)

            processed_ids.append(drama_obj.id)
            processed_count += 1

        except Exception:
            logger.exception(
                "Failed to scrape drama %r (subject_id=%s).",
                title_name,
                subject_id,
            )
        finally:
            close_old_connections()

    result_qs = (
        ShortDrama.objects
        .filter(
            Q(title__icontains=clean_title)
            | Q(id__in=processed_ids),
            is_active=True,
        )
        .select_related("country")
        .prefetch_related("genres", "episodes")
        .distinct()
        .order_by("title")
    )

    source = "scraped" if result_qs.exists() else "not_found"
    return result_qs, source


def print_drama_summary(drama):
    total = safe_int(drama.total_episodes, 0)
    stored = drama.episodes.filter(is_active=True).count()
    playable = playable_episode_count(drama)

    print(f"\n- Drama ID: {drama.id}")
    print(f"  Title: {drama.title}")
    print(f"  Subject ID: {drama.subject_id}")
    print(f"  Slug: {drama.slug}")
    print(
        f"  Total Episodes: {total} "
        f"(Stored: {stored}, Playable URLs: {playable})"
    )
    print(
        "  Country: "
        f"{drama.country.name if drama.country_id else 'N/A'}"
    )
    print(
        "  Genres: "
        + (
            ", ".join(drama.genres.values_list("name", flat=True))
            or "N/A"
        )
    )
    print(
        "  Release Date: "
        f"{drama.release_date if drama.release_date else 'N/A'}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Search a drama locally or on VSKit and scrape it with the "
            "working Premium mini-list flow."
        )
    )
    parser.add_argument(
        "title",
        type=str,
        help="Title of the drama to search",
    )
    parser.add_argument(
        "--max-scrape",
        type=int,
        default=1,
        help="Maximum number of VSKit search results to scrape (default: 1)",
    )
    parser.add_argument(
        "--force-scrape",
        action="store_true",
        help="Search VSKit and rescrape even if a local title match exists",
    )
    parser.add_argument(
        "--no-repair-existing",
        action="store_true",
        help=(
            "When a local title match exists, return it without repairing "
            "missing/no-url episodes"
        ),
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=DEFAULT_PER_PAGE,
        help=f"VSKit search results per page (default: {DEFAULT_PER_PAGE})",
    )
    parser.add_argument(
        "--search-pages",
        type=int,
        default=DEFAULT_SEARCH_PAGES,
        help=f"Maximum VSKit search pages (default: {DEFAULT_SEARCH_PAGES})",
    )

    args = parser.parse_args()

    if not BEARER_TOKEN:
        logger.error(
            "No VSKit bearer token is available from shortdrama_scraper."
        )
        return 2

    token_fp = getattr(scraper, "TOKEN_FINGERPRINT", "unknown")
    logger.info(
        "Using shared shortdrama_scraper Premium session | "
        "bearer=True token_fp=%s",
        token_fp,
    )

    print(f"\n=== Searching for Drama: {args.title!r} ===")

    dramas_qs, source = get_or_scrape_drama_by_title(
        title=args.title,
        max_scrape=args.max_scrape,
        force_scrape=args.force_scrape,
        repair_existing=not args.no_repair_existing,
        per_page=args.per_page,
        search_pages=args.search_pages,
    )

    print(f"\nResult Source: {source.upper()}")
    print(f"Total Dramas Found: {dramas_qs.count()}")

    for drama in dramas_qs:
        print_drama_summary(drama)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        close_old_connections()
