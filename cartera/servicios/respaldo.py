"""
Respaldos de la base de datos.

Como el sistema funciona en un solo archivo SQLite, un respaldo es
simplemente una copia de ese archivo. Pero se hace bien:

- Se usa el comando de SQLite para hacer la copia en caliente, sin copiar
  el archivo a medias mientras alguien esta cobranando.
- El archivo se comprime y se le pone la fecha y la hora.
- Se guardan los ultimos N respaldos y los viejos se borran solos.
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ..models import HistorialMovimiento


class ErrorRespaldo(Exception):
    pass


def carpeta_respaldos():
    carpeta = Path(settings.CARPETA_RESPALDOS)
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def nombre_archivo(fecha=None):
    fecha = fecha or timezone.localtime()
    return f"respaldo_credito_{fecha.strftime('%Y-%m-%d_%H%M%S')}.sqlite3"


def crear_respaldo(destino=None, usuario=None, limpiar=True):
    """Crea una copia de seguridad de la base de datos.

    Devuelve un diccionario con los datos del respaldo hecho.
    """
    from django.db import connection

    base = connection.settings_dict["NAME"]
    base = Path(base)
    if not base.exists():
        raise ErrorRespaldo(
            "No se encontro el archivo de la base de datos. "
            "Revise que el programa este bien instalado."
        )

    momento = timezone.localtime()
    destino = Path(destino) if destino else (carpeta_respaldos() / nombre_archivo(momento))
    destino.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Copia en caliente: SQLite escribe en un temporal y lo renombra al
        # final. Asi el archivo del respaldo sale siempre completo, aunque
        # alguien este usando el programa en este momento.
        origen = sqlite3.connect(str(base))
        try:
            destino_sqlite = sqlite3.connect(str(destino))
            try:
                origen.backup(destino_sqlite)
            finally:
                destino_sqlite.close()
        finally:
            origen.close()
    except sqlite3.Error as error:
        raise ErrorRespaldo(
            f"No se pudo hacer el respaldo: {error}"
        ) from error

    # Comprimir con gzip (viene con Python, no hay que instalar nada).
    comprimido = destino.with_suffix(destino.suffix + ".zip")
    import zipfile
    try:
        with zipfile.ZipFile(comprimido, "w", zipfile.ZIP_DEFLATED) as paquete:
            paquete.write(destino, arcname=destino.name)
        destino.unlink()  # el zip es el que se guarda
    except Exception:
        # Si no se pudo comprimir, se deja el .sqlite3 a secas: mejor un
        # respaldo sin comprimir que no tener respaldo.
        comprimido = destino

    tamano = comprimido.stat().st_size
    cantidad_clientes = _contar("cartera_cliente")
    cantidad_pagos = _contar("cartera_pago")
    cantidad_creditos = _contar("cartera_credito")

    if usuario:
        try:
            HistorialMovimiento.objects.create(
                usuario=usuario,
                tipo=HistorialMovimiento.Tipo.RESPALDO,
                descripcion=f"Respaldo creado: {comprimido.name}",
                datos={
                    "archivo": comprimido.name,
                    "tamaño_bytes": tamano,
                },
            )
        except Exception:
            # Si el historial falla, el respaldo igual ya esta en disco.
            pass

    if limpiar:
        limpiar_antiguos(conservar=20)

    return {
        "archivo": comprimido,
        "nombre": comprimido.name,
        "tamaño": tamano,
        "fecha": momento,
        "clientes": cantidad_clientes,
        "pagos": cantidad_pagos,
        "creditos": cantidad_creditos,
    }


def _contar(tabla):
    """Cuenta filas de una tabla sin depender de los modelos."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
            fila = cursor.fetchone()
        return fila[0] if fila else 0
    except Exception:
        return 0


def listar_respaldos():
    """Respaldos disponibles, del mas nuevo al mas viejo."""
    carpeta = carpeta_respaldos()
    archivos = []
    for archivo in carpeta.iterdir():
        if archivo.is_file() and archivo.name.startswith("respaldo_credito_"):
            stat = archivo.stat()
            archivos.append({
                "archivo": archivo,
                "nombre": archivo.name,
                "tamaño": stat.st_size,
                "fecha": datetime.fromtimestamp(stat.st_mtime),
            })
    archivos.sort(key=lambda a: a["nombre"], reverse=True)
    return archivos


def limpiar_antiguos(conservar=20):
    """Borra los respaldos viejos para que la carpeta no crezca infinito."""
    respaldos = listar_respaldos()
    borrados = []
    for viejo in respaldos[conservar:]:
        try:
            viejo["archivo"].unlink()
            borrados.append(viejo["nombre"])
        except OSError:
            pass
    return borrados


def restaurar_respaldo(archivo, usuario=None):
    """Restaura un respaldo sobre la base de datos actual.

    IMPORTANTE: antes de restaurar se guarda un respaldo del estado actual,
    por si el usuario se arrepiente. Asi nunca se pierde informacion.
    """
    from django.db import connection

    archivo = Path(archivo)
    if not archivo.exists():
        raise ErrorRespaldo("El archivo de respaldo no existe.")

    # 1) Respaldo de seguridad del estado actual.
    seguro = crear_respaldo(
        destino=carpeta_respaldos() / nombre_archivo(timezone.localtime()).replace(
            "respaldo_credito_", "antes_de_restaurar_",
        ),
        usuario=None,
        limpiar=False,
    )

    # 2) Cerrar conexiones para poder sobrescribir el archivo.
    connection.close()

    origen = archivo
    if archivo.suffix == ".zip":
        import zipfile

        carpeta_temporal = Path(settings.CARPETA_TIEMPO)
        carpeta_temporal.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archivo, "r") as paquete:
            nombres = [n for n in paquete.namelist() if n.endswith(".sqlite3")]
            if not nombres:
                raise ErrorRespaldo("El archivo zip no contiene una base de datos.")
            paquete.extract(nombres[0], carpeta_temporal)
            origen = carpeta_temporal / nombres[0]

    destino = Path(connection.settings_dict["NAME"])
    destino.parent.mkdir(parents=True, exist_ok=True)

    for sufijo in ("-wal", "-shm"):
        archivo_wal = Path(str(destino) + sufijo)
        if archivo_wal.exists():
            archivo_wal.unlink()

    shutil.copy2(origen, destino)

    if usuario:
        try:
            HistorialMovimiento.objects.create(
                usuario=usuario,
                tipo=HistorialMovimiento.Tipo.RESPALDO,
                descripcion=f"Restauro el respaldo {archivo.name}",
                datos={"respaldo": archivo.name, "copia_segura": seguro["nombre"]},
            )
        except Exception:
            pass

    return seguro
