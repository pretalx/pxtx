from __future__ import annotations

import requests

DEFAULT_TIMEOUT = 30.0


class ApiError(Exception):
    def __init__(self, message, *, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class Client:
    def __init__(
        self,
        url: str,
        token: str,
        actor: str = "",
        session: requests.Session | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.url = url.rstrip("/")
        self.token = token
        self.actor = actor
        self.session = session or requests.Session()
        self.timeout = timeout

    def _endpoint(self, path: str) -> str:
        return f"{self.url}/api/v1{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Token {self.token}"}
        if self.actor:
            headers["X-Pxtx-Actor"] = self.actor
        return headers

    def _request(self, method, path, *, params=None, json=None):
        response = self.session.request(
            method,
            self._endpoint(path),
            headers=self._headers(),
            params=params,
            json=json,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            self._raise(method, path, response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    @staticmethod
    def _raise(method, path, response):
        try:
            body = response.json()
        except ValueError:
            body = response.text
        raise ApiError(
            f"{method} {path} → {response.status_code}: {body}",
            status=response.status_code,
            body=body,
        )

    def paginate(self, path, *, params=None):
        # Cursor-paginated lists return {"next": <url>, "results": [...]}.
        # The first request carries filter params; the server echoes them back
        # into the ``next`` URL so we don't need to re-send them.
        url = self._endpoint(path)
        first = True
        while url:
            response = self.session.get(
                url,
                headers=self._headers(),
                params=params if first else None,
                timeout=self.timeout,
            )
            first = False
            if response.status_code >= 400:
                self._raise("GET", path, response)
            data = response.json()
            yield from data["results"]
            url = data.get("next")

    def list_issues(self, **filters):
        return self.paginate(
            "/issues/", params={k: v for k, v in filters.items() if v is not None}
        )

    def get_issue(self, number):
        return self._request("GET", f"/issues/{number}/")

    def create_issue(self, payload):
        return self._request("POST", "/issues/", json=payload)

    def update_issue(self, number, payload):
        return self._request("PATCH", f"/issues/{number}/", json=payload)

    def transition_issue(self, number, action, payload=None):
        return self._request("POST", f"/issues/{number}/{action}/", json=payload or {})

    def add_comment(self, number, body):
        return self._request("POST", f"/issues/{number}/comments/", json={"body": body})

    def list_comments(self, number):
        return list(self.paginate(f"/issues/{number}/comments/"))

    def list_milestones(self):
        return self.paginate("/milestones/")

    def activity_log(self, **filters):
        return self.paginate(
            "/activity/", params={k: v for k, v in filters.items() if v is not None}
        )
