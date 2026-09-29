"""
Dashboard: la pantalla de inicio.

Todas las cifras vienen de la base de datos real a traves de
`servicios.cartera`. No hay ningun numero escrito a mano.
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from ..models import Credito, Pago
from ..permisos import requiere_activo
from ..servicios import cartera as servicio_cartera
from ..servicios.regularidad import estado_cliente


@requiere_activo
@login_required
def dashboard(request):
    """Pantalla de inicio con el resumen del negocio."""
    hoy = timezone.localdate()

    resumen = servicio_cartera.resumen_general(hoy)
    grafico = servicio_cartera.grafico_cobros(dias=14)
    comparativo = servicio_cartera.comparativo_cartera()

    # Los ultimos pagos, para el cuadro de "movimiento de hoy".
    ultimos_pagos = (
        Pago.objects.filter(anulado=False)
        .select_related("credito", "credito__cliente", "metodo")
        .order_by("-fecha", "-hora", "-id")[:8]
    )

    # Lo que hay que cobrar hoy: los primeros 10, del que mas debe al que
    # menos. Asi el cobrador sabe por donde empezar.
    _, cobros = servicio_cartera.cobros_pendientes(hoy, dias_proximos=0)
    por_hacer = (cobros["vencidas"] + cobros["hoy"])[:10]

    # Proximos dias: aviso de lo que viene.
    _, proximos = servicio_cartera.cobros_pendientes(hoy, dias_proximos=3)
    por_hacer_proximos = proximos["proximas"][:10]

    # Un credito recien creado (para el aviso de credito pagado).
    creditos_recientes = (
        Credito.objects.filter(estado="PAGADO", fecha_finalizacion__gte=hoy - timedelta(days=30))
        .select_related("cliente")[:5]
    )

    return render(request, "dashboard.html", {
        "resumen": resumen,
        "grafico": grafico,
        "comparativo": comparativo,
        "ultimos_pagos": ultimos_pagos,
        "por_hacer": por_hacer,
        "por_hacer_proximos": por_hacer_proximos,
        "creditos_recientes": creditos_recientes,
        "total_por_hacer": len(cobros["vencidas"] + cobros["hoy"]),
        "maximo_grafico": max([float(d["total"]) for d in grafico] + [1]),
    })
