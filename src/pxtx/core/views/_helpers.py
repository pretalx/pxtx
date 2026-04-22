def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def request_actor(request):
    return f"user/{request.user.username}"
