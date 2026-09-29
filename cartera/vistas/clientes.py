"""
Modulo de CLIENTES: lista, ficha completa, edicion, activacion y las
fotos de la cedula.

La ficha del cliente es la pantalla mas importante: ahi se ve la barra de
regularidad, el resumen de dinero, los creditos y el historial de pagos.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from ..forms import ClienteForm, DocumentoClienteForm
from ..models import (
    Cliente, Credito, Cuota, DocumentoCliente, EstadoCredito, HistorialMovimiento,
    MetodoPago, Pago, Rol,
)
from ..permisos import es_administrador, requiere_activo, requiere_administrador
from ..servicios import cartera as servicio_cartera
from ..servicios import documentos as servicio_documentos
from ..servicios.documentos import ErrorDocumento
from ..servicios.regularidad import (
    calcular_regularidad, configuracion, estado_cliente, regularidad_de_lista,
)

registrador = logging.getLogger("cartera")


# ===========================================================================
# LISTA DE CLIENTES
# ===========================================================================


@requiere_activo
@login_required
def lista_clientes(request):
    """Todos los clientes, con busqueda, filtro y la barra de regularidad."""
    texto = (request.GET.get("q") or "").strip()
    estado = request.GET.get("estado") or "todos"
    orden = request.GET.get("orden") or "nombre"
    pagina = request.GET.get("pagina") or 1

    clientes = Cliente.objects.all().annotate(
        n_creditos=Count("creditos", distinct=True),
    )

    if texto:
        digitos = servicio_cartera.normalizar_cedula(texto)
        condicion = (
            Q(nombres__icontains=texto) | Q(apellidos__icontains=texto)
        )
        if digitos:
            condicion |= Q(cedula__icontains=digitos)
        else:
            for palabra in texto.split():
                condicion |= Q(nombres__icontains=palabra) | Q(apellidos__icontains=palabra)
        clientes = clientes.filter(condicion)

    if estado == "activos":
        clientes = clientes.filter(activo=True)
    elif estado == "inactivos":
        clientes = clientes.filter(activo=False)
    elif estado == "con_deuda":
        clientes = clientes.filter(creditos__estado=EstadoCredito.ACTIVO).distinct()
    elif estado == "al_dia":
        ids_al_dia = _ids_por_estado(estado_cliente_filtro="AL_DIA")
        clientes = clientes.filter(pk__in=ids_al_dia)
    elif estado == "atrasados":
        ids_atraso = _ids_por_estado(estado_cliente_filtro="ATRASADO")
        clientes = clientes.filter(pk__in=ids_atraso)

    if orden == "recientes":
        clientes = clientes.order_by("-fecha_creacion")
    elif orden == "deuda":
        clientes = clientes.order_by("-creditos__saldo")
    else:
        clientes = clientes.order_by("apellidos", "nombres")

    # Regularidad de toda la pagina visible, en una sola consulta.
    config = configuracion()
    total = clientes.count()
    paginador = Paginator(clientes, 25)
    pagina_obj = paginador.get_page(pagina)
    regulares = regularidad_de_lista(
        [c.id for c in pagina_obj.object_list], config,
    )

    filas = []
    for cliente in pagina_obj.object_list:
        regularidad = regulares.get(cliente.id) or calcular_regularidad(
            cliente=cliente, config=config)
        filas.append({
            "cliente": cliente,
            "regularidad": regularidad,
            "estado_cliente": estado_cliente(regularidad),
        })

    return render(request, "clientes/lista.html", {
        "filas": filas,
        "pagina_obj": pagina_obj,
        "paginador": paginador,
        "total": total,
        "q": texto,
        "estado": estado,
        "orden": orden,
    })


def _ids_por_estado(estado_cliente_filtro):
    """Ids de clientes que estan en un estado (al dia, atrasado...)."""
    config = configuracion()
    from django.utils import timezone
    ids = list(
        Cuota.objects.exclude(credito__estado=EstadoCredito.ANULADO)
        .values_list("credito__cliente_id", flat=True).distinct()
    )
    regulares = regularidad_de_lista(ids, config)
    return [
        cliente_id for cliente_id, reg in regulares.items()
        if estado_cliente(reg) == estado_cliente_filtro
    ]


# ===========================================================================
# FICHA DEL CLIENTE
# ===========================================================================


@requiere_activo
@login_required
def ficha_cliente(request, cliente_id):
    """La pantalla completa de un cliente."""
    cliente = get_object_or_404(
        Cliente.objects.prefetch_related("documentos"), pk=cliente_id,
    )

    config = configuracion()
    regularidad = calcular_regularidad(cliente=cliente, config=config)
    resumen = servicio_cartera.resumen_cliente(cliente.id)
    creditos = servicio_cartera.creditos_del_cliente(cliente.id)

    # Historial de pagos, con filtros.
    pagos = Pago.objects.filter(
        credito__cliente=cliente,
    ).select_related("credito", "metodo", "usuario").order_by("-fecha", "-hora", "-id")

    filtros = _filtros_historial(request.GET, creditos)
    pagos = _aplicar_filtros(pagos, filtros)

    from django.core.paginator import Paginator
    paginador = Paginator(pagos, 30)
    pagina_pagos = paginador.get_page(request.GET.get("ppagina") or 1)

    return render(request, "clientes/ficha.html", {
        "cliente": cliente,
        "regularidad": regularidad,
        "estado_cliente": estado_cliente(regularidad),
        "resumen": resumen,
        "creditos": creditos,
        "documentos": servicio_documentos.documentos_de(cliente),
        "pagos": pagina_pagos,
        "paginador": paginador,
        "filtros": filtros,
        "creditos_filtro": filtros["credito"],
        "metodos": MetodoPago.objects.all(),
        "movimientos": HistorialMovimiento.objects.filter(cliente=cliente)[:15],
    })


def _filtros_historial(GET, creditos):
    return {
        "desde": GET.get("desde") or "",
        "hasta": GET.get("hasta") or "",
        "credito": GET.get("credito") or "",
        "metodo": GET.get("metodo") or "",
        "estado": GET.get("estado") or "",
    }


def _aplicar_filtros(pagos, filtros):
    from datetime import datetime
    from ..models import MetodoPago

    if filtros["desde"]:
        try:
            pagos = pagos.filter(fecha__gte=datetime.strptime(
                filtros["desde"], "%Y-%m-%d").date())
        except ValueError:
            pass
    if filtros["hasta"]:
        try:
            pagos = pagos.filter(fecha__lte=datetime.strptime(
                filtros["hasta"], "%Y-%m-%d").date())
        except ValueError:
            pass
    if filtros["credito"]:
        pagos = pagos.filter(credito_id=filtros["credito"])
    if filtros["metodo"]:
        pagos = pagos.filter(metodo__id=filtros["metodo"])
    if filtros["estado"] == "vigentes":
        pagos = pagos.filter(anulado=False)
    elif filtros["estado"] == "anulados":
        pagos = pagos.filter(anulado=True)
    return pagos


# ===========================================================================
# CREAR Y EDITAR
# ===========================================================================


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def crear_cliente(request):
    """Formulario de nuevo cliente."""
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save(commit=False)
            cliente.creado_por = request.user
            cliente.save()
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.CLIENTE,
                descripcion=f"Creo el cliente {cliente.nombre_completo} "
                            f"(cedula {cliente.cedula})",
                cliente=cliente,
                datos={"cedula": cliente.cedula},
                direccion_ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, f"Cliente {cliente.nombre_completo} creado.")
            # Se puede ir directo a la cedula o a crear el credito.
            if request.POST.get("guardar_y_credito"):
                return redirect(f"{reverse_credito_nuevo()}?cliente={cliente.id}")
            return redirect("ficha_cliente", cliente_id=cliente.id)
    else:
        form = ClienteForm()
    return render(request, "clientes/formulario.html", {
        "form": form,
        "titulo": "Nuevo cliente",
        "accion": "crear",
    })


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def editar_cliente(request, cliente_id):
    """Editar los datos de un cliente."""
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    datos_antes = {
        "nombres": cliente.nombres, "apellidos": cliente.apellidos,
        "cedula": cliente.cedula, "telefono": cliente.telefono,
    }

    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            cambios = _comparar(datos_antes, {
                "nombres": form.cleaned_data["nombres"],
                "apellidos": form.cleaned_data["apellidos"],
                "cedula": form.cleaned_data["cedula"],
                "telefono": form.cleaned_data["telefono"],
            })
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.CLIENTE,
                descripcion=f"Edito los datos de {cliente.nombre_completo}",
                cliente=cliente,
                datos={"cambios": cambios} if cambios else {},
                direccion_ip=request.META.get("REMOTE_ADDR"),
            )
            messages.success(request, "Datos del cliente actualizados.")
            return redirect("ficha_cliente", cliente_id=cliente.id)
    else:
        form = ClienteForm(instance=cliente)

    return render(request, "clientes/formulario.html", {
        "form": form,
        "titulo": f"Editar a {cliente.nombre_completo}",
        "accion": "editar",
        "cliente": cliente,
    })


def _comparar(antes, despues):
    cambios = {}
    for campo, valor in despues.items():
        if antes.get(campo) != valor:
            cambios[campo] = {"antes": antes.get(campo), "despues": valor}
    return cambios


@requiere_activo
@login_required
@require_http_methods(["POST"])
def activar_cliente(request, cliente_id):
    """Activa o desactiva un cliente. NUNCA se borra."""
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    cliente.activo = not cliente.activo
    cliente.save(update_fields=["activo", "fecha_modificacion"])

    HistorialMovimiento.objects.create(
        usuario=request.user,
        tipo=HistorialMovimiento.Tipo.CLIENTE,
        descripcion=(
            f"Desactivo a {cliente.nombre_completo}. Sus creditos y pagos "
            f"se conservan."
            if not cliente.activo else
            f"Reactivo a {cliente.nombre_completo}"
        ),
        cliente=cliente,
        datos={"activo": cliente.activo},
    )
    if cliente.activo:
        messages.success(request, f"{cliente.nombre_completo} quedo activo.")
    else:
        messages.info(
            request,
            f"{cliente.nombre_completo} quedo inactivo. No aparecera en las "
            f"listas de cobranza, pero todo su historial sigue guardado.",
        )
    return redirect("ficha_cliente", cliente_id=cliente.id)


# ===========================================================================
# FOTOS DE LA CEDULA
# ===========================================================================


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def documentos_cliente(request, cliente_id):
    """Administrar las fotos de la cedula del cliente."""
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    if request.method == "POST":
        form = DocumentoClienteForm(request.POST, request.FILES, cliente=cliente)
        if form.is_valid():
            try:
                servicio_documentos.guardar_documento(
                    cliente=cliente,
                    tipo=form.cleaned_data["tipo"],
                    archivo=form.cleaned_data["archivo"],
                    usuario=request.user,
                )
                messages.success(request, "Foto de la cedula guardada.")
                return redirect("documentos_cliente", cliente_id=cliente.id)
            except ErrorDocumento as error:
                form.add_error("archivo", str(error))
    else:
        form = DocumentoClienteForm(cliente=cliente)

    return render(request, "clientes/documentos.html", {
        "cliente": cliente,
        "form": form,
        "documentos": servicio_documentos.documentos_de(cliente),
        "tiene": cliente.documentos.count(),
    })


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def eliminar_documento(request, documento_id):
    """Borra una foto mal subida. Solo el administrador."""
    documento = get_object_or_404(DocumentoCliente, pk=documento_id)
    cliente = documento.cliente
    servicio_documentos.eliminar_documento(documento, request.user)
    messages.success(request, "Foto eliminada.")
    return redirect("documentos_cliente", cliente_id=cliente.id)


@requiere_activo
@login_required
def ver_documento(request, documento_id):
    """Entrega la foto de la cedula SOLO a usuarios conectados.

    Esta es la unica forma de verlas. No hay URL publica: sin sesion
    iniciada, esta vista no entrega nada.
    """
    documento = get_object_or_404(
        DocumentoCliente.objects.select_related("cliente"), pk=documento_id,
    )

    try:
        archivo = documento.archivo.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("La foto no esta en el disco. Puede haberse borrado.")

    respuesta = FileResponse(
        archivo, content_type="application/octet-stream",
    )
    # Cabeceras de proteccion: la foto no se puede embeber en otra pagina
    # ni guardar en una cache compartida.
    respuesta["Content-Disposition"] = f'inline; filename="cedula-{documento.id}.jpg"'
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store, max-age=0"
    respuesta["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return respuesta


def reverse_credito_nuevo():
    from django.urls import reverse
    return reverse("nuevo_credito")
