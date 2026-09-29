"""
Modulo de CREDITOS: registrar la venta a credito, generar el plan de
cuotas y ver el detalle de un credito.
"""

import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..forms import CreditoForm, EditarCreditoForm
from ..models import (
    CERO, Cliente, Credito, Cuota, EstadoCredito, EstadoCuota, HistorialMovimiento,
    Pago, Producto, pesada,
)
from ..permisos import requiere_activo, requiere_administrador
from ..servicios import cartera as servicio_cartera
from ..servicios.calendario import ErrorCalculo, generar_plan_pagos
from ..servicios.cuotas import (
    crear_plan_credito, eliminar_credito_si_sin_pagos,
    cuota_siguiente, fecha_estimada_fin, recalcular_credito,
)
from ..servicios.regularidad import calcular_regularidad, configuracion
from ..servicios.dinero import formato_dinero

registrador = logging.getLogger("cartera")


# ===========================================================================
# LISTA DE CREDITOS
# ===========================================================================


@requiere_activo
@login_required
def lista_creditos(request):
    """Todos los creditos, con filtros por estado y cliente."""
    texto = (request.GET.get("q") or "").strip()
    estado = request.GET.get("estado") or "todos"
    solo_activos = request.GET.get("activos") == "1"
    pagina = request.GET.get("pagina") or 1

    creditos = Credito.objects.select_related("cliente", "frecuencia", "producto")

    if texto:
        condicion = (
            Q(cliente__nombres__icontains=texto)
            | Q(cliente__apellidos__icontains=texto)
            | Q(producto_texto__icontains=texto)
            | Q(id=texto if texto.isdigit() else 0)
        )
        digitos = servicio_cartera.normalizar_cedula(texto)
        if digitos:
            condicion |= Q(cliente__cedula__icontains=digitos)
        creditos = creditos.filter(condicion)

    if solo_activos:
        creditos = creditos.filter(estado=EstadoCredito.ACTIVO)
    elif estado == "activos":
        creditos = creditos.filter(estado=EstadoCredito.ACTIVO)
    elif estado == "pagados":
        creditos = creditos.filter(estado=EstadoCredito.PAGADO)
    elif estado == "anulados":
        creditos = creditos.filter(estado=EstadoCredito.ANULADO)
    elif estado == "vencidos":
        creditos = creditos.filter(estado=EstadoCredito.ACTIVO, cuotas_vencidas__gt=0)

    creditos = creditos.order_by("-fecha_venta", "-id")

    total = creditos.count()
    paginador = Paginator(creditos, 25)
    pagina_obj = paginador.get_page(pagina)

    return render(request, "creditos/lista.html", {
        "creditos": pagina_obj,
        "paginador": paginador,
        "total": total,
        "q": texto,
        "estado": estado,
        "activos": solo_activos,
        "hoy": timezone.localdate(),
    })


# ===========================================================================
# CREAR UN CREDITO
# ===========================================================================


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def nuevo_credito(request):
    """Formulario de venta a credito.

    Al guardar, se genera el plan de cuotas completo de una sola vez.
    """
    cliente_id = request.GET.get("cliente") or request.POST.get("cliente")
    cliente_fijo = None
    if cliente_id and str(cliente_id).isdigit():
        cliente_fijo = Cliente.objects.filter(pk=cliente_id).first()

    if request.method == "POST":
        form = CreditoForm(request.POST, usuario=request.user)
        if form.is_valid():
            from django.db import transaction

            # El credito y su plan de cuotas se guardan juntos: si la
            # generacion de cuotas falla, no queda un credito a medias.
            try:
                with transaction.atomic():
                    credito = form.save(commit=False)
                    credito.creado_por = request.user
                    credito.estado = EstadoCredito.ACTIVO
                    credito.save()
                    cuotas = crear_plan_credito(credito)
            except ErrorCalculo as error:
                messages.error(request, f"No se pudo crear el credito: {error}")
                return redirect("nuevo_credito")
            except Exception as error:
                registrador.exception("Error creando el credito: %s", error)
                messages.error(
                    request,
                    "Ocurrio un problema guardando el credito. No se guardo "
                    "nada: puede intentarlo de nuevo.",
                )
                return redirect("nuevo_credito")

            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.CREDITO,
                descripcion=(
                    f"Creo el credito #{credito.id} de {credito.cliente.nombre_completo}: "
                    f"{credito.nombre_producto}, {formato_dinero(credito.valor_financiado)} "
                    f"en {credito.numero_cuotas} cuotas de "
                    f"{credito.frecuencia.nombre.lower()}"
                ),
                cliente=credito.cliente,
                credito=credito,
                datos={
                    "valor_financiado": str(credito.valor_financiado),
                    "cuotas": credito.numero_cuotas,
                    "valor_cuota": str(credito.valor_cuota),
                },
            )
            messages.success(
                request,
                f"Credito creado. Se generaron {len(cuotas)} cuotas de "
                f"{formato_dinero(credito.valor_cuota)}.",
            )
            return redirect("ficha_credito", credito_id=credito.id)
    else:
        form = CreditoForm()
        if cliente_fijo:
            form.initial["cliente"] = cliente_fijo
            form.initial["precio_contado"] = _precio_de_producto(cliente_fijo)

    return render(request, "creditos/formulario.html", {
        "form": form,
        "cliente_fijo": cliente_fijo,
        "preview": getattr(form, "datos_preview", None),
    })


def _precio_de_producto(cliente):
    return 0


@requiere_activo
@login_required
def calcular_plan(request):
    """Previsualiza el plan de pagos mientras el usuario digita.

    Es lo que permite ver 'le quedaria pagando $50.000 x 36 cuotas' sin
    guardar nada.
    """
    import json
    from decimal import Decimal

    from django.db.models import F, Q
    from django.http import JsonResponse

    from ..models import FrecuenciaPago

    try:
        precio_financiado = int(request.GET.get("precio_financiado") or 0)
        cuota_inicial = int(request.GET.get("cuota_inicial") or 0)
        numero_cuotas = int(request.GET.get("numero_cuotas") or 0)
        valor_cuota_manual = request.GET.get("valor_cuota") or None
        frecuencia_id = request.GET.get("frecuencia")
        primera = request.GET.get("fecha_primera_cuota")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Datos incompletos."}, status=400)

    frecuencia = FrecuenciaPago.objects.filter(pk=frecuencia_id).first()
    if not frecuencia or numero_cuotas < 1 or precio_financiado <= 0:
        return JsonResponse({"error": "Complete los datos del credito."}, status=400)

    try:
        fecha_primera = date.fromisoformat(primera) if primera else timezone.localdate()
    except ValueError:
        return JsonResponse({"error": "Fecha invalida."}, status=400)

    saldo = pesada(Decimal(precio_financiado - cuota_inicial))
    if saldo <= 0:
        return JsonResponse({
            "error": "El saldo a financiar debe ser mayor que cero.",
        }, status=400)

    from ..servicios.calendario import generar_plan_pagos

    try:
        plan, valor_base, valor_ultima = generar_plan_pagos(
            saldo_financiado=saldo,
            numero_cuotas=numero_cuotas,
            fecha_primera=fecha_primera,
            frecuencia=frecuencia,
            valor_cuota_manual=pesada(Decimal(valor_cuota_manual)) if valor_cuota_manual else None,
        )
    except ErrorCalculo as error:
        return JsonResponse({"error": str(error)}, status=400)

    return JsonResponse({
        "ok": True,
        "valor_cuota": str(valor_base),
        "valor_ultima": str(valor_ultima),
        "saldo": str(saldo),
        "total": str(sum(p["valor"] for p in plan)),
        "cantidad": len(plan),
        "primera": plan[0]["fecha"].isoformat(),
        "ultima": plan[-1]["fecha"].isoformat(),
        "frecuencia": frecuencia.nombre,
        "muestra": [
            {
                "numero": p["numero"],
                "fecha": p["fecha"].isoformat(),
                "valor": str(p["valor"]),
            }
            for p in plan[:6]
        ],
    })


# ===========================================================================
# FICHA DEL CREDITO
# ===========================================================================


@requiere_activo
@login_required
def ficha_credito(request, credito_id):
    """Detalle completo de un credito con su plan de cuotas."""
    credito = get_object_or_404(
        Credito.objects.select_related("cliente", "frecuencia", "producto", "creado_por"),
        pk=credito_id,
    )

    hoy = timezone.localdate()
    cuotas = list(credito.cuotas.order_by("numero"))
    siguiente = cuota_siguiente(credito)

    conteo = {estado: 0 for estado in EstadoCuota.values}
    for cuota in cuotas:
        conteo[cuota.estado_real(hoy)] += 1

    pagos = (
        credito.pagos.select_related("metodo", "usuario")
        .order_by("-fecha", "-hora", "-id")
    )
    pagos_no_anulados = pagos.filter(anulado=False)

    regularidad = calcular_regularidad(credito=credito)

    progreso = 0
    if credito.valor_financiado > 0:
        progreso = int((credito.total_pagado / credito.valor_financiado) * 100)
        progreso = max(0, min(100, progreso))

    # Las cuatro filas de estado con su color, para la plantilla.
    conteo_filas = [
        ("PAGADA", "Pagada", "verde"),
        ("PARCIAL", "Parcial", "amarillo"),
        ("VENCIDA", "Vencida", "rojo"),
        ("PENDIENTE", "Pendiente", "azul"),
    ]
    pendientes = credito.numero_cuotas - credito.cuotas_pagadas

    return render(request, "creditos/ficha.html", {
        "credito": credito,
        "cliente": credito.cliente,
        "cuotas": cuotas,
        "conteo": conteo,
        "conteo_filas": conteo_filas,
        "pendientes": pendientes,
        "siguiente": siguiente,
        "pagos": pagos,
        "cantidad_pagos": pagos_no_anulados.count(),
        "regularidad": regularidad,
        "progreso": progreso,
        "hoy": hoy,
        "puede_pagar": credito.estado == EstadoCredito.ACTIVO and credito.saldo > 0,
        "historial": HistorialMovimiento.objects.filter(credito=credito)[:15],
    })


# ===========================================================================
# EDITAR
# ===========================================================================


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def editar_credito(request, credito_id):
    """Editar los datos que si se pueden cambiar de un credito."""
    credito = get_object_or_404(Credito, pk=credito_id)
    antes = {
        "precio_contado": str(credito.precio_contado),
        "precio_financiado": str(credito.precio_financiado),
        "producto_texto": credito.producto_texto,
    }

    if request.method == "POST":
        form = EditarCreditoForm(request.POST, instance=credito)
        if form.is_valid():
            form.save()
            cambios = {}
            if antes["precio_contado"] != str(form.cleaned_data["precio_contado"]):
                cambios["precio_contado"] = {
                    "antes": antes["precio_contado"],
                    "despues": str(form.cleaned_data["precio_contado"]),
                }
            if antes["precio_financiado"] != str(form.cleaned_data["precio_financiado"]):
                cambios["precio_financiado"] = {
                    "antes": antes["precio_financiado"],
                    "despues": str(form.cleaned_data["precio_financiado"]),
                }
            credito = recalcular_credito(credito)
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.CREDITO,
                descripcion=f"Edito el credito #{credito.id}",
                cliente=credito.cliente,
                credito=credito,
                datos={"cambios": cambios},
            )
            messages.success(request, "Credito actualizado.")
            return redirect("ficha_credito", credito_id=credito.id)
    else:
        form = EditarCreditoForm(instance=credito)

    return render(request, "creditos/editar.html", {
        "form": form,
        "credito": credito,
        "cliente": credito.cliente,
    })


# ===========================================================================
# ANULAR
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["POST"])
def anular_credito(request, credito_id):
    """Anula un credito mal creado.

    Con pagos NO se borra: se anula y el historial queda. Sin pagos, se
    puede borrar porque no hay informacion financiera perdida.
    """
    credito = get_object_or_404(Credito, pk=credito_id)

    if credito.estado == EstadoCredito.ANULADO:
        messages.warning(request, "Este credito ya estaba anulado.")
        return redirect("ficha_credito", credito_id=credito.id)

    if credito.pagos.exists():
        credito.estado = EstadoCredito.ANULADO
        credito.save(update_fields=["estado", "fecha_modificacion"])
        HistorialMovimiento.objects.create(
            usuario=request.user,
            tipo=HistorialMovimiento.Tipo.CREDITO,
            descripcion=(
                f"ANULO el credito #{credito.id} de {credito.cliente.nombre_completo}. "
                f"El historial de {credito.pagos.count()} pago(s) se conserva intacto."
            ),
            cliente=credito.cliente,
            credito=credito,
            datos={"motivo": request.POST.get("motivo", "")},
        )
        messages.info(
            request,
            f"Credito anulado. Sus {credito.pagos.count()} pago(s) siguen en "
            f"el historial; nada se borro.",
        )
    else:
        nombre = credito.nombre_producto
        credito_id = credito.id
        cliente_id = credito.cliente_id
        if eliminar_credito_si_sin_pagos(credito):
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.CREDITO,
                descripcion=f"Elimino el credito #{credito_id} ({nombre}). "
                            f"No tenia pagos registrados.",
                cliente_id=cliente_id,
                datos={"motivo": request.POST.get("motivo", "")},
            )
            messages.info(
                request,
                "Credito eliminado. No tenia pagos, asi que no se perdio nada.",
            )
            return redirect("ficha_cliente", cliente_id=cliente_id)

    return redirect("ficha_credito", credito_id=credito.id)


# ===========================================================================
# CATALOGO DE PRODUCTOS
# ===========================================================================


@requiere_activo
@login_required
def productos(request):
    """Catalogo de productos que se venden a credito."""
    texto = (request.GET.get("q") or "").strip()
    productos_qs = Producto.objects.all().annotate(
        n_ventas=Count("creditos"),
    )
    if texto:
        productos_qs = productos_qs.filter(
            Q(nombre__icontains=texto) | Q(marca__icontains=texto)
            | Q(modelo__icontains=texto),
        )
    return render(request, "creditos/productos.html", {
        "productos": productos_qs.order_by("nombre"),
        "q": texto,
    })


@requiere_activo
@login_required
@require_http_methods(["POST"])
def crear_producto(request):
    from ..forms import ProductoForm
    form = ProductoForm(request.POST)
    if form.is_valid():
        producto = form.save()
        messages.success(request, f"Producto '{producto.nombre}' agregado al catalogo.")
        return redirect("nuevo_credito")
    messages.error(request, "No se pudo guardar el producto. Revise los datos.")
    return redirect("nuevo_credito")
