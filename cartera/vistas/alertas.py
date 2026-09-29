"""
COBROS PENDIENTES: la seccion de la agenda de cobranza.

Responde: ¿a quien tengo que llamar hoy y por que?
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone

from ..models import EstadoCuota
from ..permisos import requiere_activo
from ..servicios import cartera as servicio_cartera


@requiere_activo
@login_required
def cobros_pendientes(request):
    """A quien hay que cobrarle hoy, ordenado por atraso."""
    hoy = timezone.localdate()
    dias = request.GET.get("dias")
    try:
        dias_proximos = int(dias) if dias else 3
    except (TypeError, ValueError):
        dias_proximos = 3
    dias_proximos = max(0, min(30, dias_proximos))
    solo_activos = request.GET.get("inactivos") != "1"

    filas, resumen = servicio_cartera.cobros_pendientes(
        hoy, solo_activos=solo_activos, dias_proximos=dias_proximos,
    )

    # El cobrador normalmente solo mira vencidas y las de hoy; las proximas
    # van en otra pestana para no saturar la lista.
    vista = request.GET.get("vista") or "vencidas"
    if vista == "hoy":
        visibles = resumen["hoy"]
    elif vista == "proximas":
        visibles = resumen["proximas"]
    elif vista == "todas":
        visibles = filas
    else:
        visibles = resumen["vencidas"] + resumen["hoy"]

    pagina = request.GET.get("pagina") or 1
    paginador = Paginator(visibles, 25)
    pagina_obj = paginador.get_page(pagina)

    return render(request, "alertas/cobros_pendientes.html", {
        "filas": pagina_obj,
        "paginador": paginador,
        "resumen": resumen,
        "vista": vista,
        "dias": dias_proximos,
        "solo_activos": solo_activos,
        "hoy": hoy,
        "total": len(visibles),
    })
