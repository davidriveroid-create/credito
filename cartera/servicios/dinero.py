"""
Formato de plata y fechas en pesos colombianos.

Regla: los pesos colombianos NO usan decimales. Un peso es un peso.
    $1.000.000     y no    $1.000.000,00
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

MONEDA_SIMBOLO = "$"
SEPARADOR_MILES = "."


def _a_numero(valor):
    """Convierte cualquier entrada a Decimal sin que se rompa."""
    try:
        return Decimal(str(valor if valor is not None else 0))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal("0")


def _con_separadores(numero, decimales=0):
    """1.000.000 — el formato colombiano, sin depender del locale del sistema.

    Se hace a mano porque el separador de miles de Python depende del
    idioma del Windows y salia con coma (1,000,000) en vez de punto.
    """
    negativo = numero < 0
    numero = abs(numero)

    if decimales:
        texto = f"{numero:.{decimales}f}"
        entero, _, fraccion = texto.partition(".")
    else:
        entero = f"{numero:.0f}"
        fraccion = ""

    # Se agrupan de tres en tres desde la derecha.
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    entero = SEPARADOR_MILES.join(g for g in grupos if g != "")

    salida = f"{entero},{fraccion}" if fraccion else entero
    return f"-{salida}" if negativo else salida


def formato_dinero(valor, simbolo=True, decimales=0):
    """$1.000.000"""
    numero = _a_numero(valor)
    texto = _con_separadores(numero, decimales)
    return f"{MONEDA_SIMBOLO}{texto}" if simbolo else texto


def numero_plano(valor, decimales=0):
    """1.000.000 (sin el simbolo). Para campos de formulario y Excel."""
    return _con_separadores(_a_numero(valor), decimales)


def numero_escrito(valor):
    """1.000.000 -> 'un millón de pesos' (solo para el comprobante)."""
    try:
        numero = int(Decimal(str(valor or 0)))
    except (TypeError, ValueError):
        return ""
    if numero == 0:
        return "cero pesos"

    unidades = [
        "", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
        "nueve", "diez", "once", "doce", "trece", "catorce", "quince",
        "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte",
    ]
    decenas = [
        "", "", "veinte", "treinta", "cuarenta", "cincuenta", "sesenta",
        "setenta", "ochenta", "noventa",
    ]
    centenas = [
        "", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos",
        "seiscientos", "setecientos", "ochocientos", "novecientos",
    ]

    def tres(n):
        partes = []
        if n // 100:
            pre = "un" if n // 100 == 1 else ""
            partes.append(centenas[n // 100])
        resto = n % 100
        if resto:
            if resto < 30:
                partes.append(unidades[resto])
            else:
                d = decenas[resto // 10]
                u = resto % 10
                partes.append(f"{d} y {unidades[u]}" if u else d)
        return " ".join(p for p in partes if p)

    millones = numero // 1_000_000
    miles = (numero % 1_000_000) // 1000
    resto = numero % 1000

    textos = []
    if millones:
        # "un millon", no "uno de millones".
        cabecera = "un millon" if millones == 1 else f"{tres(millones)} millones"
        textos.append(cabecera)
    if miles:
        # "mil", no "un mil".
        textos.append("mil" if miles == 1 else f"{tres(miles)} mil")
    if resto:
        textos.append(tres(resto))
    return " ".join(textos) + " pesos"


def fecha_corta(fecha):
    """15/03/2026"""
    if not fecha:
        return "-"
    if isinstance(fecha, str):
        return fecha
    return fecha.strftime("%d/%m/%Y")


def fecha_larga(fecha):
    """15 de marzo de 2026"""
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    if not fecha:
        return "-"
    if isinstance(fecha, str):
        return fecha
    return f"{fecha.day} de {meses[fecha.month - 1]} de {fecha.year}"


def hora_corta(hora):
    if not hora:
        return "-"
    return hora.strftime("%I:%M %p").lstrip("0")


def fecha_hora(fecha, hora=None):
    if not fecha:
        return "-"
    texto = fecha_corta(fecha)
    if hora:
        return f"{texto} {hora_corta(hora)}"
    return texto


def relativo(fecha):
    """'hace 3 dias', 'manana', 'hoy'."""
    if not fecha:
        return "-"
    if isinstance(fecha, str):
        return fecha
    # Acepta fechas con hora (DateTimeField) y sin ella (DateField).
    if isinstance(fecha, datetime):
        fecha = fecha.date()

    hoy = timezone.localdate()
    dias = (fecha - hoy).days
    if dias == 0:
        return "hoy"
    if dias == 1:
        return "manana"
    if dias == -1:
        return "ayer"
    if dias > 1:
        return f"en {dias} dias"
    return f"hace {abs(dias)} dias"


def porcentaje(parte, total):
    if not total:
        return 0
    return round((Decimal(str(parte)) / Decimal(str(total))) * 100)
