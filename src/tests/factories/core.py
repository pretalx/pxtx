import factory

from pxtx.core.models import (
    Comment,
    GithubRef,
    GithubRefKind,
    Issue,
    IssueReference,
    Milestone,
    Source,
    Status,
    User,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "s3cret-pass-phrase")
        user = model_class(*args, **kwargs)
        user.set_password(password)
        user.save()
        return user


class MilestoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Milestone

    name = factory.Sequence(lambda n: f"Release {n}")
    slug = factory.Sequence(lambda n: f"release-{n}")


class IssueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Issue

    title = factory.Sequence(lambda n: f"Issue {n}")
    status = Status.OPEN
    source = Source.MANUAL


class CommentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Comment

    issue = factory.SubFactory(IssueFactory)
    author = factory.Sequence(lambda n: f"author-{n}")
    body = factory.Sequence(lambda n: f"Comment body {n}")


class GithubIssueRefFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GithubRef

    issue = factory.SubFactory(IssueFactory)
    kind = GithubRefKind.ISSUE
    repo = "pretalx/pretalx"
    number = factory.Sequence(lambda n: 1000 + n)


class GithubPrRefFactory(GithubIssueRefFactory):
    kind = GithubRefKind.PR


class GithubCommitRefFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GithubRef

    issue = factory.SubFactory(IssueFactory)
    kind = GithubRefKind.COMMIT
    repo = "pretalx/pretalx"
    sha = factory.Sequence(lambda n: f"{n:040x}")


class IssueReferenceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = IssueReference

    from_issue = factory.SubFactory(IssueFactory)
    to_issue = factory.SubFactory(IssueFactory)
