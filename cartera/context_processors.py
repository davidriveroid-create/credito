"""
Datos del negocio disponibles en TODAS las plantillas (logo, nombre,
moneda, menus, avisos).
"""

from django.conf import settings

from .models import Configuracion, MetodoPago
from .servicios.regularidad import configuracion


def negocio(request):
    """Se inyecta como 'negocio' en el contexto de cada pagina."""
    config = configuracion()
    usuario = getattr(request, "user", None)

    es_admin = False
    if usuario is not None and usuario.is_authenticated:
        perfil = getattr(usuario, "perfil", None)
        es_admin = bool(usuario.is_superuser or (perfil and perfil.es_administrador()))

    return {
        "negocio": config,
        "simbolo": config.moneda_simbolo or settings.MONEDA_SIMBOLO,
        "es_administrador": es_admin,
        "anio_actual": timezone_actual().year,
        "titulo_sistema": config.nombre_negocio,
    }


def timezone_actual():
    from django.utils import timezone
    return timezone.localtime()
