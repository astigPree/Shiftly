from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def health(request):
    """Readiness probe with no database credentials or exception details exposed."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response
