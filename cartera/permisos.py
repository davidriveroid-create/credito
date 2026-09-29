"""
Permisos y decoradores de acceso.

Aqui se decide quien puede ver y hacer que. La idea es que las vistas no
tengan que repetir estas comprobaciones.

Roles:
    ADMINISTRADOR  -> todo, tambien configuracion y usuarios
    COBRADOR       -> consultar clientes y cartera, registrar pagos.
                      NO toca configuracion, NO crea usuarios,
                      NO anula pagos, NO elimina creditos.
"""

import functools
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .models import PerfilUsuario, Rol

registrador = logging.getLogger("cartera")


def es_administrador(usuario):
    if usuario is None or not usuario.is_authenticated:
        return False
    if usuario.is_superuser:
        return True
    perfil = getattr(usuario, "perfil", None)
    return bool(perfil and perfil.rol == Rol.ADMINISTRADOR)


def es_cobrador(usuario):
    if usuario is None or not usuario.is_authenticated:
        return False
    if es_administrador(usuario):
        return True
    perfil = getattr(usuario, "perfil", None)
    return bool(perfil and perfil.rol == Rol.COBRADOR)


def requiere_administrador(funcion):
    """Solo el administrador pasa. A los cobradores los manda a su pagina."""
    @functools.wraps(funcion)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('entrar')}?siguiente={request.path}")
        if not es_administrador(request.user):
            messages.error(
                request,
                "Esa seccion es solo para administradores.",
            )
            return redirect("dashboard")
        return funcion(request, *args, **kwargs)
    return envoltura


def requiere_activo(funcion):
    """Un usuario desactivado no puede trabajar, aunque su clave este bien."""
    @functools.wraps(funcion)
    def envoltura(request, *args, **kwargs):
        if request.user.is_authenticated:
            perfil = getattr(request.user, "perfil", None)
            if perfil is not None and not perfil.activo:
                from django.contrib.auth import logout
                logout(request)
                messages.error(
                    request,
                    "Su usuario esta desactivado. Comuniquese con el administrador.",
                )
                return redirect("entrar")
        return funcion(request, *args, **kwargs)
    return envoltura
