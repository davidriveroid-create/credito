"""
Middlewares propios.

- `RegistroAccesosMiddleware` anota en el historial los ingresos al sistema
  y deja disponible el precio/config del negocio en cada peticion.
"""

import logging

from django.utils import timezone

from .models import HistorialMovimiento

registrador = logging.getLogger("cartera")


class RegistroAccesosMiddleware:
    """Guarda en el historial quien entro al sistema y cuando."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Antes de procesar: si acaba de iniciar sesion, se anota.
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            ya_registrado = request.session.get("ingreso_registrado")
            if not ya_registrado:
                request.session["ingreso_registrado"] = True
                HistorialMovimiento.objects.create(
                    usuario=usuario,
                    tipo=HistorialMovimiento.Tipo.INGRESO,
                    descripcion=f"{usuario.get_username()} ingreso al sistema",
                    direccion_ip=self._ip(request),
                )
        return self.get_response(request)

    @staticmethod
    def _ip(request):
        try:
            return request.META.get("REMOTE_ADDR") or None
        except Exception:
            return None
