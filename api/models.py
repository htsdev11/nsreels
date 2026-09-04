from django.db import models
from datetime import timedelta
from django.utils import timezone


class ShortDramaGenre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Short Drama Genre"
        verbose_name_plural = "Short Drama Genres"

    def __str__(self):
        return self.name


class ShortDramaCountry(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=5, blank=True, null=True)
    slug = models.SlugField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Short Drama Country"
        verbose_name_plural = "Short Drama Countries"

    def __str__(self):
        return self.name


class ShortDramaForyou(models.Model):
    title = models.CharField(max_length=200)
    dramas = models.ManyToManyField("ShortDrama",blank=True,related_name="foryou_categories")
    order_by = models.IntegerField(default=0)
    last_update = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order_by"]

    def __str__(self):
        return self.title


class ShortDrama(models.Model):
    subject_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    cover = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
    genres = models.ManyToManyField(ShortDramaGenre,blank=True,related_name="dramas",)
    country = models.ForeignKey(ShortDramaCountry,on_delete=models.SET_NULL,null=True,blank=True,related_name="dramas",)
    release_date = models.DateField(null=True,blank=True,)
    total_episodes = models.PositiveIntegerField(default=0)
    is_everyone_search = models.BooleanField(default=False)
    total_views = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    last_episode_refresh = models.DateTimeField(null=True,blank=True,)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

class ShortDramaEpisode(models.Model):
    REFRESH_BUFFER = timedelta(minutes=30)
    drama = models.ForeignKey(ShortDrama,on_delete=models.CASCADE,related_name="episodes",)
    mini_id = models.CharField(max_length=100,unique=True,)
    subject_id = models.CharField(max_length=100)
    season = models.PositiveIntegerField(default=1)
    episode_number = models.PositiveIntegerField()
    play_url = models.URLField(max_length=2000)
    expires_at = models.DateTimeField(null=True,blank=True,db_index=True,)
    last_refreshed = models.DateTimeField( auto_now=True,)
    thumbnail = models.URLField(blank=True, null=True)
    duration = models.PositiveIntegerField(blank=True,null=True,help_text="Duration in seconds",)
    width = models.PositiveIntegerField(blank=True, null=True)
    height = models.PositiveIntegerField(blank=True, null=True)
    file_size = models.BigIntegerField(blank=True, null=True)
    lock_status = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.drama.title} - Episode {self.episode_number}"

    @property
    def needs_refresh(self):
        """
        Returns True when the signed URL should be refreshed.
        """
        if not self.expires_at:
            return True

        return self.expires_at <= (
            timezone.now() + self.REFRESH_BUFFER
        )