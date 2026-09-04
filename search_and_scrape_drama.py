import argparse
import logging
import os
import sys
import requests
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nsreel.settings")
django.setup()

from django.db import close_old_connections
from django.db.models import Q
from api.models import ShortDrama
from shortdrama_scraper import (
    BEARER_TOKEN,
    save_drama,
    scrape_drama,
    safe_int,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("search_and_scrape")

SEARCH_API_URL = "https://h5-api.aoneroom.com/wefeed-h5api-bff/vskit/search"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
    "Origin": "https://vskit.online",
    "Referer": "https://vskit.online/",
    "X-Client-Info": '{"timezone":"Asia/Karachi"}',
    "X-Request-Lang": "en",
    "X-Site-Domain": "https://vskit.online",
}


def search_vskit_dramas(keyword, page=1, per_page=10):
    """
    Queries the external VSKit H5 search API for a given keyword.
    """
    params = {
        "keyword": keyword,
        "page": page,
        "perPage": per_page,
    }

    try:
        response = requests.get(
            SEARCH_API_URL,
            headers=HEADERS,
            params=params,
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("code") == 0:
            drama_list = data.get("data", {}).get("list", [])
            logger.info("VSKit API returned %d search results for '%s'", len(drama_list), keyword)
            return drama_list
        else:
            logger.warning("VSKit search API returned code %s: %s", data.get("code"), data.get("message"))
            return []
    except Exception as exc:
        logger.error("Error calling VSKit search API for keyword '%s': %s", keyword, exc)
        return []


def get_or_scrape_drama_by_title(title, max_scrape=1, force_scrape=False):
    """
    Searches for drama by title in the local database.
    If available in database (and not force_scrape), returns (queryset, 'database').
    Otherwise, queries VSKit search API, scrapes metadata and episodes, saves to DB,
    and returns (queryset, 'scraped').
    """
    if not title or not title.strip():
        return ShortDrama.objects.none(), "invalid_input"

    clean_title = title.strip()

    # Step 1: Check Database
    if not force_scrape:
        existing_dramas = ShortDrama.objects.filter(
            title__icontains=clean_title,
            is_active=True,
        ).prefetch_related("episodes").order_by("title")

        if existing_dramas.exists():
            logger.info("Found %d matching drama(s) in local database for title: '%s'", existing_dramas.count(), clean_title)
            return existing_dramas, "database"

    # Step 2: Query VSKit Search API
    logger.info("Drama '%s' not found in database (or force_scrape=True). Searching VSKit API...", clean_title)
    vskit_results = search_vskit_dramas(clean_title)

    if not vskit_results:
        logger.warning("No drama found on VSKit for title: '%s'", clean_title)
        return ShortDrama.objects.none(), "not_found"

    scraped_dramas = []
    scraped_count = 0

    for drama_data in vskit_results:
        if scraped_count >= max_scrape:
            break

        subject_id = drama_data.get("subjectId")
        title_name = drama_data.get("title") or subject_id

        # Check if drama already exists by subject_id in local database
        existing_obj = ShortDrama.objects.filter(subject_id=subject_id, is_active=True).first()
        if existing_obj and existing_obj.episodes.count() >= (existing_obj.total_episodes or 1):
            logger.info("Drama '%s' (subject_id=%s) already exists in DB with full episodes. Returning existing.", title_name, subject_id)
            scraped_dramas.append(existing_obj)
            scraped_count += 1
            continue

        try:
            logger.info("Saving and scraping drama: %s (subject_id=%s)", title_name, subject_id)
            drama_obj = save_drama(drama_data)
            scrape_drama(drama_obj)
            scraped_dramas.append(drama_obj)
            scraped_count += 1
        except Exception as exc:
            logger.exception("Failed to scrape drama '%s': %s", title_name, exc)
        finally:
            close_old_connections()

    # Step 3: Return updated queryset from DB (including scraped dramas and any keyword matches)
    scraped_ids = [d.id for d in scraped_dramas]
    result_qs = ShortDrama.objects.filter(
        Q(title__icontains=clean_title) | Q(id__in=scraped_ids),
        is_active=True,
    ).prefetch_related("episodes").distinct().order_by("title")

    source = "scraped" if result_qs.exists() else "not_found"
    return result_qs, source


def main():
    parser = argparse.ArgumentParser(description="Search drama by title in database or scrape from VSKit")
    parser.add_argument("title", type=str, help="Title of the drama to search")
    parser.add_argument("--max-scrape", type=int, default=1, help="Maximum number of dramas to scrape if not found in DB")
    parser.add_argument("--force-scrape", action="store_true", help="Force scraping from VSKit even if found in DB")

    args = parser.parse_args()

    print(f"\n=== Searching for Drama: '{args.title}' ===")
    dramas_qs, source = get_or_scrape_drama_by_title(
        title=args.title,
        max_scrape=args.max_scrape,
        force_scrape=args.force_scrape,
    )

    print(f"\nResult Source: {source.upper()}")
    print(f"Total Dramas Found: {dramas_qs.count()}")

    for drama in dramas_qs:
        ep_count = drama.episodes.count()
        print(f"\n- Drama ID: {drama.id}")
        print(f"  Title: {drama.title}")
        print(f"  Subject ID: {drama.subject_id}")
        print(f"  Slug: {drama.slug}")
        print(f"  Total Episodes: {drama.total_episodes} (Saved in DB: {ep_count})")
        print(f"  Country: {drama.country.name if drama.country else 'N/A'}")
        print(f"  Genres: {', '.join([g.name for g in drama.genres.all()]) if drama.genres.exists() else 'N/A'}")


if __name__ == "__main__":
    main()
