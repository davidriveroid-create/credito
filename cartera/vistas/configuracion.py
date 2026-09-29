"""
Configuracion del sistema, usuarios y respaldos.
"""

import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..forms import (
    ConfiguracionForm, FrecuenciaPagoForm, MetodoPagoForm, UsuarioForm,
)
from ..models import (
    Credito, Cliente, Configuracion, FrecuenciaPago, HistorialMovimiento,
    MetodoPago, Pago, PerfilUsuario, Rol,
)
from ..permisos import requiere_activo, requiere_administrador
from ..servicios import respaldo as servicio_respaldo
from ..servicios.regularidad import configuracion as obtener_configuracion

registrador = logging.getLogger("cartera")


# ===========================================================================
# CONFIGURACION GENERAL
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
def ajustes(request):
    """Datos del negocio y parametros de la barra de regularidad."""
    config = obtener_configuracion()

    # Vista previa de como quedaria la barra con los parametros de ahora.
    from ..servicios.regularidad import _barra_texto
    previa = [
        {"etiqueta": "EXCELENTE desde", "porcentaje": config.umbral_excelente,
         "barra": _barra_texto(config.umbral_excelente), "color": "#16a34a"},
        {"etiqueta": "BUENO desde", "porcentaje": config.umbral_bueno,
         "barra": _barra_texto(config.umbral_bueno), "color": "#65a30d"},
        {"etiqueta": "IRREGULAR desde", "porcentaje": max(0, config.umbral_bueno - 20),
         "barra": _barra_texto(max(0, config.umbral_bueno - 20)), "color": "#eab308"},
        {"etiqueta": f"ATRASADO (0 a {config.dias_para_moroso} dias)", "porcentaje": 40,
         "barra": _barra_texto(40), "color": "#f97316"},
        {"etiqueta": f"MOROSO (mas de {config.dias_para_moroso} dias)", "porcentaje": 25,
         "barra": _barra_texto(25), "color": "#dc2626"},
    ]

    return render(request, "configuracion/ajustes.html", {
        "config": config,
        "previa": previa,
        "catalogos": {
            "frecuencias": FrecuenciaPago.objects.all(),
            "metodos": MetodoPago.objects.all(),
        },
        "usuarios": User.objects.select_related("perfil").order_by(
            "-is_active", "username"),
    })


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def guardar_ajustes(request):
    config = obtener_configuracion()
    antes = {
        "nombre_negocio": config.nombre_negocio,
        "umbral_excelente": config.umbral_excelente,
        "umbral_bueno": config.umbral_bueno,
        "dias_para_moroso": config.dias_para_moroso,
        "dias_gracia": config.dias_gracia,
    }

    form = ConfiguracionForm(request.POST, request.FILES, instance=config)
    if form.is_valid():
        form.save()
        despues = {
            "nombre_negocio": form.cleaned_data["nombre_negocio"],
            "umbral_excelente": form.cleaned_data["umbral_excelente"],
            "umbral_bueno": form.cleaned_data["umbral_bueno"],
            "dias_para_moroso": form.cleaned_data["dias_para_moroso"],
            "dias_gracia": form.cleaned_data["dias_gracia"],
        }
        cambios = {k: {"antes": antes[k], "despues": v}
                   for k, v in despues.items() if antes[k] != v}

        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.CONFIGURACION,
            descripcion="Actualizo la configuracion del sistema",
            datos={"cambios": cambios} if cambios else {},
        )
        if cambios:
            messages.success(
                request,
                "Configuracion guardada. Los cambios de regularidad ya "
                "aplican a todos los clientes.",
            )
        else:
            messages.success(request, "Configuracion guardada.")
        return redirect("ajustes")

    mensajes = "; ".join(
        f"{campo}: {' '.join(err)}" for campo, err in form.errors.items()
    )
    messages.error(request, f"No se pudo guardar. {mensajes}")
    return redirect("ajustes")


# ===========================================================================
# FRECUENCIAS Y METODOS DE PAGO
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def guardar_frecuencia(request):
    id_frecuencia = request.POST.get("id")
    if id_frecuencia:
        frecuencia = get_object_or_404(FrecuenciaPago, pk=id_frecuencia)
    else:
        frecuencia = FrecuenciaPago()

    form = FrecuenciaPagoForm(request.POST, instance=frecuencia)
    if form.is_valid():
        form.save()
        messages.success(request, f"Frecuencia '{form.cleaned_data['nombre']}' guardada.")
    else:
        messages.error(
            request,
            "No se pudo guardar la frecuencia: " +
            " ".join(sum(form.errors.values(), [])),
        )
    return redirect("ajustes")


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def guardar_metodo_pago(request):
    id_metodo = request.POST.get("id")
    if id_metodo:
        metodo = get_object_or_404(MetodoPago, pk=id_metodo)
    else:
        metodo = MetodoPago()

    form = MetodoPagoForm(request.POST, instance=metodo)
    if form.is_valid():
        form.save()
        messages.success(request, f"Metodo de pago '{form.cleaned_data['nombre']}' guardado.")
    else:
        messages.error(
            request,
            "No se pudo guardar el metodo de pago: " +
            " ".join(sum(form.errors.values(), [])),
        )
    return redirect("ajustes")


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def eliminar_catalogo(request, tipo, objeto_id):
    """Desactiva un catalogo. No se borra si ya se uso en creditos."""
    if tipo == "frecuencia":
        objeto = get_object_or_404(FrecuenciaPago, pk=objeto_id)
        usados = Credito.objects.filter(frecuencia=objeto).count()
    elif tipo == "metodo":
        objeto = get_object_or_404(MetodoPago, pk=objeto_id)
        usados = Pago.objects.filter(metodo=objeto).count()
    else:
        messages.error(request, "Tipo de catalogo desconocido.")
        return redirect("ajustes")

    if usados > 0:
        objeto.activo = False
        objeto.save(update_fields=["activo"])
        messages.info(
            request,
            f"'{objeto}' se desactivo porque ya se uso en {usados} "
            f"registro(s). Los datos antigos no se tocan; solo deja de "
            f"aparecer en las listas nuevas.",
        )
    else:
        nombre = str(objeto)
        objeto.delete()
        messages.success(request, f"'{nombre}' se elimino (no se habia usado).")
    return redirect("ajustes")


# ===========================================================================
# USUARIOS
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
def usuarios(request):
    """Lista y creacion de usuarios."""
    texto = (request.GET.get("q") or "").strip()
    usuarios_qs = User.objects.select_related("perfil").order_by(
        "-is_active", "username")

    if texto:
        usuarios_qs = usuarios_qs.filter(
            Q(username__icontains=texto)
            | Q(first_name__icontains=texto)
            | Q(last_name__icontains=texto),
        )

    paginador = Paginator(usuarios_qs, 25)
    pagina_obj = paginador.get_page(request.GET.get("pagina") or 1)

    return render(request, "configuracion/usuarios.html", {
        "usuarios": pagina_obj,
        "paginador": paginador,
        "form": UsuarioForm(),
        "q": texto,
        "roles": Rol.choices,
    })


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def crear_usuario(request):
    form = UsuarioForm(request.POST)
    if not form.is_valid():
        for campo, errores in form.errors.items():
            for error in errores:
                messages.error(request, f"{campo}: {error}")
        return redirect("usuarios")

    datos = form.cleaned_data
    usuario = User.objects.create_user(
        username=datos["usuario"],
        password=datos["clave"],
        first_name=datos["nombre"].split(" ")[0] if datos["nombre"] else "",
        last_name=" ".join(datos["nombre"].split(" ")[1:]) if datos["nombre"] else "",
        email="",
        is_staff=(datos["rol"] == Rol.ADMINISTRADOR),
    )
    PerfilUsuario.objects.create(
        usuario=usuario,
        rol=datos["rol"],
        telefono=datos.get("telefono", ""),
        activo=datos.get("activo", True),
    )

    HistorialMovimiento.objects.create(
        usuario=request.user,
        tipo=HistorialMovimiento.Tipo.USUARIO,
        descripcion=(
            f"Creo el usuario '{usuario.get_username()}' "
            f"({datos['rol']})"
        ),
        datos={"rol": datos["rol"]},
    )
    messages.success(request, f"Usuario '{usuario.get_username()}' creado.")
    return redirect("usuarios")


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def editar_usuario(request, usuario_id):
    usuario = get_object_or_404(User, pk=usuario_id)
    perfil, _ = PerfilUsuario.objects.get_or_create(usuario=usuario)

    accion = request.POST.get("accion")

    if accion == "activar":
        activo = request.POST.get("activo") == "1"
        # No se puede desactivar al propio administrador: dejaria el
        # sistema sin acceso.
        if usuario == request.user and not activo:
            messages.error(request, "No se puede desactivar su propio usuario.")
            return redirect("usuarios")
        perfil.activo = activo
        perfil.save(update_fields=["activo"])
        usuario.is_active = activo
        usuario.save(update_fields=["is_active"])
        accion_texto = "activo" if activo else "desactivado"
        messages.success(request, f"Usuario '{usuario.get_username()}' {accion_texto}.")
        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.USUARIO,
            descripcion=f"{accion_texto.capitalize()} al usuario '{usuario.get_username()}'",
        )
        return redirect("usuarios")

    if accion == "rol":
        nuevo_rol = request.POST.get("rol")
        if nuevo_rol not in dict(Rol.choices):
            messages.error(request, "Ese rol no existe.")
            return redirect("usuarios")
        if usuario == request.user and nuevo_rol != Rol.ADMINISTRADOR:
            messages.error(request, "No se puede quitarle a si mismo el rol de administrador.")
            return redirect("usuarios")
        perfil.rol = nuevo_rol
        perfil.save(update_fields=["rol"])
        usuario.is_staff = (nuevo_rol == Rol.ADMINISTRADOR)
        usuario.save(update_fields=["is_staff"])
        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.USUARIO,
            descripcion=(
                f"Cambio el rol de '{usuario.get_username()}' a "
                f"{dict(Rol.choices)[nuevo_rol]}"
            ),
            datos={"rol": nuevo_rol},
        )
        messages.success(request, "Rol actualizado.")
        return redirect("usuarios")

    if accion == "clave":
        clave = request.POST.get("clave") or ""
        if len(clave) < 6:
            messages.error(request, "La contrasena debe tener al menos 6 caracteres.")
            return redirect("usuarios")
        if clave.isdigit():
            messages.error(request, "La contrasena no puede ser solo numeros.")
            return redirect("usuarios")
        usuario.set_password(clave)
        usuario.save()
        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.USUARIO,
            descripcion=f"Cambio la contrasena de '{usuario.get_username()}'",
        )
        messages.success(
            request,
            f"Contrasena de '{usuario.get_username()}' cambiada.",
        )
        return redirect("usuarios")

    return redirect("usuarios")


# ===========================================================================
# RESPALDOS
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
def respaldos(request):
    """Pantalla de copias de seguridad."""
    lista = servicio_respaldo.listar_respaldos()
    database = None
    try:
        from django.db import connection
        database = connection.settings_dict["NAME"]
    except Exception:
        pass

    return render(request, "configuracion/respaldos.html", {
        "respaldos": lista,
        "database": database,
        "total_datos": {
            "clientes": Cliente.objects.count(),
            "creditos": Credito.objects.count(),
            "pagos": Pago.objects.filter(anulado=False).count(),
        },
    })


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def crear_respaldo(request):
    try:
        resultado = servicio_respaldo.crear_respaldo(usuario=request.user)
    except Exception as error:
        registrador.exception("Error creando respaldo: %s", error)
        messages.error(
            request,
            f"No se pudo hacer el respaldo: {error}. "
            f"Intente de nuevo en un momento.",
        )
        return redirect("respaldos")

    mensajes = [
        f"Respaldo creado: {resultado['nombre']}",
        f"{resultado['tamaño'] / 1024 / 1024:.2f} MB",
        f"{resultado['clientes']} clientes, {resultado['creditos']} creditos, "
        f"{resultado['pagos']} pagos",
    ]
    messages.success(request, " | ".join(mensajes))
    return redirect("respaldos")


@requiere_activo
@login_required
@requiere_administrador
def descargar_respaldo(request, nombre):
    """Descarga un respaldo concreto."""
    from django.http import FileResponse
    from django.utils.http import urlquote
    import os

    carpeta = servicio_respaldo.carpeta_respaldos()
    # Nunca se permite bajar nada fuera de la carpeta de respaldos.
    archivo = (carpeta / os.path.basename(nombre)).resolve()
    if not str(archivo).startswith(str(carpeta.resolve())):
        messages.error(request, "Archivo no valido.")
        return redirect("respaldos")
    if not archivo.exists():
        messages.error(request, "Ese respaldo ya no existe.")
        return redirect("respaldos")

    respuesta = FileResponse(
        archivo.open("rb"), as_attachment=True,
        filename=archivo.name,
    )
    return respuesta


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def restaurar_respaldo(request, nombre):
    """Restaura un respaldo. Antes guarda copia del estado actual."""
    import os
    from django.http import HttpResponseRedirect

    carpeta = servicio_respaldo.carpeta_respaldos()
    archivo = (carpeta / os.path.basename(nombre)).resolve()
    if not str(archivo).startswith(str(carpeta.resolve())) or not archivo.exists():
        messages.error(request, "Ese respaldo no existe.")
        return redirect("respaldos")

    if request.POST.get("confirmar") != "SI":
        messages.warning(
            request,
            "Para restaurar debe confirmar. Primero se guardara una copia de "
            "los datos actuales por si necesita volver atras.",
        )
        return redirect("respaldos")

    try:
        seguro = servicio_respaldo.restaurar_respaldo(archivo, usuario=request.user)
    except Exception as error:
        registrador.exception("Error restaurando respaldo: %s", error)
        messages.error(
            request,
            f"No se pudo restaurar: {error}. Los datos actuales siguen como estaban.",
        )
        return redirect("respaldos")

    messages.success(
        request,
        f"Datos restaurados desde {archivo.name}. "
        f"Se guardo antes una copia de seguridad ({seguro['nombre']}) "
        f"por si necesita volver atras. Vuelva a entrar al sistema.",
    )
    from django.contrib.auth import logout
    logout(request)
    return HttpResponseRedirect("/")


# ===========================================================================
# HISTORIAL DE MOVIMIENTOS
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
def historial(request):
    """Auditoria: quien hizo que y cuando."""
    tipo = request.GET.get("tipo") or ""
    usuario_id = request.GET.get("usuario") or ""
    texto = (request.GET.get("q") or "").strip()
    pagina = request.GET.get("pagina") or 1

    movimientos = HistorialMovimiento.objects.select_related(
        "usuario", "cliente", "credito")

    if tipo:
        movimientos = movimientos.filter(tipo=tipo)
    if usuario_id and usuario_id.isdigit():
        movimientos = movimientos.filter(usuario_id=int(usuario_id))
    if texto:
        movimientos = movimientos.filter(
            Q(descripcion__icontains=texto) | Q(cliente__nombres__icontains=texto),
        )

    paginador = Paginator(movimientos, 50)
    pagina_obj = paginador.get_page(pagina)

    return render(request, "configuracion/historial.html", {
        "movimientos": pagina_obj,
        "paginador": paginador,
        "tipos": HistorialMovimiento.Tipo.choices,
        "usuarios": User.objects.filter(perfil__isnull=False).order_by("username"),
        "tipo": tipo,
        "usuario_id": usuario_id,
        "q": texto,
    })
