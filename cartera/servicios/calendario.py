"""
Logica del calendario de pagos.

Este archivo decide DOS cosas importantes:

1. Cada cuando vence una cuota (diario, semanal, quincenal, mensual...).
2. Como se reparte el valor financiado en cuotas que sumen EXACTAMENTE
   lo que el cliente debe, sin que sobren ni falten pesos.

Regla de oro: la suma de las cuotas SIEMPRE es igual al saldo financiado.
Si se pierde o sobra un peso, el cliente termina debiendo de mas o el
sistema muestra que ya esta pagado cuando no es cierto.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from ..models import CERO, EstadoCuota, pesada
from .dinero import formato_dinero


class ErrorCalculo(Exception):
    """Se lanza cuando los numeros del credito no cuadran."""


def sumar_frecuencia(fecha, frecuencia, veces=1):
    """Suma `veces` intervalos a una fecha.

    - Frecuencia en DIAS: suma exacta de dias (7 dias = una semana).
    - Frecuencia en MESES: suma meses de calendario. Si la fecha es 31 de
      enero y se suma un mes, da 28 o 29 de febrero (el ultimo dia del
      mes), no un dia que no existe. Asi el pago mensual nunca cae en
      una fecha imposible.
    """
    if veces == 0:
        return fecha

    if frecuencia.unidad == frecuencia.Unidad.MESES:
        total_meses = fecha.month - 1 + (frecuencia.dias * veces)
        anio = fecha.year + total_meses // 12
        mes = total_meses % 12 + 1
        dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
        return date(anio, mes, dia)

    salto = timedelta(days=frecuencia.dias * veces)
    return fecha + salto


def calcular_valor_cuota(saldo_financiado, numero_cuotas, redondeo=10):
    """Divide el saldo en cuotas iguales y devuelve el valor de cada una.

    Se redondea a multiplos de 10 pesos (los centavos no existen en pesos
    colombianos). La diferencia que produce el redondeo se corrige sola en
    la ultima cuota: ver `generar_plan_pagos`.
    """
    if numero_cuotas <= 0:
        raise ErrorCalculo("El numero de cuotas debe ser mayor que cero.")

    saldo = pesada(saldo_financiado)
    if saldo <= CERO:
        raise ErrorCalculo("El saldo a financiar debe ser mayor que cero.")

    paso = Decimal(redondeo)
    valor = (saldo / Decimal(numero_cuotas)).quantize(paso, rounding=ROUND_HALF_UP)
    if valor <= CERO:
        # Saldo tan pequeno que al repartir no alcanza ni para un peso
        # redondeado. Se cobra en las cuotas que si queden.
        valor = pesada(saldo / Decimal(numero_cuotas))
        if valor <= CERO:
            raise ErrorCalculo(
                f"El saldo de {formato_dinero(saldo)} no alcanza para dividirlo en "
                f"{numero_cuotas} cuotas. Baje el numero de cuotas o aumente el saldo."
            )
    return valor


def calcular_fechas(fecha_primera, frecuencia, numero_cuotas):
    """Devuelve la lista de fechas de vencimiento, cuota 1 hasta la ultima."""
    fechas = []
    for indice in range(numero_cuotas):
        fechas.append(sumar_frecuencia(fecha_primera, frecuencia, indice))
    return fechas


def generar_plan_pagos(saldo_financiado, numero_cuotas, fecha_primera,
                       frecuencia, valor_cuota_manual=None, redondeo=10):
    """Arma el plan de pagos completo.

    Devuelve una lista de diccionarios:
        [{'numero': 1, 'fecha': date(...), 'valor': Decimal}, ...]

    Si se pasa `valor_cuota_manual`, se respeta ese valor y la diferencia
    se ajusta en la ULTIMA cuota para que la suma sea exacta.

    Si NO se pasa, el sistema divide solo y ajusta la ultima cuota.
    """
    saldo = pesada(saldo_financiado)
    if numero_cuotas <= 0:
        raise ErrorCalculo("El numero de cuotas debe ser mayor que cero.")
    if saldo <= CERO:
        raise ErrorCalculo("El saldo a financiar debe ser mayor que cero.")

    fechas = calcular_fechas(fecha_primera, frecuencia, numero_cuotas)

    if valor_cuota_manual is not None:
        valor_base = pesada(valor_cuota_manual)
        if valor_base <= CERO:
            raise ErrorCalculo("El valor de la cuota debe ser mayor que cero.")
    else:
        valor_base = calcular_valor_cuota(saldo, numero_cuotas, redondeo)

    # Ajuste final: la ultima cuota absorbe la diferencia de redondeo.
    suma_primeras = valor_base * (numero_cuotas - 1)
    valor_ultima = pesada(saldo - suma_primeras)
    if valor_ultima < CERO:
        # Raro: pasa si el valor manual se paso. Se reparte el exceso.
        valor_base = calcular_valor_cuota(saldo, numero_cuotas, redondeo)
        valor_ultima = pesada(saldo - valor_base * (numero_cuotas - 1))
        if valor_ultima < CERO:
            valor_base, valor_ultima = _repartir_exceso(saldo, numero_cuotas, valor_base)

    plan = []
    for indice, fecha in enumerate(fechas):
        valor = valor_ultima if indice == numero_cuotas - 1 else valor_base
        plan.append({
            "numero": indice + 1,
            "fecha": fecha,
            "valor": valor,
        })
    return plan, valor_base, valor_ultima


def _repartir_exceso(saldo, numero_cuotas, valor_base):
    """Ultimo recurso: reparte un peso sobrante entre las cuotas."""
    diferencia = pesada(saldo - valor_base * numero_cuotas)
    cuota_con_diferencia = numero_cuotas - (1 if diferencia < 0 else 0)
    ultima = pesada(valor_base + diferencia)
    if ultima < CERO:
        raise ErrorCalculo("No se pudo armar el plan de pagos con esos numeros.")
    return valor_base, ultima


def resumen_plan(plan):
    """Para mostrar en pantalla: total, cantidad y promedios."""
    total = sum((p["valor"] for p in plan), CERO)
    return {
        "cantidad": len(plan),
        "total": pesada(total),
        "primera": plan[0]["fecha"] if plan else None,
        "ultima": plan[-1]["fecha"] if plan else None,
        "valor_ultima": plan[-1]["valor"] if plan else CERO,
    }
