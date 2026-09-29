"""
Vistas del sistema de ventas a credito y cobranza.

Se separaron por modulo para que cada archivo sea corto y manejable:

    acceso.py       -> entrar, salir, cambiar contrasena
    dashboard.py    -> pantalla de inicio con los numeros
    clientes.py     -> clientes, ficha, cedula
    creditos.py     -> ventas a credito y sus cuotas
    cobranza.py     -> registrar pagos, comprobante, historiales
    alertas.py      -> cobros pendientes
    calendario.py   -> agenda de cobros por dia
    reportes.py     -> reportes y exportaciones
    configuracion.py-> ajustes del sistema, usuarios, respaldos
    api.py          -> busqueda rapida para el formulario de cobro
"""

from . import (  # noqa
    acceso, alertas, api, calendario, clientes, cobranza, configuracion,
    creditos, dashboard, errores, reportes,
)

__all__ = [
    "acceso", "alertas", "api", "calendario", "clientes", "cobranza",
    "configuracion", "creditos", "dashboard", "errores", "reportes",
]
