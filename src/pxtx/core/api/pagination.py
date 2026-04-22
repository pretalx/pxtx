from rest_framework.pagination import CursorPagination


class CreatedAtCursorPagination(CursorPagination):
    """Default cursor pagination keyed on the ``created_at`` timestamp.

    DRF's default ``ordering`` is ``-created`` which doesn't exist on our
    models (our BaseModel uses ``created_at``).
    """

    ordering = "-created_at"
    page_size = 50
    max_page_size = 200


class TimestampCursorPagination(CursorPagination):
    """Activity log pagination, ordered by the log's own ``timestamp`` field."""

    ordering = "-timestamp"
    page_size = 50
    max_page_size = 200


class ChronologicalCursorPagination(CursorPagination):
    """Oldest-first pagination for comment lists — chronological is the
    natural reading order for a comment thread."""

    ordering = "created_at"
    page_size = 50
    max_page_size = 200
