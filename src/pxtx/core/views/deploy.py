from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from pxtx.core.views._helpers import is_htmx


def _superuser_required(view):
    return user_passes_test(lambda u: u.is_active and u.is_superuser)(view)


@login_required
@_superuser_required
@require_POST
def trigger_deploy(request):
    flag_path = getattr(settings, "DEPLOY_FLAG_FILE", "") or ""
    if not flag_path:
        if is_htmx(request):
            return HttpResponse(
                status=204, headers={"HX-Redirect": reverse("core:dashboard")}
            )
        return redirect("core:dashboard")

    target = Path(flag_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{request.user.username} {timezone.now().isoformat()}\n")

    if is_htmx(request):
        return render(request, "core/_deploying.html")

    return redirect(request.META.get("HTTP_REFERER") or reverse("core:dashboard"))


def healthz(request):
    return JsonResponse({"status": "ok"})
