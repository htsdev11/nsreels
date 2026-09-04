from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.shortcuts import render
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.service import BannerService
from api.models import ShortDrama, ShortDramaForyou, ShortDramaEpisode, ShortDramaGenre, ShortDramaCountry
from api.pagination import CustomPagination
from api.serializers import ShortDramaListSerializer, ShortDramaDetailSerializer, ShortDramaForyouSerializer


CACHE_TIMEOUT = 60 * 60
# class AllShortDramaView(APIView):
#     authentication_classes = [TokenAuthentication]
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         cache_key = f"all_short_dramas_{request.GET.urlencode()}"
#         cached_data = cache.get(cache_key)
#         if cached_data is not None:
#             return Response(cached_data)
#
#         queryset = (
#             ShortDrama.objects.filter(
#                 is_active=True
#             )
#             .prefetch_related(
#                 Prefetch(
#                     "episodes",
#                     queryset=ShortDramaEpisode.objects.only(
#                         "episode_number",
#                         "play_url",
#                         "thumbnail",
#                         "duration"
#                     ).order_by("episode_number"),
#                     to_attr="ordered_episodes",
#                 )
#             )
#             .order_by("?")
#         )
#
#         paginator = CustomPagination()
#         page = paginator.paginate_queryset(
#             queryset,
#             request,
#         )
#
#         serializer = ShortDramaListSerializer(
#             page,
#             many=True,
#         )
#
#         response = paginator.get_paginated_response(
#             serializer.data
#         )
#         cache.set(cache_key, response.data, CACHE_TIMEOUT)
#         return response

class AllShortDramaView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            ShortDrama.objects.filter(
                is_active=True
            )
            .prefetch_related(
                Prefetch(
                    "episodes",
                    queryset=ShortDramaEpisode.objects.only(
                        "episode_number",
                        "play_url",
                        "thumbnail",
                        "duration"
                    ).order_by("episode_number"),
                    to_attr="ordered_episodes",
                )
            )
            .order_by("?")
        )

        paginator = CustomPagination()
        page = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(
            page,
            many=True,
        )

        return paginator.get_paginated_response(serializer.data)

class ShortDramaByIDView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        drama_id = request.GET.get("id")

        if not drama_id:
            return Response(
                {
                    "status": "error",
                    "message": "id is required",
                    "data": {}
                },
                status=400,
            )

        cache_key = f"short_drama_id_{drama_id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        try:
            drama = ShortDrama.objects.prefetch_related(
                "episodes"
            ).get(
                id=drama_id,
                is_active=True,
            )

            serializer = ShortDramaDetailSerializer(drama)

            response_data = {
                "status": "success",
                "message": "Short drama fetched successfully",
                "data": serializer.data,
            }
            cache.set(cache_key, response_data, CACHE_TIMEOUT)
            return Response(response_data)

        except ShortDrama.DoesNotExist:
            return Response(
                {
                    "status": "error",
                    "message": "Short drama not found",
                    "data": {},
                },
                status=404,
            )

# class ShortDramaByNameView(APIView):
#     authentication_classes = [TokenAuthentication]
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         title = request.GET.get("title")
#
#         if not title:
#             return Response(
#                 {
#                     "status": "error",
#                     "message": "title is required",
#                     "data": {},
#                 },
#                 status=400,
#             )
#
#         cache_key = f"short_drama_name_{title}"
#         cached_data = cache.get(cache_key)
#         if cached_data is not None:
#             return Response(cached_data)
#
#         try:
#             drama = (
#                 ShortDrama.objects.prefetch_related("episodes")
#                 .filter(
#                     title__icontains=title,
#                     is_active=True,
#                 )
#             )
#
#             serializer = ShortDramaDetailSerializer(drama, many=True)
#
#             response_data = {
#                 "status": "success",
#                 "message": "Short drama fetched successfully",
#                 "data": serializer.data,
#             }
#             cache.set(cache_key, response_data, CACHE_TIMEOUT)
#             return Response(response_data)
#
#         except ShortDrama.DoesNotExist:
#             return Response(
#                 {
#                     "status": "error",
#                     "message": "Short drama not found",
#                     "data": {},
#                 },
#                 status=404,
#             )

class ShortDramaByNameView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            title = request.GET.get("title")

            if not title:
                return Response(
                    {
                        "status": "error",
                        "message": "title is required",
                        "data": {},
                    },
                    status=400,
                )

            dramas = (
                ShortDrama.objects
                .prefetch_related("episodes")
                .filter(
                    title__icontains=title,
                    is_active=True,
                )
                .order_by("title")
            )

            if not dramas.exists():
                return Response(
                    {
                        "status": "error",
                        "message": "No drama found",
                        "data": {},
                    },
                    status=404,
                )

            paginator = CustomPagination()
            page = paginator.paginate_queryset(dramas, request)

            serializer = ShortDramaDetailSerializer(
                page,
                many=True
            )

            return paginator.get_paginated_response(serializer.data)

        except Exception:
            return Response(
                {
                    "status": "error",
                    "message": "Something went wrong",
                    "data": {},
                },
                status=500,
            )


class SearchAndScrapeDramaView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            title = request.GET.get("title")

            if not title:
                return Response(
                    {
                        "status": "error",
                        "message": "title parameter is required",
                        "data": {},
                    },
                    status=400,
                )

            max_scrape = request.GET.get("max_scrape", "1")
            try:
                max_scrape_int = int(max_scrape)
            except ValueError:
                max_scrape_int = 1

            from search_and_scrape_drama import get_or_scrape_drama_by_title
            dramas, source = get_or_scrape_drama_by_title(title=title, max_scrape=max_scrape_int)

            if not dramas.exists():
                return Response(
                    {
                        "status": "error",
                        "message": "No drama found on database or external platform",
                        "data": {},
                    },
                    status=404,
                )

            paginator = CustomPagination()
            page = paginator.paginate_queryset(dramas, request)

            serializer = ShortDramaDetailSerializer(
                page,
                many=True
            )

            response = paginator.get_paginated_response(serializer.data)
            response.data["source"] = source
            return response

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": f"Something went wrong: {str(e)}",
                    "data": {},
                },
                status=500,
            )

class ShortDramaForyouView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = "short_drama_foryou"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        queryset = ShortDramaForyou.objects.prefetch_related(
            "dramas"
        ).filter(
            is_active=True
        ).order_by("order_by")

        serializer = ShortDramaForyouSerializer(
            queryset,
            many=True
        )

        response_data = {
            "status": "success",
            "message": "ForYou fetched successfully",
            "data": serializer.data,
        }
        cache.set(cache_key, response_data, CACHE_TIMEOUT)
        return Response(response_data)

class ShortDramaForyouByCategoryView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.GET.get("search")

        if not search:
            return Response(
                {
                    "status": "error",
                    "message": "search parameter is required",
                    "data": {},
                },
                status=400,
            )

        cache_key = f"short_drama_category_{search}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        try:
            queryset = (
                ShortDramaForyou.objects.prefetch_related("dramas")
                .get(
                    title__icontains=search,
                    is_active=True,
                )
            )

            serializer = ShortDramaForyouSerializer(queryset)

            response_data = {
                "status": "success",
                "message": "Category fetched successfully",
                "data": serializer.data,
            }
            cache.set(cache_key, response_data, CACHE_TIMEOUT)
            return Response(response_data)

        except ShortDramaForyou.DoesNotExist:
            return Response(
                {
                    "status": "error",
                    "message": "Category not found",
                    "data": {},
                },
                status=404,
            )

class EveryoneWatchingView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        titles = (
            ShortDrama.objects.filter(
                is_active=True,
                is_everyone_search=True,
            )
            .values("title")
        )

        return Response(
            {
                "status": "success",
                "message": None,
                "data": list(titles),
            },
            status=status.HTTP_200_OK,
        )

class HomepageBannerAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        banners = BannerService.get_banners()

        return Response(
            {
                "success": True,
                "count": len(banners),
                "results": banners,
            },
            status=status.HTTP_200_OK,
        )


class ShortDramaFiltersAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    CACHE_TIMEOUT = 60 * 60 * 24  # 24 Hours

    def get(self, request, *args, **kwargs):
        # Genres
        genres = cache.get("short_drama_genres")
        if genres is None:
            genres = list(
                ShortDramaGenre.objects.filter(is_active=True)
                .order_by("name")
                .values("id", "name", "slug")
            )
            cache.set(
                "short_drama_genres",
                genres,
                self.CACHE_TIMEOUT,
            )

        # Countries
        countries = cache.get("short_drama_countries")
        if countries is None:
            countries = list(
                ShortDramaCountry.objects.filter(is_active=True)
                .order_by("name")
                .values("id", "name", "code", "slug")
            )
            cache.set(
                "short_drama_countries",
                countries,
                self.CACHE_TIMEOUT,
            )

        # Years
        years = cache.get("short_drama_years")
        if years is None:
            years = [
                d.year
                for d in ShortDrama.objects.filter(
                    is_active=True,
                    release_date__isnull=False,
                ).dates(
                    "release_date",
                    "year",
                    order="DESC",
                )
            ]

            cache.set(
                "short_drama_years",
                years,
                self.CACHE_TIMEOUT,
            )

        return Response(
            {
                "status": "success",
                "message": None,
                "filters": [
                    {
                        "name": "genres",
                        "data": genres,
                    },
                    {
                        "name": "countries",
                        "data": countries,
                    },
                    {
                        "name": "years",
                        "data": years,
                    },
                ],
            },
            status=status.HTTP_200_OK,
        )

class ShortDramaGenreListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        genres = (
            ShortDramaGenre.objects
            .filter(is_active=True)
            .order_by("name")
            .values("id", "name", "slug")
        )

        return Response({
            "status": "success",
            "count": len(genres),
            "message": "Genres fetched successfully",
            "data": genres,
        })

class ShortDramaCountryListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        countries = (
            ShortDramaCountry.objects
            .filter(is_active=True)
            .order_by("name")
            .values("id", "name", "code", "slug")
        )

        return Response({
            "status": "success",
            "count": len(countries),
            "message": "Countries fetched successfully",
            "data": countries,
        })

class ShortDramaReleaseYearListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        years = [
            d.year
            for d in ShortDrama.objects.filter(
                is_active=True,
                release_date__isnull=False,
            ).dates("release_date", "year", order="DESC")
        ]

        return Response(
            {
                "status": "success",
                "count": len(years),
                "message": "Release years fetched successfully",
                "data": years,
            }
        )

class ShortDramaByGenreView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        genre = request.GET.get("genre")

        if not genre:
            return Response(
                {
                    "status": "error",
                    "message": "Genre is required",
                    "data": {},
                },
                status=400,
            )

        queryset = (
            ShortDrama.objects.filter(
                is_active=True,
                genres__name__iexact=genre,
            )
            .prefetch_related("genres")
            .select_related("country")
            .distinct()
            .order_by("-id")
        )

        paginator = CustomPagination()
        page = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class ShortDramaByCountryView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        country = request.GET.get("country")

        if not country:
            return Response(
                {
                    "status": "error",
                    "message": "Country is required",
                    "data": {},
                },
                status=400,
            )

        queryset = (
            ShortDrama.objects.filter(
                is_active=True,
                country__name__iexact=country,
            )
            .prefetch_related("genres")
            .select_related("country")
            .order_by("-id")
        )

        paginator = CustomPagination()
        page = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class ShortDramaByReleaseYearView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        year = request.GET.get("year")

        if not year:
            return Response(
                {
                    "status": "error",
                    "message": "Year is required",
                    "data": {},
                },
                status=400,
            )

        queryset = (
            ShortDrama.objects.filter(
                is_active=True,
                release_date__year=year,
            )
            .prefetch_related("genres")
            .select_related("country")
            .order_by("-id")
        )

        paginator = CustomPagination()
        page = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class ShortDramaSortingFilters(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        category = request.query_params.get("category")
        genre = request.query_params.get("genre")
        country = request.query_params.get("country")
        year = request.query_params.get("year")

        filters = Q(is_active=True)

        # Genre (ManyToMany)
        if genre and genre != "All":
            filters &= Q(genres__name__iexact=genre)

        # Country (ForeignKey)
        if country and country != "All":
            filters &= Q(country__name__iexact=country)

        # Release Year
        if year and year != "All":
            filters &= Q(release_date__year=year)

        queryset = (
            ShortDrama.objects
            .filter(filters)
            .prefetch_related("genres")
            .select_related("country")
            .distinct()
            .order_by("-release_date", "-id")
        )

        if category == "top_picks":
            queryset = queryset.order_by("-created_at")[:100]
        else:
            queryset = queryset.order_by("-release_date", "-id")

        paginator = CustomPagination()
        paginated_qs = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(
            paginated_qs,
            many=True
        )

        return paginator.get_paginated_response(serializer.data)

# class ShortDramaTopPicksView(APIView):
#     authentication_classes = [TokenAuthentication]
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         # queryset = (
#         #     ShortDrama.objects
#         #     .filter(is_active=True)
#         #     .prefetch_related("genres")
#         #     .select_related("country")
#         #     .order_by("?")[:100]
#         # )
#
#         queryset = (
#             ShortDrama.objects.filter(
#                 is_active=True
#             )
#             .prefetch_related(
#                 Prefetch(
#                     "episodes",
#                     queryset=ShortDramaEpisode.objects.only(
#                         "episode_number",
#                         "play_url",
#                         "thumbnail",
#                         "duration"
#                     ).order_by("episode_number"),
#                     to_attr="ordered_episodes",
#                 )
#             )
#             .order_by("?")[:100]
#         )
#
#         serializer = ShortDramaListSerializer(
#             queryset,
#             many=True
#         )
#
#         response_data = {
#             "status": "success",
#             "message": "Top picks fetched successfully",
#             "data": serializer.data,
#         }
#
#         return Response(response_data)

class ShortDramaTopPicksView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            ShortDrama.objects.filter(is_active=True)
            .prefetch_related(
                Prefetch(
                    "episodes",
                    queryset=ShortDramaEpisode.objects.only(
                        "episode_number",
                        "play_url",
                        "thumbnail",
                        "duration"
                    ).order_by("episode_number"),
                    to_attr="ordered_episodes",
                )
            )
            .order_by("?")[:100]
        )

        paginator = CustomPagination()
        paginated_qs = paginator.paginate_queryset(queryset, request)

        serializer = ShortDramaListSerializer(
            paginated_qs,
            many=True
        )

        return paginator.get_paginated_response({
            "status": "success",
            "message": "Top picks fetched successfully",
            "data": serializer.data,
        })