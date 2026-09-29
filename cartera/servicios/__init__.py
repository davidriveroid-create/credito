"""
Capa de logica de negocio del sistema de ventas a credito.

Aqui vive TODO el calculo. Las vistas solo pintan lo que estos modulos
devuelven, para que las reglas del negocio esten en un solo sitio:

    calendario.py  -> cuando vence cada cuota y como se reparten
    cuotas.py      -> crear el plan de pagos y recalcular saldos
    pagos.py       -> registrar abonos, parciales, anticipos, idempotencia
    regularidad.py -> la barra de comportamiento de pago del cliente
    cartera.py     -> los numeros del dashboard, alertas y reportes
    documentos.py  -> fotos de cedula protegidas
    respaldo.py    -> copias de seguridad de la base
    dinero.py      -> formato de pesos colombianos y fechas
"""

from . import calendario, cartera, cuotas, dinero, documentos, pagos, regularidad, respaldo  # noqa

__all__ = [
    "calendario", "cartera", "cuotas", "dinero", "documentos",
    "pagos", "regularidad", "respaldo",
]
