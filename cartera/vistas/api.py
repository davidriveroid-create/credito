"""
Busqueda rapida para la barra de busqueda global y el formulario de cobro.

Estas vistas devuelven JSON. No se usan con enlaces normales: el
JavaScript las llama mientras el usuario escribe.

Todas exigen sesion iniciada. Sin sesion, responden 401.
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from ..models import Credito, EstadoCredito
from ..servicios import cartera as servicio_cartera
from ..servicios.cuotas import cuota_siguiente
from ..servicios.regularidad import calcular_regularidad, estado_cliente


@require_GET
@login_required
def buscar(request):
    """Busqueda global mientras el usuario escribe.

    Acepta nombre, apellido o cedula. Con menos de 2 letras no busca
    (devuelve vacio) para no mandar toda la base en cada tecla.
    """
    texto = (request.GET.get("q") or "").strip()
    if len(texto) < 2:
        return JsonResponse({"resultados": [], "total": 0})

    clientes = servicio_cartera.buscar_clientes(texto, limite=15)
    resultados = []
    for cliente in clientes:
        resumen = servicio_cartera.resumen_cliente(cliente.id)
        regularidad = calcular_regularidad(cliente=cliente)
        resultados.append({
            "id": cliente.id,
            "nombre": cliente.nombre_completo,
            "cedula": cliente.cedula,
            "telefono": cliente.telefono,
            "inicial": cliente.nombre_corto,
            "activo": cliente.activo,
            "saldo": float(resumen["saldo"]),
            "saldo_texto": _dinero(resumen["saldo"]),
            "creditos_activos": resumen["creditos_activos"],
            "regularidad": regularidad["porcentaje"],
            "categoria": regularidad["etiqueta"],
            "color": regularidad["color"],
            "estado": estado_cliente(regularidad),
            "url": f"/clientes/{cliente.id}/",
        })

    return JsonResponse({
        "resultados": resultados,
        "total": len(resultados),
        "texto": texto,
    })


@require_GET
@login_required
def info_credito(request):
    """Datos de un credito para el formulario de cobro.

    Le dice al formulario: cuanto falta, cual es la cuota que toca y
    cuanto tiene que pagar el cliente.
    """
    credito_id = request.GET.get("credito")
    if not credito_id or not str(credito_id).isdigit():
        return JsonResponse({"error": "Credito no valido."}, status=400)

    credito = Credito.objects.select_related(
        "cliente", "frecuencia", "producto").filter(pk=credito_id).first()
    if not credito:
        return JsonResponse({"error": "No se encontro el credito."}, status=404)

    siguiente = cuota_siguiente(credito)
    hoy = timezone.localdate()

    return JsonResponse({
        "ok": True,
        "id": credito.id,
        "cliente": credito.cliente.nombre_completo,
        "cliente_id": credito.cliente.id,
        "producto": credito.nombre_producto,
        "frecuencia": str(credito.frecuencia),
        "estado": credito.get_estado_display(),
        "valor_financiado": float(credito.valor_financiado),
        "total_pagado": float(credito.total_pagado),
        "saldo": float(credito.saldo),
        "saldo_texto": _dinero(credito.saldo),
        "cuotas": credito.numero_cuotas,
        "cuotas_pagadas": credito.cuotas_pagadas,
        "cuotas_vencidas": credito.cuotas_vencidas,
        "cuota_actual": siguiente.numero if siguiente else None,
        "cuota_saldo": float(siguiente.saldo) if siguiente else 0,
        "cuota_saldo_texto": _dinero(siguiente.saldo) if siguiente else "$0",
        "cuota_fecha": siguiente.fecha_vencimiento.isoformat() if siguiente else None,
        "cuota_estado": siguiente.estado_real(hoy) if siguiente else "PAGADA",
        "cuota_atraso": siguiente.dias_de_atraso if siguiente else 0,
        "url": f"/creditos/{credito.id}/",
    })


@require_GET
@login_required
def buscar_creditos(request):
    """Creditos de un cliente, para el selector del formulario de cobro."""
    cliente_id = request.GET.get("cliente")
    if not cliente_id or not str(cliente_id).isdigit():
        return JsonResponse({"creditos": []})

    creditos = Credito.objects.filter(
        cliente_id=cliente_id, estado=EstadoCredito.ACTIVO,
    ).select_related("frecuencia", "producto")

    hoy = timezone.localdate()
    datos = []
    for credito in creditos:
        siguiente = cuota_siguiente(credito)
        datos.append({
            "id": credito.id,
            "producto": credito.nombre_producto,
            "frecuencia": str(credito.frecuencia),
            "saldo": float(credito.saldo),
            "saldo_texto": _dinero(credito.saldo),
            "cuota_actual": siguiente.numero if siguiente else None,
            "cuota_saldo": float(siguiente.saldo) if siguiente else 0,
            "cuota_saldo_texto": _dinero(siguiente.saldo) if siguiente else "$0",
            "cuota_estado": siguiente.estado_real(hoy) if siguiente else "PAGADA",
            "atraso": siguiente.dias_de_atraso if siguiente else 0,
        })

    return JsonResponse({"creditos": datos})


def _dinero(valor):
    from ..servicios.dinero import formato_dinero
    return formato_dinero(valor)
