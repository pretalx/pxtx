from django.db import models
from django.urls import reverse

from pxtx.core.models.base import BaseModel


class Milestone(BaseModel):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-target_date"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("core:milestone-detail", kwargs={"slug": self.slug})

    @property
    def is_released(self):
        return self.released_at is not None
