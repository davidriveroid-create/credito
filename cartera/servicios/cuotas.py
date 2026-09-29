"""
Servicio de cuotas: crear el plan de pagos, recalcular saldos y saber
cual es la cuota que toca.

Todas las funciones que modifican datos usan `transaction.atomic` y
`select_for_update` para que dos personas cobrando al mismo tiempo en
pestanas distintas no dejen el saldo mal.
"""

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from ..models import (
    AplicacionPago, CERO, Credito, Cuota, EstadoCredito, EstadoCuota, Pago,
    pesada,
)
from .calendario import generar_plan_pagos, sumar_frecuencia


def cuota_siguiente(credito):
    """La cuota que el cliente debe pagar ahora.

    Devuelve la primera cuota sin terminar de pagar, empezando por la mas
    vieja (que es la vencida si hay atrasos). Las ya pagadas no se miran.
    """
    for cuota in credito.cuotas.order_by("numero"):
        if not cuota.esta_pagada:
            return cuota
    return None


def cuotas_por_estado(credito, hoy=None):
    """Cuenta las cuotas de un credito usando el estado real (con fecha)."""
    if hoy is None:
        hoy = timezone.localdate()
    conteo = {estado: 0 for estado in EstadoCuota.values}
    for cuota in credito.cuotas.order_by("numero"):
        conteo[cuota.estado_real(hoy)] += 1
    return conteo


def total_pagado_credito(credito):
    """Suma de los pagos NO anulados del credito."""
    total = Pago.objects.filter(credito=credito, anulado=False).aggregate(
        suma=Sum("valor"),
    )["suma"]
    return pesada(total or CERO)


def saldo_credito(credito):
    """Lo que falta por pagar de este credito."""
    return pesada(max(CERO, credito.valor_financiado - total_pagado_credito(credito)))


def max_dias_atraso_credito(credito, hoy=None):
    """Dias de atraso de la cuota mas vieja que sigue sin pagar."""
    if hoy is None:
        hoy = timezone.localdate()
    vencida = (
        credito.cuotas.filter(fecha_vencimiento__lt=hoy)
        .exclude(valor_pagado__gte=F("valor"))
        .order_by("fecha_vencimiento")
        .first()
    )
    if not vencida:
        return 0
    return (hoy - vencida.fecha_vencimiento).days


def recalcular_cuota(cuota, guardar=True):
    """Pone el estado guardado de la cuota segun lo que se ha abonado.

    OJO: el estado que se MUESTRA al usuario es `estado_real`, que ademas
    revisa la fecha. Este solo guarda PENDIENTE / PARCIAL / PAGADA.
    """
    if cuota.esta_pagada:
        cuota.estado = EstadoCuota.PAGADA
    elif cuota.valor_pagado > CERO:
        cuota.estado = EstadoCuota.PARCIAL
    else:
        cuota.estado = EstadoCuota.PENDIENTE

    if guardar:
        cuota.save(update_fields=["estado", "fecha_pago", "valor_pagado"])
    return cuota


@transaction.atomic
def recalcular_credito(credito, guardar=True):
    """Recalcula TODOS los saldos del credito a partir de los pagos reales.

    Esta es la funcion de referencia: si algo se descuadra, se llama esto y
    queda como debe ser. Nunca borra pagos, solo los lee.
    """
    credito = Credito.objects.select_for_update().select_related(
        "cliente", "frecuencia",
    ).get(pk=credito.pk)

    hoy = timezone.localdate()

    # 1) Recalcular cada cuota desde las aplicaciones de pago.
    #    Un pago puede tocar varias cuotas, asi que la verdad esta en
    #    AplicacionPago y no en el pago suelto.
    for cuota in credito.cuotas.order_by("numero"):
        aplicaciones = list(
            AplicacionPago.objects.filter(cuota=cuota, pago__anulado=False)
            .select_related("pago")
            .order_by("fecha_aplicacion", "pago__hora", "pago_id")
        )

        total = pesada(sum((a.valor for a in aplicaciones), CERO))
        # Nunca se abona mas que el valor de la cuota: el exceso del pago
        # vive en las cuotas siguientes, no aqui.
        cuota.valor_pagado = pesada(min(total, cuota.valor))

        if cuota.esta_pagada:
            # La fecha en que la cuota quedo pagada es la del ultimo pago
            # que la completo.
            cuota.fecha_pago = (
                aplicaciones[-1].pago.fecha if aplicaciones else cuota.fecha_pago
            )
        else:
            cuota.fecha_pago = None
        cuota.fecha_ultimo_abono = (
            aplicaciones[-1].pago.fecha if aplicaciones else None
        )

        recalcular_cuota(cuota, guardar=True)

    # 2) Totales del credito.
    total_pagado = total_pagado_credito(credito)
    saldo = pesada(max(CERO, credito.valor_financiado - total_pagado))

    credito.total_pagado = total_pagado
    credito.saldo = saldo
    credito.cuotas_pagadas = credito.cuotas.filter(
        valor_pagado__gte=F("valor"),
    ).count()
    credito.cuotas_vencidas = credito.cuotas.filter(
        fecha_vencimiento__lt=hoy,
    ).exclude(valor_pagado__gte=F("valor")).count()

    # 3) Estado del credito.
    if credito.estado != EstadoCredito.ANULADO:
        if saldo <= CERO:
            credito.estado = EstadoCredito.PAGADO
            if not credito.fecha_finalizacion:
                credito.fecha_finalizacion = hoy
        else:
            credito.estado = EstadoCredito.ACTIVO
            credito.fecha_finalizacion = None

    if guardar:
        credito.save(update_fields=[
            "total_pagado", "saldo", "cuotas_pagadas", "cuotas_vencidas",
            "estado", "fecha_finalizacion", "fecha_modificacion",
        ])
    return credito


def crear_plan_credito(credito):
    """Crea las cuotas de un credito nuevo segun su frecuencia y fechas.

    Si el credito ya tiene cuotas, no se regeneran: los pagos ya hechos
    jamas se pisan. Esto evita el error clasico de 'se duplicaron las
    cuotas al guardar dos veces'.
    """
    with transaction.atomic():
        hoy = timezone.localdate()
        credito = Credito.objects.select_for_update().select_related(
            "frecuencia",
        ).get(pk=credito.pk)

        if credito.cuotas.exists():
            return list(credito.cuotas.order_by("numero"))

        plan, valor_base, valor_ultima = generar_plan_pagos(
            saldo_financiado=credito.valor_financiado,
            numero_cuotas=credito.numero_cuotas,
            fecha_primera=credito.fecha_primera_cuota,
            frecuencia=credito.frecuencia,
            valor_cuota_manual=credito.valor_cuota or None,
        )
        credito.valor_cuota = valor_base
        credito.fecha_estimada_fin = plan[-1]["fecha"]
        # Un credito recien creado debe debe TODO el saldo. Sin esto el
        # credito aparecia con saldo $0 y la cartera quedaba mal.
        credito.total_pagado = CERO
        credito.saldo = pesada(credito.valor_financiado)
        credito.cuotas_pagadas = 0
        credito.cuotas_vencidas = plan[0]["fecha"] < hoy
        credito.save(update_fields=[
            "valor_cuota", "fecha_estimada_fin", "fecha_modificacion",
            "total_pagado", "saldo", "cuotas_pagadas", "cuotas_vencidas",
        ])

        Cuota.objects.bulk_create([
            Cuota(
                credito=credito,
                numero=p["numero"],
                fecha_vencimiento=p["fecha"],
                valor=p["valor"],
                estado=EstadoCuota.PENDIENTE,
            )
            for p in plan
        ])
        return list(credito.cuotas.order_by("numero"))


def eliminar_credito_si_sin_pagos(credito):
    """Si un credito se creo por error y no tiene pagos, se borra entero.

    Un credito que ya tiene pagos NUNCA se borra: se anula. Esta funcion es
    la garantia de que no se pierde informacion financiera.

    Devuelve True si se borro, False si se dejo intacto.
    """
    if credito.pagos.exists():
        return False
    credito.cuotas.all().delete()
    credito.delete()
    return True


def fecha_estimada_fin(fecha_primera, frecuencia, numero_cuotas):
    """Ultima fecha del plan, para mostrarla al crear el credito."""
    return sumar_frecuencia(fecha_primera, frecuencia, numero_cuotas - 1)
