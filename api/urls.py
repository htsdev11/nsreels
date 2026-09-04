from django.urls import path

from api.views import AllShortDramaView, ShortDramaByIDView, ShortDramaByNameView, ShortDramaForyouView, \
    ShortDramaForyouByCategoryView, EveryoneWatchingView, HomepageBannerAPIView, ShortDramaByGenreView, \
    ShortDramaByCountryView, ShortDramaByReleaseYearView, ShortDramaFiltersAPIView, ShortDramaGenreListView, \
    ShortDramaCountryListView, ShortDramaReleaseYearListView, ShortDramaSortingFilters, ShortDramaTopPicksView, \
    SearchAndScrapeDramaView

urlpatterns = [


    path("short-drama/filter/",ShortDramaFiltersAPIView.as_view(),name="short-drama-filter",),
    path("genres/",ShortDramaGenreListView.as_view(),name="short-drama-genres",),
    path("countries/",ShortDramaCountryListView.as_view(),name="short-drama-countries",),
    path("years/",ShortDramaReleaseYearListView.as_view(),name="short-drama-release-years",),


    path("short-drama/",AllShortDramaView.as_view(),),
    path("short-drama/detail/",ShortDramaByIDView.as_view(),),
    path("short-drama/search/",ShortDramaByNameView.as_view(),),
    path("short-drama/search-and-scrape/",SearchAndScrapeDramaView.as_view(),name="short-drama-search-and-scrape",),
    path("short-drama/genre/",ShortDramaByGenreView.as_view(),name="short-drama-by-genre",),
    path("short-drama/country/",ShortDramaByCountryView.as_view(),name="short-drama-by-country",),
    path("short-drama/year/",ShortDramaByReleaseYearView.as_view(),name="short-drama-by-release-year",),
    path("sort/", ShortDramaSortingFilters.as_view(), name="short-drama-sorting", ),
    path("sort/top_pick", ShortDramaTopPicksView.as_view(), name="short-drama-sorting", ),

    path("short-drama/foryou/", ShortDramaForyouView.as_view(),),
    path("short-drama/foryou/category/",ShortDramaForyouByCategoryView.as_view(),),

    path("short-drama/everyone/", EveryoneWatchingView.as_view(), ),
    path("homepage/banners/",HomepageBannerAPIView.as_view(),name="homepage-banners",),
]