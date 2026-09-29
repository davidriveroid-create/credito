"""
Crea un respaldo de la base de datos desde la linea de comandos.

Uso:
    .venv\\Scripts\\python.exe manage.py respaldar
    .venv\\Scripts\\python.exe manage.py respaldar --carpeta D:\\respaldos
    .venv\\Scripts\\python.exe manage.py respaldar --listar
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cartera.servicios import respaldo as servicio


class Command(BaseCommand):
    help = "Crea una copia de seguridad de la base de datos de creditos."

    def add_arguments(self, parser):
        parser.add_argument("--carpeta", default=None,
                            help="Carpeta donde dejar el archivo.")
        parser.add_argument("--listar", action="store_true",
                            help="Muestra los respaldos existentes y sale.")
        parser.add_argument("--conservar", type=int, default=20,
                            help="Cuantos respaldos viejos se guardan (20).")

    def handle(self, *args, **opciones):
        if opciones["listar"]:
            lista = servicio.listar_respaldos()
            if not lista:
                self.stdout.write("No hay respaldos todavia.")
                return
            self.stdout.write(f"Respaldos en {settings.CARPETA_RESPALDOS}:")
            for item in lista:
                tamano = item["tamaño"] / 1024 / 1024
                self.stdout.write(
                    f"  {item['nombre']}  {tamano:.2f} MB  "
                    f"{item['fecha']:%Y-%m-%d %H:%M}"
                )
            return

        destino = None
        if opciones["carpeta"]:
            destino = Path(opciones["carpeta"]) / servicio.nombre_archivo()
            destino.parent.mkdir(parents=True, exist_ok=True)

        try:
            resultado = servicio.crear_respaldo(
                destino=destino, usuario=None, limpiar=False,
            )
            borrados = servicio.limpiar_antiguos(conservar=opciones["conservar"])
        except Exception as error:
            raise CommandError(f"No se pudo hacer el respaldo: {error}") from error

        self.stdout.write(self.style.SUCCESS("Respaldo creado."))
        self.stdout.write(f"  Archivo:  {resultado['nombre']}")
        self.stdout.write(f"  Tamanio:  {resultado['tamaño'] / 1024 / 1024:.2f} MB")
        self.stdout.write(f"  Clientes: {resultado['clientes']}")
        self.stdout.write(f"  Creditos: {resultado['creditos']}")
        self.stdout.write(f"  Pagos:    {resultado['pagos']}")
        if borrados:
            self.stdout.write(
                f"  Se borraron {len(borrados)} respaldo(s) viejo(s)."
            )
