"""
Datos iniciales que el sistema necesita para funcionar.

Se crean SOLO la primera vez (gracias a get_or_create), asi que se puede
llamar en cada arranque sin miedo a duplicar nada.
"""

from ..models import FrecuenciaPago, MetodoPago

# Frecuencias de pago que trae el sistema.
FRECUENCIAS = [
    # (nombre, dias, unidad, orden)
    ("DIARIO", 1, FrecuenciaPago.Unidad.DIAS, 10),
    ("SEMANAL", 7, FrecuenciaPago.Unidad.DIAS, 20),
    ("QUINCENAL", 15, FrecuenciaPago.Unidad.DIAS, 30),
    ("MENSUAL", 1, FrecuenciaPago.Unidad.MESES, 40),
    ("BIMESTRAL", 2, FrecuenciaPago.Unidad.MESES, 50),
    ("TRIMESTRAL", 3, FrecuenciaPago.Unidad.MESES, 60),
]

# Metodos de pago que trae el sistema.
METODOS = [
    ("Efectivo", 10),
    ("Transferencia", 20),
    ("Nequi", 30),
    ("Daviplata", 40),
    ("Bancolombia", 50),
    ("PSE", 60),
    ("Otro", 90),
]


def crear_catalogos_iniciales():
    """Crea las frecuencias y metodos de pago base. Idempotente."""
    creados = 0

    for nombre, dias, unidad, orden in FRECUENCIAS:
        _, nuevo = FrecuenciaPago.objects.get_or_create(
            nombre=nombre,
            defaults={"dias": dias, "unidad": unidad, "orden": orden, "activo": True},
        )
        if nuevo:
            creados += 1

    for nombre, orden in METODOS:
        _, nuevo = MetodoPago.objects.get_or_create(
            nombre=nombre,
            defaults={"orden": orden, "activo": True},
        )
        if nuevo:
            creados += 1

    return creados
