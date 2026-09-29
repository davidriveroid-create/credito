"""
Rutas del proyecto.

OJO: las fotos de la cedula NO se sirven por MEDIA_URL. Si alguien intenta
acceder a /documentos/archivo.jpg sin sesion iniciada, no va a pasar: esa
ruta no existe. Las fotos se ven solo por la vista protegida 'ver_documento'.
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path


def inicio_sin_sesion(request):
    """Si no hay sesion, todo va a la pantalla de entrada."""
    from django.shortcuts import redirect
    from django.conf import settings
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect(f"/entrar/?siguiente={request.path}")


def salud(request):
    """Comprueba que el programa esta vivo. Util para la pantalla de inicio."""
    return HttpResponse("OK")


urlpatterns = [
    path("admin/", admin.site.urls),

    # Las fotos de cedula solo por vista protegida, nunca como archivo libre.
    path("documentos/", inicio_sin_sesion),

    # Cambio de contrasena de Django (redirigido a la propia del sistema).
    path("contrasena/",
         auth_views.PasswordChangeView.as_view(
             template_name="acceso/cambiar_clave.html",
             success_url="/panel/",
         ),
         name="django_cambiar_clave"),

    # Todo el sistema de ventas a credito.
    path("", include("cartera.urls")),
]
