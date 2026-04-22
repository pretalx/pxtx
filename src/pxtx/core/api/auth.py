from django.utils import timezone
from rest_framework import authentication, exceptions

from pxtx.core.models import ApiToken


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """Token auth backed by the hashed ``ApiToken`` model.

    Two transports, in order:

    1. ``Authorization: Token <plaintext>`` header (preferred).
    2. ``?token=<plaintext>`` query parameter.

    The query param exists because some tools (notably claude-code when poking
    at URLs ad-hoc) can't reliably set headers. Header auth should still be
    used wherever possible — the CLI does. Invalid tokens return 401 with no
    hint as to which half failed.
    """

    keyword = "Token"

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request)
        if auth:
            try:
                prefix, key = auth.decode("utf-8").split(" ", 1)
            except (ValueError, UnicodeDecodeError):
                return None
            if prefix.lower() == self.keyword.lower():
                return self._authenticate_credentials(key)
            return None
        key = request.query_params.get("token")
        if key:
            return self._authenticate_credentials(key)
        return None

    def authenticate_header(self, request):
        return self.keyword

    def _authenticate_credentials(self, key):
        token = ApiToken.lookup(key)
        if token is None or not token.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid token.")
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, token
