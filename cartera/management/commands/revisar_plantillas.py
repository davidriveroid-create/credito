"""
Revisa que cada plantilla use la libreria de etiquetas del sistema.

Todas las ayudas de presentacion (pesos, fechas, barras) viven en la
libreria 'formato' de cartera/templatetags/formato.py. Como son
etiquetas y no filtros, no hay que definirlas antes de usarlas, pero si
falta el {% load formato %} la pantalla no abre.

Este comando avisa si alguna plantilla se quedo sin la linea, para que no
se descubra con un usuario mirando.

Uso:
    .venv\\Scripts\\python.exe manage.py revisar_plantillas
"""

import os
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.backends.django import get_installed_libraries

# Etiquetas que define la libreria 'formato'.
ETIQUETAS = [
    "pesos", "numero", "en_letras", "fecha", "fecha_larga", "reloj",
    "momento", "relativo", "color_estado", "icono_estado", "nombre_estado",
    "color_categoria", "etiqueta_categoria", "clave", "avance",
    "cedula_oculta", "barra_regularidad", "barra_porcentaje", "puntos_barras",
]

RUTAS_IGNORADAS = ("compilado-estatico", ".venv", "__pycache__")

COMENTARIOS = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)


class Command(BaseCommand):
    help = "Revisa que las plantillas carguen la libreria de etiquetas propia."

    def handle(self, *args, **opciones):
        carpeta = Path(settings.BASE_DIR) / "plantillas"

        nombre = None
        for clave, ruta in get_installed_libraries().items():
            if ruta.endswith("cartera.templatetags.formato"):
                nombre = clave
                break

        if not nombre:
            self.stdout.write(self.style.ERROR(
                "No se encontro la libreria de plantillas 'formato'."
            ))
            return

        carga = "{%% load %s %%}" % nombre
        problemas = []
        revisadas = 0

        for carpeta_padre, _, archivos in os.walk(carpeta):
            if any(parte in carpeta_padre for parte in RUTAS_IGNORADAS):
                continue
            for nombre_archivo in sorted(archivos):
                if not nombre_archivo.endswith(".html"):
                    continue
                revisadas += 1
                ruta = os.path.join(carpeta_padre, nombre_archivo)
                texto = COMENTARIOS.sub(
                    "", open(ruta, encoding="utf-8").read())

                usa = any(
                    re.search(r"\{%\s*" + etiqueta + r"\b", texto)
                    for etiqueta in ETIQUETAS
                )
                if usa and carga not in texto:
                    problemas.append(os.path.relpath(ruta, settings.BASE_DIR))

        self.stdout.write(f"Plantillas revisadas: {revisadas}")

        if not problemas:
            self.stdout.write(self.style.SUCCESS(
                f"Todas cargan bien la libreria '{nombre}'."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"Falta '{{% load {nombre} %}}' en {len(problemas)} plantilla(s):"
        ))
        for problema in problemas:
            self.stdout.write(f"  - {problema}")
        raise SystemExit(1)
