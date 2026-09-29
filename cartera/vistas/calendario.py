"""
Calendario de cobros: la agenda diaria de cobranza.

Muestra el mes con los dias que tienen cuotas programadas. Al abrir un dia,
se ve a quien hay que cobrarle, cuanto se espera, cuanto se recibio y
cuanto falta.
"""

import calendar as _calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from ..permisos import requiere_activo
from ..servicios import cartera as servicio_cartera


@requiere_activo
@login_required
def calendario(request):
    """Vista de mes con las cuotas programadas."""
    hoy = timezone.localdate()

    anio = int(request.GET.get("anio") or hoy.year)
    mes = int(request.GET.get("mes") or hoy.month)
    if mes < 1 or mes > 12:
        mes = hoy.month
    if anio < 2000 or anio > 2100:
        anio = hoy.year

    datos = servicio_cartera.calendario_del_mes(anio, mes)

    # Navegacion mes a mes.
    anterior = date(anio, mes, 1) - timedelta(days=1)
    siguiente = date(anio, mes, 1) + timedelta(days=32)
    siguiente = date(siguiente.year, siguiente.month, 1)

    nombres_meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]

    # Arma la grilla: filas de 7 dias (lunes a domingo).
    ultimo_dia = _calendar.monthrange(anio, mes)[1]
    # lunes=0 ... domingo=6
    desplazamiento = date(anio, mes, 1).weekday()
    celdas = [None] * desplazamiento
    for numero_dia in range(1, ultimo_dia + 1):
        celdas.append(datos["dias"][numero_dia])
    filas = [celdas[i:i + 7] for i in range(0, len(celdas), 7)]

    return render(request, "calendario/calendario.html", {
        "datos": datos,
        "anio": anio,
        "mes": mes,
        "nombre_mes": nombres_meses[mes - 1],
        "hoy": hoy,
        "anterior": anterior,
        "siguiente": siguiente,
        "filas": filas,
        "dias_semana": ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"],
    })


@requiere_activo
@login_required
def dia(request, anio, mes, dia):
    """Detalle de un dia: a quien hay que cobrarle."""
    fecha = date(int(anio), int(mes), int(dia))
    datos = servicio_cartera.detalle_dia(fecha)
    hoy = timezone.localdate()

    nombres_meses = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]

    return render(request, "calendario/dia.html", {
        "datos": datos,
        "fecha": fecha,
        "hoy": hoy,
        "nombre_mes": nombres_meses[int(mes) - 1],
        "es_hoy": fecha == hoy,
        "es_pasado": fecha < hoy,
    })
