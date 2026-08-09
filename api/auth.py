"""
Shared-password protection for the admin knowledge base endpoints.

The password comes from settings.ADMIN_PASSWORD (env: ADMIN_PASSWORD). Callers
supply it via the `X-Admin-Password` header or an `Authorization: Bearer <pwd>`
header. This is a single shared secret — deliberately lightweight, since the
project has no user/session machinery — so keep it strong and out of version
control (.env is gitignored).
"""
import hmac
from functools import wraps

from django.conf import settings
from rest_framework.response import Response


def extract_admin_token(request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return (request.headers.get("X-Admin-Password", "") or "").strip()


def require_admin_password(view_func):
    """Rejects the request with 401 unless the correct admin password is sent."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = getattr(settings, "ADMIN_PASSWORD", "") or ""
        provided = extract_admin_token(request)
        # Constant-time compare; deny outright if no password is configured.
        if not expected or not hmac.compare_digest(provided, expected):
            return Response(
                {"error": "Unauthorized. A valid admin password is required."},
                status=401,
            )
        return view_func(request, *args, **kwargs)

    return wrapper
