import requests

from bs4 import BeautifulSoup
from django.core.cache import cache
from urllib.parse import urlsplit

CACHE_KEY = "homepage_banners"
CACHE_TIMEOUT = 60 * 60 * 24  # 24 hours

URL = "https://vskit.tv"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


class BannerService:

    @classmethod
    def scrape_banners(cls):
        session = requests.Session()

        response = session.get(
            URL,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        banners = []
        seen = set()

        slides = soup.select(
            "div.absolute.inset-0.transition-opacity.duration-700"
        )

        for slide in slides:
            img = slide.select_one("img.md\\:hidden")

            if not img:
                continue

            title = (img.get("alt") or "").strip()

            if not title:
                continue

            src = img.get("src")

            if not src:
                continue

            if "pbcdn.aoneroom.com" not in src:
                continue

            image = urlsplit(src)._replace(query="").geturl()

            if title in seen:
                continue

            seen.add(title)

            banners.append({
                "title": title,
                "image": image,
            })

        return banners

    @classmethod
    def get_banners(cls):
        banners = cache.get(CACHE_KEY)
        # print("CACHE.....",banners)

        if banners is not None:
            return banners

        banners = cls.scrape_banners()
        # print(".....", banners)

        cache.set(
            CACHE_KEY,
            banners,
            CACHE_TIMEOUT,
        )

        return banners