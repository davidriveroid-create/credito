"""
Reportes y exportaciones.

Reportes disponibles:
  - Cartera total (quien debe que)
  - Cartera vencida (quien esta atrasado y cuantos dias)
  - Cobros del dia / semana / mes
  - Clientes al dia vs atrasados
  - Creditos activos vs terminados
  - Total vendido, cobrado y pendiente

Exportacion a Excel (.xlsx real) y a PDF (impresion limpia).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Cliente, Credito, EstadoCredito, Pago
from ..permisos import requiere_activo
from ..servicios import cartera as servicio_cartera
from ..servicios.regularidad import calcular_regularidad, configuracion

registrador = logging.getLogger("cartera")

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _rango_desde_get(GET):
    """Lee las fechas del formulario de filtros."""
    hoy = timezone.localdate()
    desde_texto = GET.get("desde") or ""
    hasta_texto = GET.get("hasta") or ""
    try:
        desde = date.fromisoformat(desde_texto) if desde_texto else hoy.replace(day=1)
    except ValueError:
        desde = hoy.replace(day=1)
    try:
        hasta = date.fromisoformat(hasta_texto) if hasta_texto else hoy
    except ValueError:
        hasta = hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


# ===========================================================================
# PAGINA PRINCIPAL DE REPORTES
# ===========================================================================


@requiere_activo
@login_required
def reportes(request):
    """Menu de reportes con el resumen de cada uno."""
    desde, hasta = _rango_desde_get(request.GET)
    hoy = timezone.localdate()

    config = configuracion()
    resumen = servicio_cartera.resumen_general(hoy)
    cartera = servicio_cartera.reporte_cartera()
    cobros = servicio_cartera.reporte_cobros(desde, hasta)
    ventas = servicio_cartera.reporte_ventas(desde, hasta)
    atrasados = servicio_cartera.clientes_atrasados()

    return render(request, "reportes/reportes.html", {
        "desde": desde,
        "hasta": hasta,
        "resumen": resumen,
        "cartera": cartera,
        "cartera_vencida": [f for f in cartera if f["saldo_vencido"] > 0],
        "cobros": cobros,
        "ventas": ventas,
        "atrasados": atrasados,
        "hoy": hoy,
        "grafos": {
            "semana": servicio_cartera.grafico_cobros(dias=7),
            "mes": servicio_cartera.grafico_cobros(dias=30),
        },
    })


# ===========================================================================
# EXPORTACIONES
# ===========================================================================


@requiere_activo
@login_required
def exportar_excel(request):
    """Descarga un .xlsx real con el reporte pedido."""
    tipo = request.GET.get("tipo") or "cartera"
    desde, hasta = _rango_desde_get(request.GET)
    config = configuracion()

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as error:
        registrador.exception("Falta openpyxl: %s", error)
        return HttpResponse(
            "No esta instalada la libreria para exportar a Excel.\n"
            "Instale openpyxl en el entorno del programa y vuelva a intentar.",
            status=500,
            content_type="text/plain; charset=utf-8",
        )

    libro = Workbook()

    # --- Portada ---------------------------------------------------
    hoja = libro.active
    hoja.title = "Resumen"
    hoja["A1"] = config.nombre_negocio
    hoja["A1"].font = Font(size=16, bold=True)
    hoja["A2"] = f"Reporte generado el {timezone.localtime():%d/%m/%Y %I:%M %p}"
    hoja["A3"] = f"Periodo: {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"

    resumen = servicio_cartera.resumen_general()
    datos_resumen = [
        ("Clientes registrados", resumen["total_clientes"]),
        ("Clientes con credito activo", resumen["clientes_con_credito_activo"]),
        ("Clientes al dia", resumen["clientes_al_dia"]),
        ("Clientes atrasados", resumen["clientes_atrasados"]),
        ("Clientes en mora", resumen["clientes_en_mora"]),
        ("Creditos activos", resumen["creditos_activos"]),
        ("Creditos pagados", resumen["creditos_pagados"]),
        ("Total vendido a credito", float(resumen["total_vendido"])),
        ("Total financiado", float(resumen["total_financiado"])),
        ("Total cobrado", float(resumen["total_cobrado"])),
        ("Total pendiente por cobrar", float(resumen["total_pendiente"])),
        ("Cartera vencida", float(resumen["cartera_vencida"])),
        ("Cobrado hoy", float(resumen["cobrado_hoy"])),
        ("Cobrado esta semana", float(resumen["cobrado_semana"])),
        ("Cobrado este mes", float(resumen["cobrado_mes"])),
    ]
    hoja["A5"] = "Concepto"
    hoja["B5"] = "Valor"
    for celda in ("A5", "B5"):
        hoja[celda].font = Font(bold=True)
        hoja[celda].fill = PatternFill("solid", fgColor="1e293b")
        hoja[celda].font = Font(bold=True, color="FFFFFF")
    fila = 6
    for concepto, valor in datos_resumen:
        hoja.cell(row=fila, column=1, value=concepto)
        hoja.cell(row=fila, column=2, value=valor)
        if isinstance(valor, float) and valor > 1000:
            hoja.cell(row=fila, column=2).number_format = '"$"#,##0'
        fila += 1

    # --- Hoja de cartera -------------------------------------------
    hoja_cartera = libro.create_sheet("Cartera")
    encabezados = [
        "Cliente", "Cedula", "Telefono", "Credito #", "Producto",
        "Frecuencia", "Fecha venta", "Valor financiado", "Total pagado",
        "Saldo pendiente", "Cuotas pagadas", "Cuotas vencidas",
        "Saldo vencido", "Dias de atraso", "Regularidad", "Puntualidad %",
    ]
    _encabezados(hoja_cartera, encabezados, Font, PatternFill, Alignment)

    fila = 2
    for dato in servicio_cartera.reporte_cartera():
        credito = dato["credito"]
        cliente = dato["cliente"]
        regularidad = dato["regularidad"]
        hoja_cartera.cell(row=fila, column=1, value=cliente.nombre_completo)
        hoja_cartera.cell(row=fila, column=2, value=cliente.cedula)
        hoja_cartera.cell(row=fila, column=3, value=cliente.telefono)
        hoja_cartera.cell(row=fila, column=4, value=credito.id)
        hoja_cartera.cell(row=fila, column=5, value=credito.nombre_producto)
        hoja_cartera.cell(row=fila, column=6, value=str(credito.frecuencia))
        hoja_cartera.cell(row=fila, column=7, value=credito.fecha_venta)
        hoja_cartera.cell(row=fila, column=8, value=float(credito.valor_financiado))
        hoja_cartera.cell(row=fila, column=9, value=float(credito.total_pagado))
        hoja_cartera.cell(row=fila, column=10, value=float(credito.saldo))
        hoja_cartera.cell(row=fila, column=11, value=credito.cuotas_pagadas)
        hoja_cartera.cell(row=fila, column=12, value=credito.cuotas_vencidas)
        hoja_cartera.cell(row=fila, column=13, value=float(dato["saldo_vencido"]))
        hoja_cartera.cell(row=fila, column=14, value=dato["atraso"])
        hoja_cartera.cell(row=fila, column=15, value=regularidad["etiqueta"])
        hoja_cartera.cell(row=fila, column=16, value=regularidad["porcentaje"])
        fila += 1

    _formato_dinero(hoja_cartera, [8, 9, 10, 13], fila)
    _anchos(hoja_cartera, encabezados, get_column_letter)

    # --- Hoja de pagos ---------------------------------------------
    hoja_pagos = libro.create_sheet("Cobros")
    encabezados_pago = [
        "Comprobante", "Fecha", "Hora", "Cliente", "Cedula", "Credito #",
        "Producto", "Cuota #", "Valor pagado", "Metodo", "Referencia",
        "Saldo antes", "Saldo despues", "Estado",
    ]
    _encabezados(hoja_pagos, encabezados_pago, Font, PatternFill, Alignment)

    pagos = Pago.objects.filter(
        anulado=False, fecha__gte=desde, fecha__lte=hasta,
    ).select_related("credito", "credito__cliente", "metodo", "cuota")

    fila = 2
    for pago in pagos:
        hoja_pagos.cell(row=fila, column=1, value=pago.recibo)
        hoja_pagos.cell(row=fila, column=2, value=pago.fecha)
        hoja_pagos.cell(row=fila, column=3, value=pago.hora.strftime("%H:%M"))
        hoja_pagos.cell(row=fila, column=4, value=pago.credito.cliente.nombre_completo)
        hoja_pagos.cell(row=fila, column=5, value=pago.credito.cliente.cedula)
        hoja_pagos.cell(row=fila, column=6, value=pago.credito.id)
        hoja_pagos.cell(row=fila, column=7, value=pago.credito.nombre_producto)
        hoja_pagos.cell(row=fila, column=8, value=pago.cuota.numero if pago.cuota else "-")
        hoja_pagos.cell(row=fila, column=9, value=float(pago.valor))
        hoja_pagos.cell(row=fila, column=10, value=str(pago.metodo))
        hoja_pagos.cell(row=fila, column=11, value=pago.referencia)
        hoja_pagos.cell(row=fila, column=12, value=float(pago.saldo_antes))
        hoja_pagos.cell(row=fila, column=13, value=float(pago.saldo_despues))
        hoja_pagos.cell(row=fila, column=14, value="Anulado" if pago.anulado else "Vigente")
        fila += 1

    _formato_dinero(hoja_pagos, [9, 12, 13], fila)
    _anchos(hoja_pagos, encabezados_pago, get_column_letter)

    # --- Hoja de clientes atrasados ---------------------------------
    hoja_atraso = libro.create_sheet("Atrasados")
    encabezados_atraso = [
        "Cliente", "Cedula", "Telefono", "Dias de atraso",
        "Cuotas vencidas", "Saldo vencido", "Saldo total",
        "Regularidad", "Puntualidad %", "Ultimo pago",
    ]
    _encabezados(hoja_atraso, encabezados_atraso, Font, PatternFill, Alignment)

    fila = 2
    for dato in servicio_cartera.clientes_atrasados():
        cliente = dato["cliente"]
        hoja_atraso.cell(row=fila, column=1, value=cliente.nombre_completo)
        hoja_atraso.cell(row=fila, column=2, value=cliente.cedula)
        hoja_atraso.cell(row=fila, column=3, value=cliente.telefono)
        hoja_atraso.cell(row=fila, column=4, value=dato["atraso"])
        hoja_atraso.cell(row=fila, column=5, value=dato["cuotas_vencidas"])
        hoja_atraso.cell(row=fila, column=6, value=float(dato["saldo_vencido"]))
        hoja_atraso.cell(row=fila, column=7, value=float(dato["saldo_total"]))
        hoja_atraso.cell(row=fila, column=8, value=dato["regularidad"]["etiqueta"])
        hoja_atraso.cell(row=fila, column=9, value=dato["regularidad"]["porcentaje"])
        ultimo = Pago.objects.filter(
            credito__cliente=cliente, anulado=False,
        ).order_by("-fecha").first()
        hoja_atraso.cell(row=fila, column=10, value=ultimo.fecha if ultimo else "-")
        fila += 1

    _formato_dinero(hoja_atraso, [6, 7], fila)
    _anchos(hoja_atraso, encabezados_atraso, get_column_letter)

    # --- Guardar y responder ---------------------------------------
    import io
    archivo = io.BytesIO()
    libro.save(archivo)

    nombre = f"reporte_credito_{timezone.localdate():%Y%m%d_%H%M}.xlsx"
    respuesta = HttpResponse(
        archivo.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _encabezados(hoja, encabezados, Font, PatternFill, Alignment):
    for indice, texto in enumerate(encabezados, start=1):
        celda = hoja.cell(row=1, column=indice, value=texto)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1e293b")
        celda.alignment = Alignment(horizontal="center", vertical="center")
    hoja.freeze_panes = "A2"


def _formato_dinero(hoja, columnas, fila_final):
    for fila in range(2, fila_final + 1):
        for columna in columnas:
            hoja.cell(row=fila, column=columna).number_format = '"$"#,##0'


def _anchos(hoja, encabezados, get_column_letter):
    for indice, texto in enumerate(encabezados, start=1):
        ancho = max(len(str(texto)) + 3, 13)
        hoja.column_dimensions[get_column_letter(indice)].width = min(ancho, 40)


@requiere_activo
@login_required
def exportar_csv(request):
    """Exporta a CSV (se abre con Excel o Google Sheets)."""
    tipo = request.GET.get("tipo") or "cartera"
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    nombre = f"cartera_credito_{timezone.localdate():%Y%m%d}.csv"
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    respuesta.write("\ufeff")  # para que Excel abra los acentos bien

    if tipo == "pagos":
        respuesta.write("Comprobante;Fecha;Cliente;Cedula;Valor;Metodo;Estado\n")
        pagos = Pago.objects.select_related(
            "credito", "credito__cliente", "metodo").order_by("-fecha")[:5000]
        for pago in pagos:
            respuesta.write(
                f"{pago.recibo};{pago.fecha:%Y-%m-%d};"
                f"{pago.credito.cliente.nombre_completo};"
                f"{pago.credito.cliente.cedula};{pago.valor};"
                f"{pago.metodo};{'Anulado' if pago.anulado else 'Vigente'}\n"
            )
    else:
        respuesta.write("Cliente;Cedula;Telefono;Credito;Saldo;Vencido;Atraso;Regularidad\n")
        for dato in servicio_cartera.reporte_cartera():
            respuesta.write(
                f"{dato['cliente'].nombre_completo};{dato['cliente'].cedula};"
                f"{dato['cliente'].telefono};#{dato['credito'].id};"
                f"{dato['saldo']};{dato['saldo_vencido']};{dato['atraso']};"
                f"{dato['regularidad']['etiqueta']}\n"
            )
    return respuesta
