"""
COBRAR / Registrar pago.

Este es el flujo mas usado del sistema, asi que esta pensado para que sea
lo mas rapido posible:

    buscar cliente -> ver cuota pendiente -> escribir valor -> cobrar

Y al final, el comprobante con los saldos antes y despues.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..forms import AnularPagoForm, CorregirPagoForm, PagoForm
from ..models import (
    Cliente, Credito, Cuota, EstadoCredito, EstadoCuota, HistorialMovimiento,
    MetodoPago, Pago,
)
from ..permisos import requiere_activo, requiere_administrador
from ..servicios import cartera as servicio_cartera
from ..servicios.cuotas import cuota_siguiente, total_pagado_credito
# OJO: el servicio se importa con otro nombre porque esta vista tambien
# se llama registrar_pago. Si se importara con el mismo nombre, la vista
# taparia al servicio y el cobro nunca se guardaria.
from ..servicios.pagos import (
    ErrorPago, anular_pago, corregir_pago, datos_comprobante,
    registrar_pago as servicio_registrar_pago,
)
from ..servicios.regularidad import calcular_regularidad, estado_cliente
from ..servicios.dinero import formato_dinero

registrador = logging.getLogger("cartera")


# ===========================================================================
# PANTALLA DE COBRO RAPIDO
# ===========================================================================


@requiere_activo
@login_required
def cobrar(request):
    """La pantalla principal de cobranza.

    Pide solo el cliente. De ahi sale directo a la cuota pendiente.
    """
    texto = (request.GET.get("q") or "").strip()
    resultados = []
    if len(texto) >= 2:
        resultados = list(servicio_cartera.buscar_clientes(texto, limite=20))
        for cliente in resultados:
            cliente.saldo = servicio_cartera.resumen_cliente(cliente.id)["saldo"]

    return render(request, "cobranza/cobrar.html", {
        "texto": texto,
        "resultados": resultados,
    })


@requiere_activo
@login_required
def cobrar_cliente(request, cliente_id):
    """Formulario de cobro de un cliente concreto.

    Muestra sus creditos activos, la cuota que toca y un formulario corto
    con solo los campos imprescindibles.
    """
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    creditos = list(
        Credito.objects.filter(cliente=cliente, estado=EstadoCredito.ACTIVO)
        .select_related("frecuencia", "producto")
        .order_by("fecha_venta")
    )
    resumen = servicio_cartera.resumen_cliente(cliente.id)
    regularidad = calcular_regularidad(cliente=cliente)
    hoy = timezone.localdate()

    # Vista previa de la cuota que toca en cada credito.
    info_creditos = []
    for credito in creditos:
        siguiente = cuota_siguiente(credito)
        info_creditos.append({
            "credito": credito,
            "siguiente": siguiente,
            "estado_siguiente": siguiente.estado_real(hoy) if siguiente else None,
            "atraso": siguiente.dias_de_atraso if siguiente else 0,
            "cuotas_pendientes": credito.cuotas.filter(
                valor_pagado__lt=F("valor")).count(),
        })

    # Si viene un credito en la URL, se preselecciona.
    credito_id = request.GET.get("credito")
    credito_elegido = None
    for info in info_creditos:
        if str(info["credito"].id) == str(credito_id):
            credito_elegido = info["credito"]
            break
    if credito_elegido is None and len(info_creditos) == 1:
        credito_elegido = info_creditos[0]["credito"]

    return render(request, "cobranza/cobro_cliente.html", {
        "cliente": cliente,
        "creditos": info_creditos,
        "resumen": resumen,
        "regularidad": regularidad,
        "estado_cliente": estado_cliente(regularidad),
        "credito_elegido": credito_elegido,
        "metodos": MetodoPago.objects.filter(activo=True),
        "hoy": hoy,
        "ultimos_pagos": Pago.objects.filter(
            credito__cliente=cliente, anulado=False,
        ).select_related("metodo", "credito").order_by("-fecha", "-hora")[:5],
    })


# ===========================================================================
# REGISTRAR EL PAGO
# ===========================================================================


@requiere_activo
@login_required
@require_http_methods(["GET", "POST"])
def registrar_pago(request, credito_id=None):
    """Registra el pago y muestra el comprobante.

    Protecciones:
    - El `token` del formulario evita pagos duplicados por recargar.
    - Si el valor supera el saldo, se pide confirmacion de anticipo.
    - Un segundo boton en el formulario evita el doble clic.
    """
    credito = None
    cuota = None
    cliente = None

    if credito_id:
        credito = get_object_or_404(
            Credito.objects.select_related("cliente", "frecuencia"),
            pk=credito_id,
        )
        cliente = credito.cliente
        cuota_id = request.GET.get("cuota")
        if cuota_id:
            cuota = Cuota.objects.filter(pk=cuota_id, credito=credito).first()
    elif request.method == "POST":
        credito_id = request.POST.get("credito")
        if credito_id:
            credito = Credito.objects.select_related(
                "cliente", "frecuencia").filter(pk=credito_id).first()

    if credito is None:
        messages.error(request, "No se encontro el credito para cobrar.")
        return redirect("cobrar")

    if credito.estado != EstadoCredito.ACTIVO:
        messages.warning(
            request,
            f"Este credito esta {credito.get_estado_display().lower()}. "
            f"No admite pagos.",
        )
        return redirect("ficha_credito", credito_id=credito.id)

    # --- Preparacion del formulario -----------------------------------
    siguiente = cuota_siguiente(credito)
    cuota_seleccionada = cuota or siguiente
    saldo_credito = credito.valor_financiado - total_pagado_credito(credito)

    if request.method == "POST":
        form = PagoForm(request.POST)
        if form.is_valid():
            try:
                pago, detalles = servicio_registrar_pago(
                    credito=credito,
                    valor=form.cleaned_data["valor"],
                    metodo=form.cleaned_data["metodo"],
                    usuario=request.user,
                    cuota=form.cleaned_data.get("cuota") or cuota_seleccionada,
                    fecha=form.cleaned_data["fecha"],
                    referencia=form.cleaned_data.get("referencia", ""),
                    observaciones=form.cleaned_data.get("observaciones", ""),
                    token=form.cleaned_data["token"],
                    es_anticipo_confirmado=bool(
                        form.cleaned_data.get("es_anticipo_confirmado")),
                )
            except ErrorPago as error:
                messages.error(request, error.mensaje)
                return redirect("registrar_pago", credito_id=credito.id)
            except Exception as error:
                registrador.exception("Error registrando pago: %s", error)
                messages.error(
                    request,
                    "No se pudo registrar el pago. No se guardo nada: "
                    "intente de nuevo. Si el problema sigue, anule el "
                    "operativo y avise al administrador.",
                )
                return redirect("registrar_pago", credito_id=credito.id)

            # --- Se guardo. Ahora el historial y el comprobante --------
            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.PAGO,
                descripcion=(
                    f"Registro el pago de {formato_dinero(pago.valor)} de "
                    f"{cliente.nombre_completo} (comprobante {pago.recibo})"
                ),
                cliente=cliente,
                credito=credito,
                datos={
                    "recibo": pago.recibo,
                    "valor": str(pago.valor),
                    "metodo": str(pago.metodo),
                    "duplicado": detalles.get("duplicado", False),
                },
                direccion_ip=request.META.get("REMOTE_ADDR"),
            )

            if detalles.get("duplicado"):
                messages.warning(
                    request,
                    "Ese pago ya estaba registrado. No se cobro dos veces.",
                )
            else:
                messages.success(
                    request,
                    f"Pago de {formato_dinero(pago.valor)} registrado. "
                    f"Nuevo saldo: {formato_dinero(pago.saldo_despues)}.",
                )
            if detalles.get("anticipo"):
                messages.info(
                    request,
                    f"Quedaron {formato_dinero(detalles['anticipo'])} de anticipo: se "
                    f"descontaran de las proximas cuotas.",
                )

            return redirect("comprobante", pago_id=pago.id)
    else:
        form = PagoForm(credito=credito)
        if cuota_seleccionada:
            form.fields["cuota"].initial = cuota_seleccionada.id
            form.fields["valor"].initial = cuota_seleccionada.saldo

    return render(request, "cobranza/registrar_pago.html", {
        "form": form,
        "cliente": cliente,
        "credito": credito,
        "cuota": cuota_seleccionada,
        "saldo_credito": saldo_credito,
        "cuotas": list(credito.cuotas.order_by("numero")),
        "hoy": timezone.localdate(),
    })


# ===========================================================================
# COMPROBANTE
# ===========================================================================


@requiere_activo
@login_required
def comprobante(request, pago_id):
    """Comprobante digital del pago. Se puede imprimir."""
    pago = get_object_or_404(
        Pago.objects.select_related(
            "credito", "credito__cliente", "credito__frecuencia", "metodo", "usuario"),
        pk=pago_id,
    )
    datos = datos_comprobante(pago)
    return render(request, "cobranza/comprobante.html", {
        "pago": pago,
        "datos": datos,
        "cliente": pago.credito.cliente,
        "cliente_id": pago.credito.cliente_id,
    })


# ===========================================================================
# HISTORIAL DE PAGOS
# ===========================================================================


@requiere_activo
@login_required
def historial_pagos(request):
    """Todos los pagos del sistema, con filtros."""
    texto = (request.GET.get("q") or "").strip()
    desde = request.GET.get("desde") or ""
    hasta = request.GET.get("hasta") or ""
    metodo = request.GET.get("metodo") or ""
    estado = request.GET.get("estado") or "vigentes"
    pagina = request.GET.get("pagina") or 1

    pagos = Pago.objects.select_related(
        "credito", "credito__cliente", "metodo", "usuario",
    ).order_by("-fecha", "-hora", "-id")

    if texto:
        condicion = (
            Q(recibo__icontains=texto)
            | Q(credito__cliente__nombres__icontains=texto)
            | Q(credito__cliente__apellidos__icontains=texto)
            | Q(referencia__icontains=texto)
        )
        digitos = servicio_cartera.normalizar_cedula(texto)
        if digitos:
            condicion |= Q(credito__cliente__cedula__icontains=digitos)
        pagos = pagos.filter(condicion)

    if desde:
        pagos = pagos.filter(fecha__gte=desde)
    if hasta:
        pagos = pagos.filter(fecha__lte=hasta)
    if metodo:
        pagos = pagos.filter(metodo_id=metodo)
    if estado == "vigentes":
        pagos = pagos.filter(anulado=False)
    elif estado == "anulados":
        pagos = pagos.filter(anulado=True)

    from django.core.paginator import Paginator
    total = pagos.count()
    total_valor = pagos.filter(anulado=False).aggregate(s=Sum("valor"))["s"] or 0
    paginador = Paginator(pagos, 30)
    pagina_obj = paginador.get_page(pagina)

    return render(request, "cobranza/historial.html", {
        "pagos": pagina_obj,
        "paginador": paginador,
        "total": total,
        "total_valor": total_valor,
        "q": texto,
        "desde": desde,
        "hasta": hasta,
        "metodo": metodo,
        "estado": estado,
        "metodos": MetodoPago.objects.filter(activo=True),
    })


# ===========================================================================
# ANULAR Y CORREGIR
# ===========================================================================


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["GET", "POST"])
def anular(request, pago_id):
    """Anula un pago. Solo administradores. El pago NUNCA se borra."""
    pago = get_object_or_404(
        Pago.objects.select_related("credito", "credito__cliente", "metodo"),
        pk=pago_id,
    )
    cliente = pago.credito.cliente

    if request.method == "POST":
        form = AnularPagoForm(request.POST)
        if form.is_valid():
            try:
                anular_pago(
                    pago=pago,
                    usuario=request.user,
                    motivo=form.cleaned_data["motivo"],
                )
            except ErrorPago as error:
                messages.error(request, error.mensaje)
                return redirect("anular", pago_id=pago.id)

            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.ANULACION,
                descripcion=(
                    f"Anulo el pago {pago.recibo} de {formato_dinero(pago.valor)} de "
                    f"{cliente.nombre_completo}. Motivo: "
                    f"{form.cleaned_data['motivo']}"
                ),
                cliente=cliente,
                credito=pago.credito,
                datos={
                    "recibo": pago.recibo,
                    "valor": str(pago.valor),
                    "motivo": form.cleaned_data["motivo"],
                },
            )
            messages.success(
                request,
                f"Pago {pago.recibo} anulado. El saldo se recalculo. "
                f"El registro se conserva en el historial.",
            )
            return redirect("ficha_cliente", cliente_id=cliente.id)
    else:
        form = AnularPagoForm()

    return render(request, "cobranza/anular.html", {
        "form": form,
        "pago": pago,
        "cliente": cliente,
    })


@requiere_activo
@login_required
@requiere_administrador
@require_http_methods(["GET", "POST"])
def corregir(request, pago_id):
    """Corrige el valor o la fecha de un pago. Guardando el antes."""
    pago = get_object_or_404(
        Pago.objects.select_related("credito", "credito__cliente", "metodo"),
        pk=pago_id,
    )
    cliente = pago.credito.cliente

    if request.method == "POST":
        form = CorregirPagoForm(request.POST)
        if form.is_valid():
            try:
                pago, cambios = corregir_pago(
                    pago=pago,
                    nuevo_valor=form.cleaned_data["valor"],
                    nueva_fecha=form.cleaned_data["fecha"],
                    motivo=form.cleaned_data["motivo"],
                    usuario=request.user,
                )
            except ErrorPago as error:
                messages.error(request, error.mensaje)
                return redirect("corregir", pago_id=pago.id)

            HistorialMovimiento.objects.create(
                usuario=request.user,
                tipo=HistorialMovimiento.Tipo.PAGO,
                descripcion=(
                    f"Corrijo el pago {pago.recibo} de {cliente.nombre_completo}. "
                    f"Motivo: {form.cleaned_data['motivo']}"
                ),
                cliente=cliente,
                credito=pago.credito,
                datos={"cambios": cambios, "motivo": form.cleaned_data["motivo"]},
            )
            messages.success(
                request,
                f"Pago {pago.recibo} corregido. Los saldos se actualizaron.",
            )
            return redirect("ficha_cliente", cliente_id=cliente.id)
    else:
        form = CorregirPagoForm(initial={
            "valor": pago.valor,
            "fecha": pago.fecha,
        })

    return render(request, "cobranza/corregir.html", {
        "form": form,
        "pago": pago,
        "cliente": cliente,
    })
