"""
Inicio de sesion, cierre de sesion y cambio de contrasena.

Se protege el acceso con:
--limiting de intentos: despues de 5 intentos fallidos la cuenta se
  bloquea 10 minutos, para que nadie pueda adivinar la clave probando.
- Mensajes claros sin decir si el usuario existe o no.
"""

import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..forms import CambiarClaveForm
from ..models import HistorialMovimiento, PerfilUsuario, Rol
from ..permisos import requiere_administrador, requiere_activo

registrador = logging.getLogger("cartera.seguridad")

NOMBRE_INTENTOS = "intentos_"


def _clave_intentos(username):
    return f"{NOMBRE_INTENTOS}{username}"


def _registrar_intento(username, ok):
    """Lleva la cuenta de intentos fallidos por usuario."""
    clave = _clave_intentos(username)
    if ok:
        cache.delete(clave)
        return 0
    intentos = cache.get(clave, 0) + 1
    cache.set(clave, intentos, 60 * 60 * 2)
    return intentos


def _esta_bloqueado(username, max_intentos, minutos_bloqueo):
    from django.conf import settings
    clave = _clave_intentos(username)
    intentos = cache.get(clave, 0)
    if intentos < max_intentos:
        return False, intentos
    # El bloqueo dura el tiempo del cache. Si ya paso, se limpia.
    if cache.get(f"{clave}_bloqueado"):
        return True, intentos
    cache.set(f"{clave}_bloqueado", True, minutos_bloqueo * 60)
    return True, intentos


@requiere_activo
@require_http_methods(["GET", "POST"])
def entrar(request):
    """Pantalla de inicio de sesion."""
    from django.conf import settings

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        usuario = (request.POST.get("usuario") or "").strip().lower()
        clave = request.POST.get("clave") or ""
        siguiente = request.POST.get("siguiente") or ""

        bloqueado, intentos = _esta_bloqueado(
            usuario, settings.NUMERO_INTENTOS_LOGIN, settings.BLOQUEO_MINUTOS,
        )
        if bloqueado:
            messages.error(
                request,
                f"Demasiados intentos fallidos. Espere "
                f"{settings.BLOQUEO_MINUTOS} minutos e intente de nuevo.",
            )
            return render(request, "acceso/entrar.html", {
                "usuario": usuario,
                "siguiente": siguiente,
            }, status=429)

        correcto = authenticate(username=usuario, password=clave)
        # Mismo mensaje exista o no el usuario: no se revela quien tiene cuenta.
        if correcto is None:
            intentos = _registrar_intento(usuario, ok=False)
            faltantes = max(0, settings.NUMERO_INTENTOS_LOGIN - intentos)
            registrador.warning(
                "Intento de acceso fallido para '%s' (intento %s de %s).",
                usuario, intentos, settings.NUMERO_INTENTOS_LOGIN,
            )
            if faltantes <= 2:
                mensaje = (
                    f"Usuario o contrasena incorrectos. "
                    f"Le quedan {faltantes} intento(s)."
                )
            else:
                mensaje = "Usuario o contrasena incorrectos."
            messages.error(request, mensaje)
            return render(request, "acceso/entrar.html", {
                "usuario": usuario,
                "siguiente": siguiente,
            }, status=401)

        _registrar_intento(usuario, ok=True)

        # El perfil se crea solo la primera vez.
        perfil = PerfilUsuario.objects.filter(usuario=correcto).first()
        if perfil is None:
            perfil = PerfilUsuario.objects.create(
                usuario=correcto,
                rol=Rol.ADMINISTRADOR if correcto.is_superuser else Rol.COBRADOR,
            )
        if not perfil.activo and not correcto.is_superuser:
            messages.error(
                request,
                "Su usuario esta desactivado. Comuniquese con el administrador.",
            )
            return redirect("entrar")

        login(request, correcto)
        request.session["ingreso_registrado"] = True
        HistorialMovimiento.objects.create(
            usuario=correcto,
            tipo=HistorialMovimiento.Tipo.INGRESO,
            descripcion=f"{correcto.get_username()} ingreso al sistema",
            direccion_ip=request.META.get("REMOTE_ADDR"),
        )
        messages.success(
            request,
            f"Bienvenido, {correcto.first_name or correcto.get_username()}.",
        )

        # Solo se permite redirigir a paginas internas.
        if siguiente and siguiente.startswith("/") and not siguiente.startswith("//"):
            return redirect(siguiente)
        return redirect("dashboard")

    return render(request, "acceso/entrar.html", {
        "siguiente": request.GET.get("siguiente", ""),
    })


@require_http_methods(["GET", "POST"])
def salir(request):
    """Cierra la sesion."""
    if request.user.is_authenticated:
        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.INGRESO,
            descripcion=f"{request.user.get_username()} salio del sistema",
            direccion_ip=request.META.get("REMOTE_ADDR"),
        )
    logout(request)
    request.session.flush()
    messages.info(request, "Sesion cerrada correctamente.")
    return redirect("entrar")


@requiere_activo
@require_http_methods(["GET", "POST"])
def cambiar_clave(request):
    """El usuario cambia su propia contrasena."""
    if request.method == "POST":
        form = CambiarClaveForm(request.POST, usuario=request.user)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["nueva"])
            request.user.save()
            update_session_auth_hash(request, request.user)
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.USUARIO,
                descripcion=f"{request.user.get_username()} cambio su contrasena",
            )
            messages.success(request, "Contrasena cambiada correctamente.")
            return redirect("dashboard")
    else:
        form = CambiarClaveForm(usuario=request.user)

    return render(request, "acceso/cambiar_clave.html", {"form": form})
