"""
Vista de error amigable cuando un formulario no pasa la proteccion CSRF.

En vez de la pagina tecnica de Django, se muestra algo que el usuario
entienda: que la pagina estuvo mucho tiempo abierta y que recargue.
"""

import logging

from django.http import HttpResponse
from django.shortcuts import render
from django.template import RequestContext
from django.utils import timezone
from django.views.decorators.csrf import requires_csrf_token

registrador = logging.getLogger("cartera.errores")


@requires_csrf_token
def error_csrf(request, reason=""):
    """Pagina de error de CSRF explicada en palabras simples."""
    registrador.warning("Peticion bloqueada por CSRF: %s (%s)", request.path, reason)

    contexto = {
        "titulo": "La pagina esta muy vieja",
        "mensaje": (
            "La pagina estuvo abierta mucho tiempo y por seguridad el sistema "
            "no la dejo guardar los datos. Vuelva a abrirla e intente de nuevo."
        ),
        "sugerencia": (
            "Si le pasa siempre, revise la fecha y la hora de este computador: "
            "si estan muy desfasadas, el sistema cree que la pagina es vieja."
        ),
    }
    return render(request, "errores/csrf.html", contexto, status=403)
