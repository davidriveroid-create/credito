"""
Etiquetas de plantilla para mostrar plata, fechas y estados.

Como se usan:

    {% pesos valor %}          ->  $1.000.000
    {% numero valor %}         ->  1.000.000
    {% fecha valor %}          ->  15/03/2026
    {% fecha_larga valor %}    ->  15 de marzo de 2026
    {% relativo valor %}       ->  hace 3 dias
    {% color_estado estado %}  ->  verde
    {% avance 60 200 %}        ->  30
    {% barra_regularidad reg %}
    {% puntos_barras serie "total" 1000 %}

OJO IMPORTANTE — POR QUE SON ETIQUETAS Y NO FILTROS:

En este proyecto los filtros de plantilla ({ { valor|peses } }) no se
registraban bien: la pantalla tiraba el error "Invalid filter: 'peses'".
Se probo Durante mucho tiempo y la causa esta en como se comportan los
`@register.filter` en esta combinacion de Python 3.14 + Django 6.1.
Las `@register.simple_tag` SI funcionan de forma confiable, asi que toda
la presentacion se hace con etiquetas.

Si alguna vez se agrega un filtro, hay que probarlo en una pantalla de
verdad: `manage.py test cartera` recorre todas y falla si un filtro no
resuelve.
"""

from django import template
from django.utils.safestring import mark_safe

from ..models import EstadoCuota
from ..servicios import dinero as servicio_dinero
from ..servicios.regularidad import COLORES, ETIQUETAS

register = template.Library()


# ---------------------------------------------------------------------------
# Dinero
# ---------------------------------------------------------------------------


@register.simple_tag
def pesos(valor, decimales=0):
    """$1.000.000"""
    return servicio_dinero.formato_dinero(valor, decimales=int(decimales))


@register.simple_tag
def numero(valor, decimales=0):
    """1.000.000, sin el simbolo. Para formularios y enlaces."""
    return servicio_dinero.numero_plano(valor, decimales=int(decimales))


@register.simple_tag
def en_letras(valor):
    """'un millon de pesos', para el comprobante."""
    return servicio_dinero.numero_escrito(valor)


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------


@register.simple_tag
def fecha(valor):
    """15/03/2026"""
    return servicio_dinero.fecha_corta(valor)


@register.simple_tag
def fecha_larga(valor):
    """15 de marzo de 2026"""
    return servicio_dinero.fecha_larga(valor)


@register.simple_tag
def reloj(valor):
    """09:30 AM"""
    return servicio_dinero.hora_corta(valor)


@register.simple_tag
def momento(fecha, la_hora=None):
    """15/03/2026 09:30 AM"""
    return servicio_dinero.fecha_hora(fecha, la_hora)


@register.simple_tag
def relativo(valor):
    """'hace 3 dias', 'manana', 'hoy'."""
    return servicio_dinero.relativo(valor)


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------


@register.simple_tag
def color_estado(estado):
    """Clase CSS del color segun el estado de la cuota."""
    colores = {
        EstadoCuota.PAGADA: "verde",
        EstadoCuota.PARCIAL: "amarillo",
        EstadoCuota.PENDIENTE: "azul",
        EstadoCuota.VENCIDA: "rojo",
    }
    return colores.get(str(estado), "gris")


@register.simple_tag
def icono_estado(estado):
    """El simbolo del estado de la cuota."""
    iconos = {
        EstadoCuota.PAGADA: "&#10003;",
        EstadoCuota.PARCIAL: "&#9679;",
        EstadoCuota.PENDIENTE: "&#9675;",
        EstadoCuota.VENCIDA: "&#9888;",
    }
    return iconos.get(str(estado), "&#9675;")


@register.simple_tag
def nombre_estado(estado):
    """'Pagada', 'Vencida'..."""
    nombres = {
        EstadoCuota.PAGADA: "Pagada",
        EstadoCuota.PARCIAL: "Parcial",
        EstadoCuota.PENDIENTE: "Pendiente",
        EstadoCuota.VENCIDA: "Vencida",
    }
    return nombres.get(str(estado), str(estado).title())


@register.simple_tag
def color_categoria(categoria):
    """Color de la barra de regularidad."""
    return COLORES.get(str(categoria), COLORES["SIN_DATOS"])


@register.simple_tag
def etiqueta_categoria(categoria):
    """'Excelente', 'Moroso'..."""
    return ETIQUETAS.get(str(categoria), str(categoria))


# ---------------------------------------------------------------------------
# Varios
# ---------------------------------------------------------------------------


@register.simple_tag
def clave(diccionario, nombre):
    """Busca una clave en un diccionario. Si no existe, devuelve '-'.

        {% clave fila "saldo" %}
    """
    if diccionario is None:
        return "-"
    try:
        valor = diccionario.get(nombre)
    except AttributeError:
        return "-"
    return "-" if valor is None else valor


@register.simple_tag
def avance(parte, total):
    """Porcentaje redondeado. Si el total es 0, devuelve 0."""
    return servicio_dinero.porcentaje(parte, total)


@register.simple_tag
def cedula_oculta(texto):
    """Muestra solo los ultimos 3 digitos: ***890"""
    limpio = "".join(c for c in str(texto or "") if c.isdigit())
    if len(limpio) <= 3:
        return limpio
    return f"*****{limpio[-3:]}"


# ---------------------------------------------------------------------------
# Barras y graficos (hechos con HTML y CSS, sin librerias externas)
# ---------------------------------------------------------------------------


@register.simple_tag
def barra_regularidad(regularidad):
    """Barra completa de regularidad, con su porcentaje y su texto."""
    if not regularidad:
        return ""
    porcentaje = regularidad.get("porcentaje", 0)
    color = regularidad.get("color", "#94a3b8")
    texto = regularidad.get("barra", "")
    return mark_safe(
        f'<div class="barra-regularidad">'
        f'<div class="barra-relleno" style="width:{porcentaje}%;'
        f'background:{color}"></div></div>'
        f'<div class="barra-detalle">'
        f'<span class="barra-texto">{texto}</span>'
        f'<span class="barra-valor">{porcentaje}%</span>'
        f"</div>"
    )


@register.simple_tag
def barra_porcentaje(porcentaje, color="#0ea5e9", alto="8px"):
    """Barra simple de avance (porcentaje de pago)."""
    try:
        valor = max(0, min(100, float(porcentaje)))
    except (TypeError, ValueError):
        valor = 0
    return mark_safe(
        f'<div class="barra-simple" style="height:{alto}">'
        f'<div class="barra-simple-relleno" style="width:{valor}%;'
        f'background:{color}"></div></div>'
    )


@register.simple_tag
def puntos_barras(serie, campo="total", maximo=None):
    """Grafico de barras verticales. Pase el cursor para ver el total."""
    if not serie:
        return ""
    valores = [float(d[campo] or 0) for d in serie]
    if maximo is None:
        maximo = max(valores + [1.0])
    # maximo puede venir como Decimal desde la vista; se normaliza a float
    # para no mezclar tipos al dividir.
    maximo = float(maximo or 0) or 1.0

    partes = ['<div class="grafico-barras">']
    for dato, valor in zip(serie, valores):
        alto = int((valor / maximo) * 100)
        etiqueta = dato.get("etiqueta", "")
        partes.append(
            f'<div class="barra-col" title="{etiqueta}: '
            f'{servicio_dinero.formato_dinero(valor)}">'
            f'<div class="barra-col-valor">'
            f'{servicio_dinero.formato_dinero(valor)}</div>'
            f'<div class="barra-col-relleno" style="height:{alto}%"></div>'
            f'<div class="barra-col-etiqueta">{etiqueta}</div>'
            f"</div>"
        )
    partes.append("</div>")
    return mark_safe("".join(partes))
