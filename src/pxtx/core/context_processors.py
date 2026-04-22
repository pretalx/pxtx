from django.conf import settings


def deploy(request):
    return {"deploy_enabled": bool(getattr(settings, "DEPLOY_FLAG_FILE", ""))}
