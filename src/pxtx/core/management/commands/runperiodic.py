import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlencode

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from pxtx.core.models import GithubRef, GithubRefKind, Issue, Source, Status

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
USER_AGENT = "pxtx-runperiodic"
ACTOR = "periodic/github-sync"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 30


class Command(BaseCommand):
    help = (
        "Poll configured GitHub repos for open issues and create ghost issues "
        "(status=draft, source=github) for any that are not yet linked via a "
        "GithubRef. Repos come from [github].repos in pxtx.toml "
        "(/etc/pxtx.toml or next to pyproject.toml). Token at [github].token."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo",
            action="append",
            dest="repos",
            metavar="owner/name",
            help=(
                "Repo to poll. Can be passed multiple times. Overrides "
                "settings.GITHUB_WATCH_REPOS entirely for this run."
            ),
        )

    def handle(self, *args, repos=None, **options):
        repos = repos or list(getattr(settings, "GITHUB_WATCH_REPOS", []))
        if not repos:
            self.stdout.write(
                "No repos configured; set GITHUB_WATCH_REPOS or pass --repo."
            )
            return

        total = 0
        for repo in repos:
            created = self._sync_repo(repo)
            total += created
            self.stdout.write(f"{repo}: created {created} ghost issue(s)")
        self.stdout.write(f"Done. {total} ghost issue(s) created.")

    def _sync_repo(self, repo):
        created = 0
        for payload in self._iter_issues(repo):
            # GitHub's issues endpoint returns PRs too; skip those.
            if payload.get("pull_request") is not None:
                continue
            number = payload.get("number")
            if number is None:
                continue
            if GithubRef.objects.filter(
                kind=GithubRefKind.ISSUE, repo=repo, number=number
            ).exists():
                continue
            title = (payload.get("title") or "")[:500]
            body = payload.get("body") or ""
            state = payload.get("state") or ""
            with transaction.atomic():
                issue = Issue(
                    title=title or f"{repo}#{number}",
                    description=body,
                    status=Status.DRAFT,
                    source=Source.GITHUB,
                )
                issue.save(actor=ACTOR)
                GithubRef.objects.create(
                    issue=issue,
                    kind=GithubRefKind.ISSUE,
                    repo=repo,
                    number=number,
                    title=title,
                    state=state,
                )
            created += 1
            logger.info("Created ghost issue %s for %s#%s", issue.slug, repo, number)
        return created

    def _iter_issues(self, repo):
        page = 1
        while True:
            query = urlencode({"state": "open", "per_page": PAGE_SIZE, "page": page})
            url = f"{GITHUB_API}/repos/{repo}/issues?{query}"
            try:
                data = self._fetch(url)
            except urllib.error.HTTPError as exc:
                logger.exception("GitHub %s for %s: %s", exc.code, repo, exc.reason)
                return
            except urllib.error.URLError as exc:
                logger.exception("Network error for %s: %s", repo, exc.reason)
                return
            if not data:
                return
            yield from data
            if len(data) < PAGE_SIZE:
                return
            page += 1

    def _fetch(self, url):
        request = urllib.request.Request(url, headers=self._headers())  # noqa: S310
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        token = getattr(settings, "GITHUB_TOKEN", "") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
