from django.db import models

from pxtx.core.models.base import BaseModel


class Comment(BaseModel):
    issue = models.ForeignKey(
        "core.Issue", related_name="comments", on_delete=models.CASCADE
    )
    author = models.CharField(max_length=200)
    body = models.TextField()
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment by {self.author} on {self.issue.slug}"
