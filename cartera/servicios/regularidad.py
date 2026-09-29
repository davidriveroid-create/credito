"""
Calculo de la BARRA DE REGULARIDAD DE PAGO.

El cliente NUNCA marca su categoria a mano. Todo sale del historial real
de pagos, usando datos objectives:

    - Cuotas pagadas a tiempo
    - Cuotas pagadas despues de la fecha
    - Cuotas vencidas (y cuantos dias lleva vencidas)
    - Dias de atraso promedio y el mayor atraso
    - Porcentaje de pagos puntuales

La barra se calcula asi (es la misma del ejemplo del sistema):

    12 a tiempo + 2 con retraso + 1 vencida  ->  12 / 15 = 80%

        ████████████████░░░░ 80%

Todos los umbrales salen de Configuracion, asi que el administrador los
cambia sin tocar el codigo.
"""

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from ..models import CERO, Configuracion, Cuota, EstadoCuota, pesada

# Categorias, de mejor a peor.
EXCELENTE = "EXCELENTE"
BUENO = "BUENO"
IRREGULAR = "IRREGULAR"
ATRASADO = "ATRASADO"
MOROSO = "MOROSO"
SIN_DATOS = "SIN_DATOS"

# Colores de la barra para cada categoria (se pueden cambiar en Configuracion).
COLORES = {
    EXCELENTE: "#16a34a",
    BUENO: "#65a30d",
    IRREGULAR: "#eab308",
    ATRASADO: "#f97316",
    MOROSO: "#dc2626",
    SIN_DATOS: "#94a3b8",
}

ICONOS = {
    EXCELENTE: "excelente",
    BUENO: "bueno",
    IRREGULAR: "irregular",
    ATRASADO: "atrasado",
    MOROSO: "moroso",
    SIN_DATOS: "sin-datos",
}


def configuracion():
    """Devuelve la fila unica de Configuracion, creandola si no existe."""
    config, _ = Configuracion.objects.get_or_create(
        pk=1, defaults={"nombre_negocio": "Mi Negocio"},
    )
    return config


# ===========================================================================
# CALCULO
# ===========================================================================


def calcular_regularidad(credito=None, cliente=None, hoy=None, config=None):
    """Calcula el perfil de pago de un credito o de todo un cliente.

    Devuelve un diccionario con los numeros crudos y la categoria.
    """
    if hoy is None:
        hoy = timezone.localdate()
    if config is None:
        config = configuracion()

    cuotas = _cuotas_de(credito, cliente)

    dias_gracia = timedelta(days=config.dias_gracia)

    a_tiempo = 0
    con_retraso = 0
    vencidas = 0
    pendientes = 0
    parciales = 0
    atrasos = []          # dias de atraso de las cuotas ya pagadas tarde
    atraso_vigente = 0    # atraso de las cuotas que hoy siguen sin pagar
    valor_vencido = CERO

    for cuota in cuotas:
        pagada = cuota.valor_pagado >= cuota.valor
        # Vencio o no: se mira con la gracia configurada.
        vencido_real = hoy > cuota.fecha_vencimiento + dias_gracia

        if pagada:
            fecha_pago = cuota.fecha_pago or cuota.fecha_ultimo_abono
            if fecha_pago and fecha_pago > cuota.fecha_vencimiento + dias_gracia:
                con_retraso += 1
                atrasos.append((fecha_pago - cuota.fecha_vencimiento).days)
            else:
                a_tiempo += 1
        else:
            if vencido_real:
                vencidas += 1
                atraso_vigente = max(
                    atraso_vigente,
                    (hoy - cuota.fecha_vencimiento).days,
                )
                valor_vencido = pesada(valor_vencido + cuota.saldo)
            elif cuota.valor_pagado > CERO:
                parciales += 1
            else:
                pendientes += 1

    # Cuotas que cuentan para el porcentaje: las que ya se cobraron mas las
    # que estan vencidas. Las que todavia no vencen no cuentan (no es justo
    # castigar a alguien por algo que todavia no era para hoy).
    evaluadas = a_tiempo + con_retraso + vencidas

    if evaluadas > 0:
        porcentaje = round((a_tiempo / evaluadas) * 100)
    else:
        porcentaje = 100 if (pendientes + parciales) == 0 and not cuotas else 0

    if not cuotas or evaluadas < config.minimo_cuotas_para_clasificar:
        categoria = SIN_DATOS
        porcentaje_mostrado = porcentaje if cuotas else 0
    else:
        categoria = _clasificar(
            porcentaje=porcentaje,
            vencidas=vencidas,
            atraso_vigente=atraso_vigente,
            atraso_promedio=_promedio(atrasos),
            config=config,
        )
        porcentaje_mostrado = porcentaje

    return {
        "porcentaje": porcentaje_mostrado,
        "barra": _barra_texto(porcentaje_mostrado),
        "categoria": categoria,
        "color": COLORES.get(categoria, COLORES[SIN_DATOS]),
        "icono": ICONOS.get(categoria, ICONOS[SIN_DATOS]),
        "etiqueta": ETIQUETAS.get(categoria, categoria),
        # Numeros que se muestran al lado de la barra
        "a_tiempo": a_tiempo,
        "con_retraso": con_retraso,
        "vencidas": vencidas,
        "parciales": parciales,
        "pendientes": pendientes,
        "total_cuotas": len(cuotas),
        "evaluadas": evaluadas,
        "atraso_promedio": _promedio(atrasos),
        "atraso_maximo": max(atrasos) if atrasos else atraso_vigente,
        "atraso_vigente": atraso_vigente,
        "valor_vencido": valor_vencido,
        "explicacion": _explicar(
            categoria, porcentaje_mostrado, a_tiempo, con_retraso,
            vencidas, atraso_vigente,
        ),
    }


ETIQUETAS = {
    EXCELENTE: "Excelente",
    BUENO: "Bueno",
    IRREGULAR: "Irregular",
    ATRASADO: "Atrasado",
    MOROSO: "Moroso",
    SIN_DATOS: "Sin datos",
}


def _cuotas_de(credito=None, cliente=None):
    """Trae las cuotas a analizar, segun lo que se pida."""
    base = Cuota.objects.select_related("credito").order_by(
        "credito_id", "numero",
    )
    if credito is not None:
        if isinstance(credito, (list, tuple)):
            ids = [c.pk for c in credito]
            return list(base.filter(credito_id__in=ids))
        return list(base.filter(credito=credito))
    if cliente is not None:
        return list(base.filter(credito__cliente=cliente))
    return []


def _clasificar(porcentaje, vencidas, atraso_vigente, atraso_promedio, config):
    """Aplica los umbrales de Configuracion para decidir la categoria."""
    if vencidas == 0:
        if porcentaje >= config.umbral_excelente:
            return EXCELENTE
        if porcentaje >= config.umbral_bueno:
            return BUENO
        return IRREGULAR

    # Con cuotas vencidas: la severidad la marca cuantos dias lleva atrás.
    if atraso_vigente >= config.dias_para_moroso:
        return MOROSO
    return ATRASADO


def _promedio(lista):
    if not lista:
        return 0
    return round(sum(lista) / len(lista), 1)


def _barra_texto(porcentaje, largo=20):
    """Dibuja la barra de texto:  ████████████████░░░░ 80%"""
    porcentaje = max(0, min(100, porcentaje))
    llenos = int(round(largo * porcentaje / 100))
    return "█" * llenos + "░" * (largo - llenos)


def _explicar(categoria, porcentaje, a_tiempo, retraso, vencidas, atraso):
    """Texto corto que explica por que quedo asi. Se muestra bajo la barra."""
    if categoria == SIN_DATOS:
        return "Todavia no hay suficientes cuotas cobradas para clasificarlo."
    if categoria == EXCELENTE:
        return f"{a_tiempo} cuotas pagadas a tiempo. Sin atrasos."
    if categoria == BUENO:
        base = f"{a_tiempo} a tiempo y {retraso} con retraso."
        return base + (" Sin cuotas vencidas." if not vencidas else "")
    if categoria == IRREGULAR:
        return f"{retraso} cuotas pagadas tarde. Ninguna vencida todavia."
    if categoria == ATRASADO:
        return (f"{vencidas} cuota(s) vencida(s), la mas antigua con "
                f"{atraso} dia(s) de atraso.")
    return (f"{vencidas} cuota(s) vencida(s) y {atraso} dia(s) de atraso. "
            f"Necesita seguimiento ya.")


# ===========================================================================
# RESUMEN PARA LISTAS
# ===========================================================================


def regularidad_de_lista(clientes_ids, config=None):
    """Calcula la regularidad de varios clientes de una sola vez.

    Sirve para las pantallas de clientes y de cobranza, donde pintar
    una barra por fila sin consultar la base N veces.
    """
    if config is None:
        config = configuracion()
    if not clientes_ids:
        return {}

    hoy = timezone.localdate()
    dias_gracia = timedelta(days=config.dias_gracia)

    from collections import defaultdict
    cuentas = defaultdict(lambda: {
        "a_tiempo": 0, "con_retraso": 0, "vencidas": 0,
        "pendientes": 0, "parciales": 0, "atrasos": [],
        "atraso_vigente": 0, "total": 0, "valor_vencido": CERO,
    })

    cuotas = (
        Cuota.objects
        .filter(credito__cliente_id__in=clientes_ids)
        .select_related("credito")
        .order_by("credito_id", "numero")
    )

    for cuota in cuotas.iterator(chunk_size=500):
        cuenta = cuentas[cuota.credito.cliente_id]
        cuenta["total"] += 1
        pagada = cuota.valor_pagado >= cuota.valor
        vencido_real = hoy > cuota.fecha_vencimiento + dias_gracia

        if pagada:
            fecha_pago = cuota.fecha_pago or cuota.fecha_ultimo_abono
            if fecha_pago and fecha_pago > cuota.fecha_vencimiento + dias_gracia:
                cuenta["con_retraso"] += 1
                cuenta["atrasos"].append((fecha_pago - cuota.fecha_vencimiento).days)
            else:
                cuenta["a_tiempo"] += 1
        elif vencido_real:
            cuenta["vencidas"] += 1
            cuenta["atraso_vigente"] = max(
                cuenta["atraso_vigente"],
                (hoy - cuota.fecha_vencimiento).days,
            )
            cuenta["valor_vencido"] = pesada(
                cuenta["valor_vencido"] + cuota.saldo,
            )
        elif cuota.valor_pagado > CERO:
            cuenta["parciales"] += 1
        else:
            cuenta["pendientes"] += 1

    resultados = {}
    for cliente_id, cuenta in cuentas.items():
        evaluadas = cuenta["a_tiempo"] + cuenta["con_retraso"] + cuenta["vencidas"]
        if evaluadas > 0:
            porcentaje = round((cuenta["a_tiempo"] / evaluadas) * 100)
        else:
            porcentaje = 100 if cuenta["total"] == 0 else 0

        if cuenta["total"] == 0 or evaluadas < config.minimo_cuotas_para_clasificar:
            categoria = SIN_DATOS
            porcentaje_mostrado = porcentaje if cuenta["total"] else 0
        else:
            categoria = _clasificar(
                porcentaje, cuenta["vencidas"], cuenta["atraso_vigente"],
                _promedio(cuenta["atrasos"]), config,
            )
            porcentaje_mostrado = porcentaje

        atraso_max = max(cuenta["atrasos"]) if cuenta["atrasos"] else cuenta["atraso_vigente"]
        resultados[cliente_id] = {
            "porcentaje": porcentaje_mostrado,
            "barra": _barra_texto(porcentaje_mostrado),
            "categoria": categoria,
            "color": COLORES.get(categoria, COLORES[SIN_DATOS]),
            "icono": ICONOS.get(categoria, ICONOS[SIN_DATOS]),
            "etiqueta": ETIQUETAS.get(categoria, categoria),
            "a_tiempo": cuenta["a_tiempo"],
            "con_retraso": cuenta["con_retraso"],
            "vencidas": cuenta["vencidas"],
            "parciales": cuenta["parciales"],
            "pendientes": cuenta["pendientes"],
            "total_cuotas": cuenta["total"],
            "evaluadas": evaluadas,
            "atraso_promedio": _promedio(cuenta["atrasos"]),
            "atraso_maximo": atraso_max,
            "atraso_vigente": cuenta["atraso_vigente"],
            "valor_vencido": cuenta["valor_vencido"],
            "explicacion": _explicar(
                categoria, porcentaje_mostrado, cuenta["a_tiempo"],
                cuenta["con_retraso"], cuenta["vencidas"],
                cuenta["atraso_vigente"],
            ),
        }

    return resultados


# ===========================================================================
# ESTADO GENERAL DEL CLIENTE (al dia / con atraso / en mora)
# ===========================================================================


def estado_cliente(regularidad):
    """Traduce la regularidad al estado que se ve en las listas."""
    categoria = regularidad["categoria"]
    if categoria in (ATRASADO, MOROSO):
        return "MORA" if categoria == MOROSO else "ATRASADO"
    if categoria == SIN_DATOS:
        return "SIN_DATOS"
    return "AL_DIA"
