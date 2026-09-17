from django.db import connection
from django.http import JsonResponse


def readiness(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ready", "database": True})
    except Exception:
        return JsonResponse({"status": "not_ready", "database": False}, status=503)
