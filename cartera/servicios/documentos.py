"""
Manejo de las fotos de la cedula del cliente.

REGLA DE ORO: las fotos NO se sirven como archivo publico. Nunca estan en
una carpeta que el navegador pueda leer directo. Se entregan por una vista
que revisa que:
  1. el usuario este conectado,
  2. tenga permiso para ver documentos,
  3. y devuelva el archivo con cabeceras que impiden guardarlo en cache
     publica ni embeberlo en otra pagina.
"""

import os
import uuid
from pathlib import Path

from django.core.files.storage import default_storage
from django.utils import timezone

from ..models import DocumentoCliente


# Tipos de imagen que se aceptan.
TIPOS_PERMITIDOS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}

TAMANO_MAXIMO = 12 * 1024 * 1024  # 12 MB


class ErrorDocumento(Exception):
    pass


def validar_imagen(archivo):
    """Revisa que el archivo sea una imagen valida y no pese de mas."""
    if not archivo:
        raise ErrorDocumento("No se selecciono ninguna imagen.")

    if archivo.size > TAMANO_MAXIMO:
        mb = round(archivo.size / (1024 * 1024), 1)
        raise ErrorDocumento(
            f"La foto pesa {mb} MB y el maximo es 12 MB. "
            f"Tomele la foto otra vez, con menos calidad."
        )

    content_type = (getattr(archivo, "content_type", "") or "").lower()
    extension = os.path.splitext(archivo.name)[1].lower()

    if content_type and content_type not in TIPOS_PERMITIDOS:
        raise ErrorDocumento(
            "Ese archivo no es una imagen. Use fotos JPG, PNG o WEBP."
        )
    if extension and extension not in {".jpg", ".jpeg", ".png", ".webp", ".heic"}:
        raise ErrorDocumento(
            "Ese archivo no es una imagen. Use fotos JPG, PNG o WEBP."
        )

    # Ultima linea de defensa: confirmar que Pillow lo abre. Un `.jpg` que
    # por dentro sea un archivo de texto no pasa de aqui.
    try:
        from PIL import Image
        archivo.seek(0)
        with Image.open(archivo) as imagen:
            imagen.verify()
        archivo.seek(0)
    except Exception as error:
        raise ErrorDocumento(
            "La imagen esta danada o no se pudo leer. Vuelva a tomarla."
        ) from error
    return True


def guardar_documento(cliente, tipo, archivo, usuario):
    """Sube una foto de cedula y la deja asociada solo a ese cliente."""
    from ..models import HistorialMovimiento

    if not validar_imagen(archivo):
        raise ErrorDocumento("La imagen no se pudo validar.")

    # Nombre inventado: no se usa el nombre que subio el usuario. Asi nadie
    # puede subir algo llamado "foto.jpg" que en realidad sea otra cosa, y no
    # se guarda informacion del computador del usuario en el nombre.
    extension = os.path.splitext(archivo.name)[1].lower() or ".jpg"
    if extension == ".jpeg":
        extension = ".jpg"
    nombre_seguro = f"cedula_{cliente.id}_{tipo.lower()}_{uuid.uuid4().hex[:12]}{extension}"

    documento = DocumentoCliente(
        cliente=cliente,
        tipo=tipo,
        nombre_original=archivo.name[:200],
        subido_por=usuario,
    )
    documento.archivo.save(nombre_seguro, archivo, save=True)

    HistorialMovimiento.objects.create(
        usuario=usuario,
        tipo=HistorialMovimiento.Tipo.CLIENTE,
        descripcion=f"Subio {documento.get_tipo_display().lower()} de "
                    f"{cliente.nombre_completo}",
        cliente=cliente,
        datos={"documento_id": documento.id, "tipo": tipo},
    )
    return documento


def eliminar_documento(documento, usuario):
    """Quita la foto. Esto SI es reversible: el archivo se borra, pero queda
    el registro del movimiento.

    NOTA: a diferencia de los pagos, aqui no hay informacion financiera que
    se pueda perder; es solo una foto que el usuario subio por error.
    """
    from ..models import HistorialMovimiento

    cliente = documento.cliente
    tipo = documento.get_tipo_display()
    documento.archivo.delete(save=False)
    documento.delete()

    HistorialMovimiento.objects.create(
        usuario=usuario,
        tipo=HistorialMovimiento.Tipo.CLIENTE,
        descripcion=f"Elimino {tipo.lower()} de {cliente.nombre_completo}",
        cliente=cliente,
        datos={"tipo": documento.tipo},
    )


def documentos_de(cliente):
    """Documentos del cliente ordenados: frente primero, reverso despues."""
    return list(cliente.documentos.select_related("subido_por").order_by("tipo"))


def tiene_documentos(cliente):
    return cliente.documentos.exists()
