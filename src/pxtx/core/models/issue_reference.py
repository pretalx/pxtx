from django.db import models
from django.db.models import F, Q

from pxtx.core.models.base import BaseModel


class IssueReference(BaseModel):
    from_issue = models.ForeignKey(
        "core.Issue", related_name="references_from", on_delete=models.CASCADE
    )
    to_issue = models.ForeignKey(
        "core.Issue", related_name="references_to", on_delete=models.CASCADE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_issue", "to_issue"], name="unique_issue_ref"
            ),
            models.CheckConstraint(
                condition=~Q(from_issue=F("to_issue")), name="no_self_ref"
            ),
        ]

    def __str__(self):
        return f"{self.from_issue.slug} → {self.to_issue.slug}"
