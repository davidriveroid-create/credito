"""
Rutas del sistema de ventas a credito y cobranza.

Cada URL tiene un nombre. Las vistas referencian los nombres, no las
direcciones, para que cambiar una URL no rompa el sistema entero.
"""

from django.urls import path

from .vistas import (
    acceso, alertas, api, calendario, clientes, cobranza, configuracion,
    creditos, dashboard, reportes,
)

# --- Paginas principales -----------------------------------------------
urlpatterns = [
    path("", dashboard.dashboard, name="inicio"),

    # Acceso
    path("entrar/", acceso.entrar, name="entrar"),
    path("salir/", acceso.salir, name="salir"),
    path("mi-clave/", acceso.cambiar_clave, name="cambiar_clave"),

    # Panel
    path("panel/", dashboard.dashboard, name="dashboard"),

    # Clientes
    path("clientes/", clientes.lista_clientes, name="clientes"),
    path("clientes/nuevo/", clientes.crear_cliente, name="nuevo_cliente"),
    path("clientes/<int:cliente_id>/", clientes.ficha_cliente, name="ficha_cliente"),
    path("clientes/<int:cliente_id>/editar/", clientes.editar_cliente, name="editar_cliente"),
    path("clientes/<int:cliente_id>/activar/", clientes.activar_cliente, name="activar_cliente"),

    # Foto de la cedula
    path("clientes/<int:cliente_id>/cedula/", clientes.documentos_cliente, name="documentos_cliente"),
    path("documentos/<int:documento_id>/quitar/", clientes.eliminar_documento, name="eliminar_documento"),
    path("documentos/<int:documento_id>/ver/", clientes.ver_documento, name="ver_documento"),

    # Creditos
    path("creditos/", creditos.lista_creditos, name="creditos"),
    path("creditos/nuevo/", creditos.nuevo_credito, name="nuevo_credito"),
    path("creditos/plan/", creditos.calcular_plan, name="calcular_plan"),
    path("creditos/productos/", creditos.productos, name="productos"),
    path("creditos/producto/nuevo/", creditos.crear_producto, name="crear_producto"),
    path("creditos/<int:credito_id>/", creditos.ficha_credito, name="ficha_credito"),
    path("creditos/<int:credito_id>/editar/", creditos.editar_credito, name="editar_credito"),
    path("creditos/<int:credito_id>/anular/", creditos.anular_credito, name="anular_credito"),

    # Cobranza
    path("cobrar/", cobranza.cobrar, name="cobrar"),
    path("cobrar/cliente/<int:cliente_id>/", cobranza.cobrar_cliente, name="cobrar_cliente"),
    path("cobrar/registrar/<int:credito_id>/", cobranza.registrar_pago, name="registrar_pago"),
    path("cobrar/comprobante/<int:pago_id>/", cobranza.comprobante, name="comprobante"),
    path("pagos/", cobranza.historial_pagos, name="historial_pagos"),
    path("pagos/<int:pago_id>/anular/", cobranza.anular, name="anular_pago"),
    path("pagos/<int:pago_id>/corregir/", cobranza.corregir, name="corregir_pago"),

    # Cobros pendientes
    path("pendientes/", alertas.cobros_pendientes, name="cobros_pendientes"),

    # Calendario
    path("calendario/", calendario.calendario, name="calendario"),
    path("calendario/<int:anio>/<int:mes>/<int:dia>/", calendario.dia, name="dia_calendario"),

    # Reportes
    path("reportes/", reportes.reportes, name="reportes"),
    path("reportes/excel/", reportes.exportar_excel, name="exportar_excel"),
    path("reportes/csv/", reportes.exportar_csv, name="exportar_csv"),

    # Configuracion
    path("configuracion/", configuracion.ajustes, name="ajustes"),
    path("configuracion/guardar/", configuracion.guardar_ajustes, name="guardar_ajustes"),
    path("configuracion/frecuencia/", configuracion.guardar_frecuencia, name="guardar_frecuencia"),
    path("configuracion/metodo/", configuracion.guardar_metodo_pago, name="guardar_metodo_pago"),
    path("configuracion/catalogo/<str:tipo>/<int:objeto_id>/quitar/", configuracion.eliminar_catalogo, name="eliminar_catalogo"),

    # Usuarios
    path("usuarios/", configuracion.usuarios, name="usuarios"),
    path("usuarios/nuevo/", configuracion.crear_usuario, name="crear_usuario"),
    path("usuarios/<int:usuario_id>/", configuracion.editar_usuario, name="editar_usuario"),

    # Respaldos
    path("respaldos/", configuracion.respaldos, name="respaldos"),
    path("respaldos/nuevo/", configuracion.crear_respaldo, name="crear_respaldo"),
    path("respaldos/<str:nombre>/descargar/", configuracion.descargar_respaldo, name="descargar_respaldo"),
    path("respaldos/<str:nombre>/restaurar/", configuracion.restaurar_respaldo, name="restaurar_respaldo"),

    # Auditoria
    path("historial/", configuracion.historial, name="historial"),

    # Busqueda rapida (JSON)
    path("api/buscar/", api.buscar, name="api_buscar"),
    path("api/credito/", api.info_credito, name="api_credito"),
    path("api/creditos-cliente/", api.buscar_creditos, name="api_creditos_cliente"),
]
