"""
Administracion tecnica de Django (opcional).

La mayoria del manejo se hace por las pantallas propias del programa, pero
esta seccion queda disponible para consultas rapidas o paraoyo tecnico.
"""

from django.contrib import admin

from .models import (
    Cliente, ClienteBusqueda, Configuracion, Credito, Cuota, DocumentoCliente,
    FrecuenciaPago, HistorialMovimiento, MetodoPago, Pago, PerfilUsuario,
    Producto,
)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre_completo", "cedula", "telefono", "ciudad", "activo", "fecha_creacion"]
    list_filter = ["activo", "ciudad"]
    search_fields = ["nombres", "apellidos", "cedula", "telefono"]
    readonly_fields = ["fecha_creacion", "fecha_modificacion"]


@admin.register(Credito)
class CreditoAdmin(admin.ModelAdmin):
    list_display = ["id", "cliente", "producto_texto", "valor_financiado",
                    "total_pagado", "saldo", "estado", "frecuencia"]
    list_filter = ["estado", "frecuencia"]
    search_fields = ["cliente__nombres", "cliente__apellidos", "cliente__cedula"]


@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = ["credito", "numero", "fecha_vencimiento", "valor",
                    "valor_pagado", "estado"]
    list_filter = ["estado", "fecha_vencimiento"]


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["recibo", "fecha", "cliente_credito", "valor", "metodo", "anulado"]
    list_filter = ["anulado", "metodo", "fecha"]
    search_fields = ["recibo", "credito__cliente__cedula"]

    @admin.display(description="Cliente")
    def cliente_credito(self, obj):
        return str(obj.credito.cliente)


@admin.register(HistorialMovimiento)
class HistorialAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tipo", "descripcion", "usuario"]
    list_filter = ["tipo", "fecha"]


# Estos modelos se registran sin clase propia: solo se ven en la seccion
# tecnica de Django, que es opcional.
admin.site.register([
    Configuracion, DocumentoCliente, FrecuenciaPago, MetodoPago,
    PerfilUsuario, Producto, ClienteBusqueda,
])
