import hashlib
import secrets

from django.db import models

from pxtx.core.models.base import BaseModel

TOKEN_PREFIX = "pxtx_"  # noqa: S105
TOKEN_BYTES = 32  # → 43 urlsafe chars; prefix + 43 = 48 char plaintext


def _hash_token(plaintext):
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_token():
    """Return a fresh plaintext token. Never stored server-side in this form."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


class ApiToken(BaseModel):
    user = models.ForeignKey(
        "core.User", related_name="tokens", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    @classmethod
    def create(cls, *, user, name):
        """Create a token, returning (instance, plaintext).

        Plaintext is only available at creation time; only the hash is stored.
        """
        plaintext = generate_token()
        instance = cls.objects.create(
            user=user, name=name, token_hash=_hash_token(plaintext)
        )
        return instance, plaintext

    @classmethod
    def lookup(cls, plaintext):
        """Return the ApiToken for a plaintext, or None."""
        if not plaintext:
            return None
        try:
            return cls.objects.select_related("user").get(
                token_hash=_hash_token(plaintext)
            )
        except cls.DoesNotExist:
            return None
