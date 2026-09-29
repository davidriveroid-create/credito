"""
Consultas de cartera: los numeros del dashboard, las alertas de cobranza,
el calendario y los reportes.

Aqui vive el "de donde sale este numero" para que ningun total de la
pantalla sea inventado.
"""

from datetime import date as _fecha, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import (
    CERO, Cliente, Credito, Cuota, EstadoCredito, EstadoCuota, Pago,
    pesada,
)
from .regularidad import (
    calcular_regularidad, configuracion, estado_cliente,
    regularidad_de_lista,
)

# En los agregados hay que decir que el cero de relleno es decimal. Si se
# deja como 0 (entero), SQLite se queja de "tipos mezclados" y el panel
# deja de funcionar cuando no hay ningun dato.
CERO_D = Value(Decimal("0"))


def pesados(valor):
    """Convierte a Decimal para poder dividir sin que se quebre."""
    return Decimal(str(valor or 0))


# ===========================================================================
# DASHBOARD
# ===========================================================================


def resumen_general(hoy=None):
    """Los numeros grandes de la pantalla de inicio.

    Cada valor sale de la base de datos real, no de un numero guardado.
    """
    if hoy is None:
        hoy = timezone.localdate()
    config = configuracion()
    ayer = hoy - timedelta(days=1)
    inicio_semana = hoy - timedelta(days=6)
    inicio_mes = hoy.replace(day=1)

    creditos = Credito.objects.exclude(estado=EstadoCredito.ANULADO)

    # --- Clientes ----------------------------------------------------
    clientes_qs = Cliente.objects.all()
    clientes_ids_activos = list(
        creditos.filter(estado=EstadoCredito.ACTIVO)
        .values_list("cliente_id", flat=True).distinct()
    )
    regularidades = regularidad_de_lista(clientes_ids_activos, config)

    estados = {"AL_DIA": 0, "ATRASADO": 0, "MORA": 0, "SIN_DATOS": 0}
    for cliente_id in clientes_ids_activos:
        reg = regularidades.get(cliente_id)
        if reg:
            estados[estado_cliente(reg)] += 1

    # --- Dinero ------------------------------------------------------
    totales = creditos.aggregate(
        vendido=Coalesce(Sum("precio_financiado"), CERO_D),
        financiado=Coalesce(Sum("valor_financiado"), CERO_D),
        cobrado=Coalesce(Sum("total_pagado"), CERO_D),
        pendiente=Coalesce(Sum("saldo"), CERO_D),
    )

    pagos_no_anulados = Pago.objects.filter(anulado=False)

    cobrado_hoy = pesada(pagos_no_anulados.filter(fecha=hoy).aggregate(
        s=Sum("valor"))["s"] or 0)
    cobrado_semana = pesada(pagos_no_anulados.filter(
        fecha__gte=inicio_semana, fecha__lte=hoy).aggregate(s=Sum("valor"))["s"] or 0)
    cobrado_mes = pesada(pagos_no_anulados.filter(
        fecha__gte=inicio_mes, fecha__lte=hoy).aggregate(s=Sum("valor"))["s"] or 0)

    # --- Cuotas de hoy ------------------------------------------------
    cuotas_hoy = Cuota.objects.filter(fecha_vencimiento=hoy)
    valor_esperado_hoy = pesada(cuotas_hoy.aggregate(s=Sum("valor"))["s"] or 0)
    valor_recibido_hoy = pesada(
        cuotas_hoy.filter(valor_pagado__gte=F("valor")).aggregate(
            s=Sum("valor"))["s"] or 0)

    # --- Cartera vencida ----------------------------------------------
    cuotas_vencidas = Cuota.objects.filter(
        fecha_vencimiento__lt=hoy,
    ).exclude(valor_pagado__gte=F("valor")).exclude(
        credito__estado=EstadoCredito.ANULADO,
    ).exclude(credito__cliente__activo=False)

    valor_vencido = pesada(cuotas_vencidas.aggregate(s=Sum("valor"))["s"] or 0)
    # Lo que realmente falta de esas cuotas vencidas (no el valor completo).
    saldo_vencido = pesada(sum(
        (c.saldo for c in cuotas_vencidas), CERO
    ))

    clientes_en_mora = creditos.filter(
        cuotas__fecha_vencimiento__lt=hoy,
    ).exclude(cuotas__valor_pagado__gte=F("cuotas__valor")).values(
        "cliente_id").distinct().count()

    return {
        "hoy": hoy,
        # Clientes
        "total_clientes": clientes_qs.count(),
        "clientes_activos": clientes_qs.filter(activo=True).count(),
        "clientes_inactivos": clientes_qs.filter(activo=False).count(),
        "clientes_con_credito_activo": len(clientes_ids_activos),
        "clientes_al_dia": estados["AL_DIA"],
        "clientes_atrasados": estados["ATRASADO"],
        "clientes_en_mora": estados["MORA"],
        "clientes_sin_datos": estados["SIN_DATOS"],
        # Creditos
        "creditos_activos": creditos.filter(estado=EstadoCredito.ACTIVO).count(),
        "creditos_pagados": creditos.filter(estado=EstadoCredito.PAGADO).count(),
        "total_creditos": creditos.count(),
        # Dinero
        "total_vendido": pesada(totales["vendido"]),
        "total_financiado": pesada(totales["financiado"]),
        "total_cobrado": pesada(totales["cobrado"]),
        "total_pendiente": pesada(totales["pendiente"]),
        "cartera_vencida": saldo_vencido,
        "cartera_vencida_bruto": valor_vencido,
        "cantidad_cuotas_vencidas": cuotas_vencidas.count(),
        "cantidad_clientes_mora": clientes_en_mora,
        # Cobros
        "cobrado_hoy": cobrado_hoy,
        "cobrado_semana": cobrado_semana,
        "cobrado_mes": cobrado_mes,
        "cantidad_pagos_hoy": pagos_no_anulados.filter(fecha=hoy).count(),
        # Cuotas de hoy
        "cuotas_por_cobrar_hoy": cuotas_hoy.count(),
        "valor_esperado_hoy": valor_esperado_hoy,
        "valor_recibido_hoy": valor_recibido_hoy,
        "cuotas_pendientes_hoy": cuotas_hoy.filter(
            valor_pagado__lt=F("valor")).count(),
    }


def grafico_cobros(dias=14):
    """Ultimos N dias con lo cobrado, para el grafico de barras."""
    hoy = timezone.localdate()
    inicio = hoy - timedelta(days=dias - 1)

    datos = (
        Pago.objects.filter(anulado=False, fecha__gte=inicio, fecha__lte=hoy)
        .values("fecha")
        .annotate(total=Sum("valor"), cantidad=Count("id"))
        .order_by("fecha")
    )
    mapa = {d["fecha"]: d for d in datos}

    serie = []
    for i in range(dias):
        fecha = inicio + timedelta(days=i)
        fila = mapa.get(fecha)
        serie.append({
            "fecha": fecha,
            "etiqueta": fecha.strftime("%d/%m"),
            "total": pesada(fila["total"] if fila else 0),
            "cantidad": fila["cantidad"] if fila else 0,
        })
    return serie


def comparativo_cartera():
    """Para el grafico de torta: al dia vs atrasado vs mora.

    Ademas calcula el `gradiente` CSS completo (conic-gradient) para que la
    plantilla no tenga que armar angulos a mano.
    """
    resumen = resumen_general()
    datos = [
        {"nombre": "Al dia", "clave": "al_dia",
         "valor": resumen["clientes_al_dia"], "color": "#16a34a"},
        {"nombre": "Atrasados", "clave": "atrasados",
         "valor": resumen["clientes_atrasados"], "color": "#f97316"},
        {"nombre": "En mora", "clave": "en_mora",
         "valor": resumen["clientes_en_mora"], "color": "#dc2626"},
        {"nombre": "Sin datos", "clave": "sin_datos",
         "valor": resumen["clientes_sin_datos"], "color": "#cbd5e1"},
    ]

    total = sum(d["valor"] for d in datos)
    if total:
        angulo = 0.0
        for dato in datos:
            if dato["valor"]:
                desde = angulo
                angulo += (dato["valor"] / total) * 360
                dato["desde"] = round(desde, 2)
                dato["hasta"] = round(angulo, 2)
                dato["porcentaje"] = round((dato["valor"] / total) * 100)
            else:
                dato["desde"] = 0
                dato["hasta"] = 0
                dato["porcentaje"] = 0
    else:
        for dato in datos:
            dato.update(desde=0, hasta=0, porcentaje=0)

    return datos


# ===========================================================================
# FICHA DEL CLIENTE
# ===========================================================================


def resumen_cliente(cliente_id):
    """Dinero del cliente: comprado, pagado, pendiente, cuotas."""
    creditos = Credito.objects.filter(cliente_id=cliente_id).exclude(
        estado=EstadoCredito.ANULADO)
    totales = creditos.aggregate(
        comprado=Coalesce(Sum("precio_financiado"), CERO_D),
        financiado=Coalesce(Sum("valor_financiado"), CERO_D),
        pagado=Coalesce(Sum("total_pagado"), CERO_D),
        pendiente=Coalesce(Sum("saldo"), CERO_D),
    )
    pendiente = pesada(totales["pendiente"])

    # Porcentaje de lo pagado, para las barras de la ficha del cliente.
    avance = 0
    if pesados(totales["financiado"]) > 0:
        avance = int(
            (pesados(totales["pagado"]) / pesados(totales["financiado"])) * 100
        )
        avance = max(0, min(100, avance))

    return {
        "comprado": pesada(totales["comprado"]),
        "financiado": pesada(totales["financiado"]),
        "pagado": pesada(totales["pagado"]),
        "saldo": pendiente,
        "avance_pct": avance,
        "creditos_activos": creditos.filter(estado=EstadoCredito.ACTIVO).count(),
        "creditos_pagados": creditos.filter(estado=EstadoCredito.PAGADO).count(),
        "total_creditos": creditos.count(),
    }


def creditos_del_cliente(cliente_id, solo_activos=False):
    qs = Credito.objects.filter(cliente_id=cliente_id).select_related(
        "producto", "frecuencia",
    )
    if solo_activos:
        qs = qs.filter(estado=EstadoCredito.ACTIVO)
    return qs.order_by("-fecha_venta", "-id")


# ===========================================================================
# COBROS PENDIENTES (alertas)
# ===========================================================================


def cobros_pendientes(hoy=None, solo_activos=True, dias_proximos=3):
    """La lista de a quien hay que llamar hoy.

    Orden: primero el que mas dias lleva atrasado.
    """
    if hoy is None:
        hoy = timezone.localdate()

    creditos = Credito.objects.filter(estado=EstadoCredito.ACTIVO).select_related(
        "cliente", "frecuencia", "producto",
    )
    if solo_activos:
        creditos = creditos.filter(cliente__activo=True)

    # Una fila por cuota sin terminar de pagar que ya vencio o vence pronto.
    cuotas = (
        Cuota.objects
        .filter(credito__in=creditos)
        .exclude(valor_pagado__gte=F("valor"))
        .filter(fecha_vencimiento__lte=hoy + timedelta(days=dias_proximos))
        .select_related("credito", "credito__cliente")
        .order_by("fecha_vencimiento")
    )

    filas = []
    for cuota in cuotas:
        cliente = cuota.credito.cliente
        dias_faltan = (cuota.fecha_vencimiento - hoy).days
        atraso = max(0, -dias_faltan)
        if dias_faltan > 0:
            estado = "PROXIMO"
        elif atraso == 0:
            estado = "HOY"
        elif atraso <= 5:
            estado = "RECIEN"
        elif atraso <= 15:
            estado = "ATRASADO"
        else:
            estado = "MORA"

        regularidad = calcular_regularidad(cliente=cliente, hoy=hoy)
        filas.append({
            "cliente": cliente,
            "credito": cuota.credito,
            "cuota": cuota,
            "saldo_cuota": cuota.saldo,
            "atraso": atraso,
            "dias_faltan": dias_faltan,
            "estado": estado,
            # Estado real de la cuota, para pintar el color correcto.
            "estado_siguiente": cuota.estado_real(hoy),
            "regularidad": regularidad,
        })

    # De mayor atraso a menor, y dentro de cada uno, mayor saldo primero.
    filas.sort(key=lambda f: (-f["atraso"], -float(f["saldo_cuota"])))

    resumen = {
        "vencidas": [f for f in filas if f["atraso"] > 0],
        "hoy": [f for f in filas if f["atraso"] == 0 and f["dias_faltan"] == 0],
        "proximas": [f for f in filas if f["dias_faltan"] > 0],
        "total_vencido": pesada(sum(
            (f["saldo_cuota"] for f in filas if f["atraso"] > 0), CERO,
        )),
        "cantidad_vencidas": len([f for f in filas if f["atraso"] > 0]),
    }
    return filas, resumen


# ===========================================================================
# CALENDARIO
# ===========================================================================


def calendario_del_mes(anio, mes):
    """Cuotas programadas de un mes, con lo esperado y lo recibido."""
    import calendar as _calendar
    ultimo_dia = _calendar.monthrange(anio, mes)[1]
    inicio = _fecha(anio, mes, 1)
    fin = _fecha(anio, mes, ultimo_dia)

    cuotas = (
        Cuota.objects
        .filter(fecha_vencimiento__gte=inicio, fecha_vencimiento__lte=fin)
        .exclude(credito__estado=EstadoCredito.ANULADO)
        .select_related("credito", "credito__cliente")
        .order_by("fecha_vencimiento", "credito__cliente__apellidos")
    )

    dias = {}
    for dia in range(1, ultimo_dia + 1):
        fecha = _fecha(anio, mes, dia)
        dias[dia] = {
            "fecha": fecha,
            "numero": dia,
            "cuotas": [],
            "esperado": CERO,
            "recibido": CERO,
            "pendiente": CERO,
            "clientes": 0,
        }

    for cuota in cuotas:
        info = dias[cuota.fecha_vencimiento.day]
        saldo = cuota.saldo
        info["esperado"] = pesada(info["esperado"] + cuota.valor)
        if cuota.esta_pagada:
            info["recibido"] = pesada(info["recibido"] + cuota.valor)
        else:
            info["pendiente"] = pesada(info["pendiente"] + saldo)
        if cuota.credito.cliente_id not in {c.credito.cliente_id for c in info["cuotas"]}:
            info["clientes"] += 1
        info["cuotas"].append(cuota)

    return {
        "anio": anio,
        "mes": mes,
        "dias": dias,
        "total_esperado": pesada(sum((d["esperado"] for d in dias.values()), CERO)),
        "total_recibido": pesada(sum((d["recibido"] for d in dias.values()), CERO)),
        "total_pendiente": pesada(sum((d["pendiente"] for d in dias.values()), CERO)),
    }


def detalle_dia(fecha):
    """A quien hay que cobrarle en un dia exacto."""
    cuotas = (
        Cuota.objects
        .filter(fecha_vencimiento=fecha)
        .exclude(credito__estado=EstadoCredito.ANULADO)
        .select_related("credito", "credito__cliente", "credito__frecuencia")
        .order_by("credito__cliente__apellidos", "credito__cliente__nombres")
    )
    filas = []
    for cuota in cuotas:
        filas.append({
            "cuota": cuota,
            "cliente": cuota.credito.cliente,
            "credito": cuota.credito,
            "estado": cuota.estado_real(),
            "saldo": cuota.saldo,
        })
    return {
        "fecha": fecha,
        "filas": filas,
        "esperado": pesada(sum((c.valor for c in cuotas), CERO)),
        "recibido": pesada(sum((c.valor for c in cuotas if c.esta_pagada), CERO)),
        "pendiente": pesada(sum((c.saldo for c in cuotas), CERO)),
    }


# ===========================================================================
# REPORTES
# ===========================================================================


def reporte_cartera(hasta=None):
    """Cartera por cliente: quien debe, quien esta al dia, quien va atrasado."""
    config = configuracion()
    creditos = Credito.objects.filter(estado=EstadoCredito.ACTIVO).select_related(
        "cliente", "frecuencia",
    )
    clientes_ids = list(creditos.values_list("cliente_id", flat=True).distinct())
    regulares = regularidad_de_lista(clientes_ids, config)

    datos = []
    for credito in creditos:
        cliente = credito.cliente
        reg = regulares.get(cliente.id)
        filas = list(credito.cuotas.all())
        vencida = sum(
            (c.saldo for c in filas
             if c.estado_real() == EstadoCuota.VENCIDA), CERO,
        )
        datos.append({
            "credito": credito,
            "cliente": cliente,
            "saldo": credito.saldo,
            "saldo_vencido": pesada(vencida),
            "atraso": max(
                (c.dias_de_atraso for c in filas
                 if c.estado_real() == EstadoCuota.VENCIDA), default=0,
            ),
            "regularidad": reg or calcular_regularidad(cliente=cliente),
            "estado_cliente": estado_cliente(
                reg or calcular_regularidad(cliente=cliente)),
        })

    datos.sort(key=lambda f: (-f["atraso"], -float(f["saldo_vencido"]), f["cliente"].apellidos))
    return datos


def reporte_cobros(desde, hasta):
    """Todos los pagos de un rango de fechas, con filtro opcional."""
    pagos = Pago.objects.filter(
        anulado=False, fecha__gte=desde, fecha__lte=hasta,
    ).select_related("credito", "credito__cliente", "metodo")

    por_metodo = pagos.values("metodo__nombre").annotate(
        total=Sum("valor"), cantidad=Count("id")).order_by("-total")

    por_dia = pagos.values("fecha").annotate(
        total=Sum("valor"), cantidad=Count("id")).order_by("fecha")

    return {
        "desde": desde,
        "hasta": hasta,
        "pagos": pagos.order_by("-fecha", "-hora"),
        "total": pesada(pagos.aggregate(s=Sum("valor"))["s"] or 0),
        "cantidad": pagos.count(),
        "por_metodo": [(f["metodo__nombre"], pesada(f["total"]), f["cantidad"])
                       for f in por_metodo],
        "por_dia": [(f["fecha"], pesada(f["total"]), f["cantidad"])
                    for f in por_dia],
    }


def reporte_ventas(desde, hasta):
    """Creditos vendidos en un rango de fechas."""
    creditos = Credito.objects.filter(
        fecha_venta__gte=desde, fecha_venta__lte=hasta,
    ).exclude(estado=EstadoCredito.ANULADO).select_related("cliente", "frecuencia")

    return {
        "desde": desde,
        "hasta": hasta,
        "creditos": creditos.order_by("-fecha_venta"),
        "cantidad": creditos.count(),
        "total_vendido": pesada(creditos.aggregate(s=Sum("precio_financiado"))["s"] or 0),
        "total_financiado": pesada(creditos.aggregate(s=Sum("valor_financiado"))["s"] or 0),
        "total_cobrado": pesada(creditos.aggregate(s=Sum("total_pagado"))["s"] or 0),
        "total_pendiente": pesada(creditos.aggregate(s=Sum("saldo"))["s"] or 0),
    }


def clientes_atrasados():
    """Solo los clientes con cuotas vencidas, de mayor atraso a menor."""
    config = configuracion()
    hoy = timezone.localdate()
    clientes_ids = list(
        Cuota.objects.filter(fecha_vencimiento__lt=hoy)
        .exclude(valor_pagado__gte=F("valor"))
        .exclude(credito__estado=EstadoCredito.ANULADO)
        .values_list("credito__cliente_id", flat=True).distinct()
    )
    regulares = regularidad_de_lista(clientes_ids, config)
    resultado = []
    for cliente_id in clientes_ids:
        cliente = Cliente.objects.get(pk=cliente_id)
        vencidas = Cuota.objects.filter(
            credito__cliente_id=cliente_id,
            fecha_vencimiento__lt=hoy,
        ).exclude(valor_pagado__gte=F("valor"))
        atraso = max((c.dias_de_atraso for c in vencidas), default=0)
        reg = regulares.get(cliente_id) or calcular_regularidad(cliente=cliente)
        resultado.append({
            "cliente": cliente,
            "atraso": atraso,
            "cuotas_vencidas": vencidas.count(),
            "saldo_vencido": pesada(sum((c.saldo for c in vencidas), CERO)),
            "saldo_total": Cliente.objects.get(pk=cliente_id).saldo_total(),
            "regularidad": reg,
        })
    resultado.sort(key=lambda f: -f["atraso"])
    return resultado


# ===========================================================================
# BUSQUEDA GLOBAL
# ===========================================================================


def normalizar_cedula(texto):
    """'1.234.567-8' -> '12345678'. Para buscar sin importarle el formato."""
    return "".join(c for c in (texto or "") if c.isdigit())


def buscar_clientes(texto, limite=25, solo_activos=False):
    """Busqueda global por nombre, apellido o cedula.

    Si el texto son solo digitos, ademas busca por cedula aunque tenga
    puntos o guiones.
    """
    texto = (texto or "").strip()
    if len(texto) < 2:
        return Cliente.objects.none()

    qs = Cliente.objects.all()
    if solo_activos:
        qs = qs.filter(activo=True)

    condiciones = Q(nombres__icontains=texto) | Q(apellidos__icontains=texto)
    digitos = normalizar_cedula(texto)
    if digitos:
        condiciones |= Q(cedula__icontains=digitos)
    else:
        # Busqueda por palabras sueltas: "Juan Perez"
        for palabra in texto.split():
            condiciones |= Q(nombres__icontains=palabra) | Q(apellidos__icontains=palabra)

    return qs.filter(condiciones).annotate(
        n_creditos=Count("creditos", distinct=True),
    ).order_by("apellidos", "nombres")[:limite]
