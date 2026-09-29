"""
Crea el usuario administrador inicial.

Uso:
    .venv\\Scripts\\python.exe manage.py crear_admin
    .venv\\Scripts\\python.exe manage.py crear_admin --usuario admin --clave mi12345

Si el usuario ya existe, solo le actualiza la clave y el rol.
"""

import getpass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cartera.models import Configuracion, PerfilUsuario, Rol
from cartera.servicios.regularidad import configuracion
from cartera.servicios.catalogo import crear_catalogos_iniciales


class Command(BaseCommand):
    help = "Crea o actualiza el usuario administrador del sistema."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default=None,
                            help="Nombre de usuario (por defecto 'admin').")
        parser.add_argument("--clave", default=None,
                            help="Contrasena. Si no se pone, se pregunta.")
        parser.add_argument("--nombre", default="Administrador",
                            help="Nombre real.")

    def handle(self, *args, **opciones):
        usuario_nombre = opciones["usuario"] or "admin"
        clave = opciones["clave"]

        if not clave:
            if not self.stdin.isatty():
                raise CommandError(
                    "Falta la contrasena. Usela asi:\n"
                    "  manage.py crear_admin --clave su_clave_aqui"
                )
            clave = getpass.getpass("Contrasena del administrador: ")
            if not clave:
                raise CommandError("La contrasena no puede estar vacia.")
            if len(clave) < 6:
                raise CommandError(
                    "La contrasena debe tener al menos 6 caracteres."
                )

        with transaction.atomic():
            # Catalogo minimo para que el sistema pueda usarse.
            crear_catalogos_iniciales()
            configuracion()

            usuario, creado = User.objects.get_or_create(
                username=usuario_nombre,
                defaults={
                    "first_name": opciones["nombre"],
                    "is_staff": True,
                    "is_superuser": True,
                },
            )
            if creado:
                usuario.set_password(clave)
                usuario.is_staff = True
                usuario.is_superuser = True
                usuario.save()
                accion = "creado"
            else:
                usuario.set_password(clave)
                usuario.is_staff = True
                usuario.save()
                accion = "actualizado"

            PerfilUsuario.objects.update_or_create(
                usuario=usuario,
                defaults={"rol": Rol.ADMINISTRADOR, "activo": True},
            )

        self.stdout.write(self.style.SUCCESS(
            f"Usuario '{usuario_nombre}' {accion} correctamente."
        ))
        self.stdout.write(
            f"  Entre en http://127.0.0.1:9000/ con ese usuario."
        )
