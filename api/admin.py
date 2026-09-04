from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    ShortDrama,
    ShortDramaEpisode,
    ShortDramaForyou,
    ShortDramaCountry,
    ShortDramaGenre,
)


# ==========================================================
# Episode Admin
# ==========================================================
@admin.register(ShortDramaEpisode)
class ShortDramaEpisodeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "drama",
        "episode_number",
        "season",
        "duration",
        "lock_status",
        "is_active",
    )

    list_filter = (
        "is_active",
        "season",
        "lock_status",
    )

    search_fields = (
        "drama__title",
        "mini_id",
        "subject_id",
    )

    autocomplete_fields = ("drama",)

    readonly_fields = ("created_at",)

    ordering = (
        "drama",
        "episode_number",
    )

    list_select_related = ("drama",)

    list_per_page = 50


# ==========================================================
# Drama Admin
# ==========================================================
@admin.register(ShortDrama)
class ShortDramaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "country",
        "display_genres",
        "release_date",
        "total_episodes",
        "episode_count",
        "is_active",
    )

    search_fields = (
        "title",
        "subject_id",
        "slug",
    )

    list_filter = (
        "is_active",
        "country",
        "genres",
        "release_date",
    )

    autocomplete_fields = (
        "country",
        "genres",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "episode_badges",
    )

    list_select_related = ("country",)

    list_per_page = 50
    list_max_show_all = 200

    ordering = (
        "-release_date",
        "-id",
    )

    date_hierarchy = "release_date"

    fieldsets = (
        (
            "Drama Information",
            {
                "fields": (
                    "title",
                    "cover",
                    "description",
                    "genres",
                    "country",
                    "release_date",
                    "tags",
                )
            },
        ),
        (
            "Statistics",
            {
                "fields": (
                    "total_episodes",
                    "total_views",
                    "is_active",
                )
            },
        ),
        (
            "Episodes",
            {
                "fields": (
                    "episode_badges",
                )
            },
        ),
        (
            "System Information",
            {
                "classes": ("collapse",),
                "fields": (
                    "subject_id",
                    "slug",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    actions = [
        "make_active",
        "make_inactive",
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("country")
            .prefetch_related("genres", "episodes")
        )

    @admin.display(description="Genres")
    def display_genres(self, obj):
        return ", ".join(obj.genres.values_list("name", flat=True))

    @admin.display(description="Episodes", ordering="total_episodes")
    def episode_count(self, obj):
        count = obj.episodes.count()

        url = (
            reverse("admin:api_shortdramaepisode_changelist")
            + f"?drama__id__exact={obj.pk}"
        )

        return format_html('<a href="{}">{} Episodes</a>', url, count)

    @admin.display(description="Episode List")
    def episode_badges(self, obj):
        if not obj.pk:
            return "-"

        badges = []

        for ep in obj.episodes.all().order_by("episode_number"):
            url = reverse(
                "admin:api_shortdramaepisode_change",
                args=[ep.pk],
            )

            badges.append(
                f'<a href="{url}" '
                f'style="display:inline-block;'
                f'padding:6px 10px;'
                f'margin:4px;'
                f'background:#0d6efd;'
                f'color:white;'
                f'border-radius:5px;'
                f'text-decoration:none;">'
                f'Episode {ep.episode_number}'
                f"</a>"
            )

        return mark_safe("".join(badges))

    @admin.action(description="Activate selected dramas")
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} drama(s) activated.")

    @admin.action(description="Deactivate selected dramas")
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} drama(s) deactivated.")


# ==========================================================
# For You Admin
# ==========================================================
@admin.register(ShortDramaForyou)
class ShortDramaForyouAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "drama_count",
        "order_by",
        "is_active",
        "last_update",
    )

    search_fields = ("title",)

    list_filter = ("is_active",)

    filter_horizontal = ("dramas",)

    readonly_fields = ("last_update",)

    ordering = ("order_by",)

    list_per_page = 50

    @admin.display(description="Total Dramas")
    def drama_count(self, obj):
        return obj.dramas.count()


# ==========================================================
# Genre Admin
# ==========================================================
@admin.register(ShortDramaGenre)
class ShortDramaGenreAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "slug",
        "is_active",
    )

    search_fields = (
        "name",
        "slug",
    )

    list_filter = ("is_active",)

    prepopulated_fields = {
        "slug": ("name",),
    }

    ordering = ("name",)

    list_per_page = 50


# ==========================================================
# Country Admin
# ==========================================================
@admin.register(ShortDramaCountry)
class ShortDramaCountryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "code",
        "slug",
        "is_active",
    )

    search_fields = (
        "name",
        "code",
        "slug",
    )

    list_filter = ("is_active",)

    prepopulated_fields = {
        "slug": ("name",),
    }

    ordering = ("name",)

    list_per_page = 50