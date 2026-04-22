from django.db import models
from django.db.models import Q

from pxtx.core.models.base import BaseModel


class GithubRefKind(models.TextChoices):
    ISSUE = "issue", "Issue"
    PR = "pr", "Pull Request"
    COMMIT = "commit", "Commit"


class GithubRef(BaseModel):
    issue = models.ForeignKey(
        "core.Issue", related_name="github_refs", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=10, choices=GithubRefKind.choices)
    repo = models.CharField(max_length=200)
    number = models.IntegerField(null=True, blank=True)
    sha = models.CharField(max_length=40, blank=True)

    title = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind__in=[GithubRefKind.ISSUE, GithubRefKind.PR])
                    & Q(number__isnull=False)
                )
                | (Q(kind=GithubRefKind.COMMIT) & ~Q(sha="")),
                name="githubref_kind_consistency",
            )
        ]

    def __str__(self):
        return self.display

    @property
    def url(self):
        if self.kind == GithubRefKind.COMMIT:
            return f"https://github.com/{self.repo}/commit/{self.sha}"
        path = "pull" if self.kind == GithubRefKind.PR else "issues"
        return f"https://github.com/{self.repo}/{path}/{self.number}"

    @property
    def display(self):
        if self.kind == GithubRefKind.COMMIT:
            return f"{self.repo}@{self.sha[:7]}"
        sigil = "#" if self.kind == GithubRefKind.ISSUE else "!"
        return f"{self.repo}{sigil}{self.number}"
