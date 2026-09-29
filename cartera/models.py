"""
Base de datos del sistema de ventas a credito y cobranza.

Relaciones principales:

    Cliente  1 --- N  Credito
    Credito  1 --- N  Cuota
    Cuota    1 --- N  Pago      (puede tener varios abonos parciales)
    Cliente  1 --- N  DocumentoCliente
    Usuario  1 --- N  (todo lo que crea o toca)

Reglas que nunca se rompen:
  - Un pago NUNCA se borra. Si esta mal, se anula y queda el registro.
  - Un cliente NUNCA se borra. Si no compra mas, se desactiva.
  - Un credito terminado guarda todo su historial para siempre.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

CERO = Decimal("0")


def pesada(valor):
    """Redondea a pesos enteros, sin decimiles (los pesos colombianos no los usan)."""
    return Decimal(valor).quantize(Decimal("1"))


# ===========================================================================
# CONFIGURACION DEL SISTEMA
# ===========================================================================


class Configuracion(models.Model):
    """Una sola fila en toda la base. Guarda los parametros del negocio.

    Los parametros de regularidad (umbrales) se editan desde la pantalla de
    Configuracion y son los que usa el calculo de la barra de regularidad.
    """

    # --- Datos del negocio ---------------------------------------------
    nombre_negocio = models.CharField("Nombre del negocio", max_length=120)
    logo = models.ImageField("Logo", upload_to="negocio/", blank=True, null=True)
    telefono = models.CharField("Telefono", max_length=40, blank=True)
    direccion = models.CharField("Direccion", max_length=200, blank=True)
    nit = models.CharField("NIT", max_length=40, blank=True)
    mensaje_comprobante = models.CharField(
        "Mensaje del comprobante", max_length=300, blank=True,
        help_text="Texto que sale abajo en el comprobante de pago.",
    )

    # --- Formato -------------------------------------------------------
    moneda_simbolo = models.CharField("Simbolo de la moneda", max_length=8, default="$")
    moneda_codigo = models.CharField("Codigo de la moneda", max_length=8, default="COP")
    moneda_decimales = models.PositiveSmallIntegerField("Decimales", default=0)
    formato_fecha = models.CharField("Formato de fecha", max_length=20, default="%d/%m/%Y")

    # --- Umbrales de regularidad (CONFIGURABLES) -----------------------
    # Porcentaje a partir del cual el cliente se considera EXCELENTE.
    umbral_excelente = models.PositiveSmallIntegerField(
        "Umbral EXCELENTE (%)", default=90,
        help_text="Porcentaje de pagos puntuales para estar en categoria EXCELENTE.",
    )
    # Porcentaje a partir del cual se considera BUENO.
    umbral_bueno = models.PositiveSmallIntegerField(
        "Umbral BUENO (%)", default=70,
        help_text="Porcentaje de pagos puntuales para estar en categoria BUENO.",
    )
    # Dias de atraso a partir de los cuales un cliente con cuotas vencidas
    # pasa de ATRASADO a MOROSO.
    dias_para_moroso = models.PositiveSmallIntegerField(
        "Dias para MOROSO", default=15,
        help_text="Dias de atraso de la cuota mas vieja para marcar como MOROSO.",
    )
    # Un pago cuenta como 'puntual' si se registro este numero de dias
    # despues del vencimiento o antes.
    dias_gracia = models.PositiveSmallIntegerField(
        "Dias de gracia", default=0,
        help_text="Dias de tolerancia despues del vencimiento para que el pago "
                  "siga contando como puntual (0 = puntual solo si pago a tiempo).",
    )
    # Minimo de cuotas pagadas para poder clasificar a un cliente.
    minimo_cuotas_para_clasificar = models.PositiveSmallIntegerField(
        "Minimo de cuotas para clasificar", default=1,
        help_text="Con menos cuotas pagadas que esto el cliente sale como SIN DATOS.",
    )

    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion del sistema"
        verbose_name_plural = "Configuracion del sistema"

    def __str__(self):
        return self.nombre_negocio

    def guardar(self):
        """Crea la fila unica si todavia no existe."""
        obj, _ = Configuracion.objects.get_or_create(pk=1, defaults={
            "nombre_negocio": "Mi Negocio",
        })
        return obj

    @property
    def es_excelente(self):
        return self.umbral_excelente

    @property
    def es_bueno(self):
        return self.umbral_bueno


# ===========================================================================
# USUARIOS Y PERMISOS
# ===========================================================================


class Rol(models.TextChoices):
    ADMINISTRADOR = "ADMIN", "Administrador"
    COBRADOR = "COBRA", "Cobrador"


class PerfilUsuario(models.Model):
    """Datos extra del usuario: rol, sucursal y si esta activo.

    La contrasena nunca se guarda aqui. Django la guarda cifrada.
    """

    usuario = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="perfil",
        verbose_name="Usuario",
    )
    rol = models.CharField(
        "Rol", max_length=10, choices=Rol.choices,
        default=Rol.COBRADOR,
    )
    activo = models.BooleanField("Activo", default=True)
    telefono = models.CharField("Telefono", max_length=40, blank=True)
    observaciones = models.TextField("Observaciones", blank=True)
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"

    def __str__(self):
        return f"{self.usuario.get_username()} ({self.get_rol_display()})"

    def es_administrador(self):
        return self.rol == Rol.ADMINISTRADOR

    def guardar_si_falta(self):
        perfil, _ = PerfilUsuario.objects.get_or_create(
            usuario=self.usuario,
            defaults={"rol": Rol.ADMINISTRADOR if self.is_superuser else Rol.COBRADOR},
        )
        return perfil


# ===========================================================================
# CATALOGOS
# ===========================================================================


class FrecuenciaPago(models.Model):
    """DIARIO, SEMANAL, QUINCENAL, MENSUAL... Se pueden agregar mas.

    Guardar el numero de dias permite agregar frecuencias nuevas sin
    tocar el codigo.
    """

    class Unidad(models.TextChoices):
        DIAS = "DIAS", "Dias"
        MESES = "MESES", "Meses"

    nombre = models.CharField("Nombre", max_length=40, unique=True)
    dias = models.PositiveIntegerField("Dias de intervalo", default=30)
    unidad = models.CharField(
        "Unidad", max_length=6, choices=Unidad.choices, default=Unidad.DIAS,
        help_text="Dias = suma exacta de dias. Meses = suma meses de calendario "
                  "(mejor para el pago mensual).",
    )
    activo = models.BooleanField("Activo", default=True)
    orden = models.PositiveSmallIntegerField("Orden", default=100)

    class Meta:
        verbose_name = "Frecuencia de pago"
        verbose_name_plural = "Frecuencias de pago"
        ordering = ["orden", "id"]

    def __str__(self):
        return self.nombre

    def sumar(self, fecha, veces=1):
        """Devuelve la fecha de la cuota numero `fecha + veces intervalos`."""
        from .servicios.calendario import sumar_frecuencia
        return sumar_frecuencia(fecha, self, veces)


class MetodoPago(models.Model):
    """Efectivo, transferencia, Nequi, Bancolombia, otro..."""

    nombre = models.CharField("Nombre", max_length=60, unique=True)
    activo = models.BooleanField("Activo", default=True)
    orden = models.PositiveSmallIntegerField("Orden", default=100)

    class Meta:
        verbose_name = "Metodo de pago"
        verbose_name_plural = "Metodos de pago"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


# ===========================================================================
# CLIENTES
# ===========================================================================


class Cliente(models.Model):
    """Cliente al que se le vende a credito.

    NUNCA se borra. Si deja de comprar se marca inactivo y se conserva todo
    su historial de creditos y pagos.
    """

    # --- Informacion personal -----------------------------------------
    nombres = models.CharField("Nombres", max_length=80)
    apellidos = models.CharField("Apellidos", max_length=80)
    cedula = models.CharField(
        "Numero de cedula", max_length=30, unique=True,
        help_text="Sin puntos ni guiones. Ejemplo: 123456789",
    )
    telefono = models.CharField("Telefono principal", max_length=40)
    telefono_alternativo = models.CharField("Telefono alterno", max_length=40, blank=True)
    direccion = models.CharField("Direccion", max_length=200)
    ciudad = models.CharField("Ciudad", max_length=80)
    barrio = models.CharField("Barrio", max_length=80, blank=True)

    # --- Referencia personal ------------------------------------------
    referencia_nombre = models.CharField("Nombre de la referencia", max_length=120, blank=True)
    referencia_telefono = models.CharField("Telefono de la referencia", max_length=40, blank=True)

    # --- Otros datos --------------------------------------------------
    ocupacion = models.CharField("Ocupacion", max_length=120, blank=True)
    fecha_nacimiento = models.DateField("Fecha de nacimiento", null=True, blank=True)
    observaciones = models.TextField("Observaciones", blank=True)

    activo = models.BooleanField(
        "Activo", default=True,
        help_text="Desactive para que no aparezca en las listas de cobranza. "
                  "No se borra nada: sus creditos y pagos se conservan.",
    )
    fecha_creacion = models.DateTimeField("Fecha de creacion", auto_now_add=True)
    fecha_modificacion = models.DateTimeField("Ultima modificacion", auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="clientes_creados", verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["apellidos", "nombres"]
        indexes = [
            models.Index(fields=["cedula"], name="idx_cliente_cedula"),
            models.Index(fields=["apellidos", "nombres"], name="idx_cliente_nombre"),
            models.Index(fields=["activo"], name="idx_cliente_activo"),
        ]

    def __str__(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}".strip()

    @property
    def nombre_corto(self):
        """'Juan Perez' -> 'Juan P.' para listas estrechas."""
        primero = self.nombres.split(" ")[0] if self.nombres else ""
        inicial = self.apellidos[0] if self.apellidos else ""
        return f"{primero} {inicial}." if inicial else primero

    @property
    def cedula_oculta(self):
        """Ultimos 3 digitos, para comprobantes y listas compartidas."""
        limpio = "".join(c for c in self.cedula if c.isdigit())
        if len(limpio) <= 3:
            return limpio
        return f"*****{limpio[-3:]}"

    def saldo_total(self):
        """Suma de lo que falta por pagar en todos sus creditos."""
        from .servicios.cartera import resumen_cliente
        return resumen_cliente(self.id)["saldo"]

    def guardar_busqueda(self, texto):
        """Guarda un texto buscado para poder sugerirlo despues."""
        ClienteBusqueda.objects.get_or_create(texto=texto[:80])


class ClienteBusqueda(models.Model):
    """Texto que los usuarios buscó. Sirve para autocomplete y auditoria."""

    texto = models.CharField(max_length=80, unique=True)
    veces = models.PositiveIntegerField(default=1)
    fecha_ultimo_uso = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Busqueda de cliente"
        verbose_name_plural = "Busquedas de clientes"
        ordering = ["-veces"]

    def __str__(self):
        return self.texto


class DocumentoCliente(models.Model):
    """Foto de la cedula del cliente (frente y reverso).

    La foto NO se puede abrir por URL directa: la vista que la entrega
    revisa que el usuario este conectado y tenga permiso.
    """

    class Tipo(models.TextChoices):
        FRONTAL = "FRONTAL", "Frente de la cedula"
        POSTERIOR = "POSTERIOR", "Reverso de la cedula"
        OTRO = "OTRO", "Otro documento"

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="documentos",
        verbose_name="Cliente",
    )
    tipo = models.CharField("Tipo", max_length=12, choices=Tipo.choices)
    archivo = models.ImageField("Foto", upload_to="cedula/%Y/%m/")
    nombre_original = models.CharField(max_length=200, blank=True)
    fecha_subida = models.DateTimeField("Fecha de subida", auto_now_add=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documentos_subidos",
    )

    class Meta:
        verbose_name = "Documento del cliente"
        verbose_name_plural = "Documentos de clientes"
        ordering = ["tipo"]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.cliente}"


# ===========================================================================
# PRODUCTOS
# ===========================================================================


class Producto(models.Model):
    """Electrodomestico, mueble, tecnologia... que se vende a credito."""

    nombre = models.CharField("Producto", max_length=120)
    marca = models.CharField("Marca", max_length=80, blank=True)
    modelo = models.CharField("Modelo", max_length=80, blank=True)
    numero_serie = models.CharField("Numero de serie", max_length=80, blank=True)
    descripcion = models.TextField("Descripcion", blank=True)
    precio_contado = models.DecimalField(
        "Precio de contado", max_digits=14, decimal_places=0,
        default=CERO, validators=[MinValueValidator(CERO)],
    )
    activo = models.BooleanField("Activo", default=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre_completo

    @property
    def nombre_completo(self):
        partes = [self.nombre]
        if self.marca:
            partes.append(self.marca)
        if self.modelo:
            partes.append(self.modelo)
        return " - ".join(partes)


# ===========================================================================
# CREDITOS / VENTAS A CREDITO
# ===========================================================================


class EstadoCredito(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo (saldo pendiente)"
    PAGADO = "PAGADO", "Pagado (cancelado)"
    ANULADO = "ANULADO", "Anulado"


class Credito(models.Model):
    """Una venta a credito. Un cliente puede tener cuantos creditos quiera.

    Los saldos (total_pagado, saldo) son un resumen que se recalcula desde
    los pagos. Se guardan para que las listas carguen rapido, pero la
    verdad siempre son las cuotas y los pagos.
    """

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="creditos",
        verbose_name="Cliente",
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="creditos",
        verbose_name="Producto", null=True, blank=True,
    )

    # --- Si no se eligio producto del catalogo, se escribe libre ---------
    producto_texto = models.CharField(
        "Producto (escrito)", max_length=200, blank=True,
        help_text="Se llena solo si el producto no esta en el catalogo.",
    )

    fecha_venta = models.DateField("Fecha de la venta", default=timezone.localdate)

    # --- Dinero ---------------------------------------------------------
    precio_contado = models.DecimalField(
        "Precio de contado", max_digits=14, decimal_places=0,
        validators=[MinValueValidator(CERO)],
    )
    precio_financiado = models.DecimalField(
        "Precio financiado (total con cuota inicial)", max_digits=14, decimal_places=0,
        validators=[MinValueValidator(CERO)],
    )
    cuota_inicial = models.DecimalField(
        "Cuota inicial (abono)", max_digits=14, decimal_places=0,
        default=CERO, validators=[MinValueValidator(CERO)],
    )
    valor_financiado = models.DecimalField(
        "Saldo a financiar", max_digits=14, decimal_places=0,
        validators=[MinValueValidator(CERO)],
    )
    valor_cuota = models.DecimalField(
        "Valor de cada cuota", max_digits=14, decimal_places=0,
        validators=[MinValueValidator(CERO)],
    )
    numero_cuotas = models.PositiveIntegerField("Numero de cuotas")

    frecuencia = models.ForeignKey(
        FrecuenciaPago, on_delete=models.PROTECT, related_name="creditos",
        verbose_name="Frecuencia de pago",
    )
    fecha_primera_cuota = models.DateField("Fecha de la primera cuota")
    fecha_estimada_fin = models.DateField(
        "Fecha estimada de finalizacion", null=True, blank=True,
        help_text="Se calcula sola con la frecuencia y el numero de cuotas.",
    )
    fecha_finalizacion = models.DateField(
        "Fecha real de finalizacion", null=True, blank=True,
    )

    estado = models.CharField(
        "Estado", max_length=10, choices=EstadoCredito.choices,
        default=EstadoCredito.ACTIVO,
    )
    total_pagado = models.DecimalField(
        "Total pagado", max_digits=14, decimal_places=0, default=CERO,
    )
    saldo = models.DecimalField(
        "Saldo pendiente", max_digits=14, decimal_places=0, default=CERO,
    )
    cuotas_pagadas = models.PositiveIntegerField("Cuotas pagadas", default=0)
    cuotas_vencidas = models.PositiveIntegerField("Cuotas vencidas", default=0)

    observaciones = models.TextField("Observaciones", blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="creditos_creados", verbose_name="Creado por",
    )

    class Meta:
        verbose_name = "Credito"
        verbose_name_plural = "Creditos"
        ordering = ["-fecha_venta", "-id"]
        indexes = [
            models.Index(fields=["cliente", "estado"], name="idx_credito_cli_est"),
            models.Index(fields=["estado"], name="idx_credito_estado"),
        ]

    def __str__(self):
        return f"Credito #{self.id} - {self.cliente} - {self.producto_texto or self.producto}"

    @property
    def nombre_producto(self):
        return self.producto_texto or (str(self.producto) if self.producto else "-")

    @property
    def esta_pagado(self):
        return self.estado == EstadoCredito.PAGADO

    @property
    def esta_activo(self):
        return self.estado == EstadoCredito.ACTIVO

    def nombre_producto_o_id(self):
        return self.nombre_producto

    def cuota_actual(self):
        """La cuota que toca pagar: la primera pendiente o vencida."""
        from .servicios.cuotas import cuota_siguiente
        return cuota_siguiente(self)

    def guardar_estado(self):
        """Recalcula total pagado, saldo y estado del credito."""
        from .servicios.cuotas import recalcular_credito
        return recalcular_credito(self)


# ===========================================================================
# CUOTAS
# ===========================================================================


class EstadoCuota(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    PARCIAL = "PARCIAL", "Parcial"
    PAGADA = "PAGADA", "Pagada"
    VENCIDA = "VENCIDA", "Vencida"


class Cuota(models.Model):
    """Una cuota del plan de pagos.

    Vencida no se guarda como estado guardado en la base: se calcula. Aqui
    el campo 'estado' guarda PENDIENTE / PARCIAL / PAGADA y la funcion
    `estado_real` compara con la fecha de hoy para decir VENCIDA.
    """

    credito = models.ForeignKey(
        Credito, on_delete=models.CASCADE, related_name="cuotas",
        verbose_name="Credito",
    )
    numero = models.PositiveIntegerField("Numero de cuota")
    fecha_vencimiento = models.DateField("Fecha de vencimiento", db_index=True)
    valor = models.DecimalField(
        "Valor de la cuota", max_digits=14, decimal_places=0,
    )
    valor_pagado = models.DecimalField(
        "Abonado", max_digits=14, decimal_places=0, default=CERO,
    )
    estado = models.CharField(
        "Estado guardado", max_length=10, choices=EstadoCuota.choices,
        default=EstadoCuota.PENDIENTE,
    )
    fecha_pago = models.DateField(
        "Fecha en que se termino de pagar", null=True, blank=True,
    )
    fecha_ultimo_abono = models.DateField(
        "Fecha del ultimo abono", null=True, blank=True,
    )
    observacion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Cuota"
        verbose_name_plural = "Cuotas"
        ordering = ["credito", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["credito", "numero"], name="una_cuota_por_numero_en_credito",
            ),
        ]
        indexes = [
            models.Index(fields=["fecha_vencimiento", "estado"], name="idx_cuota_fec_est"),
            models.Index(fields=["credito", "estado"], name="idx_cuota_cred_est"),
        ]

    def __str__(self):
        return f"Cuota {self.numero} - {self.fecha_vencimiento} - ${self.valor}"

    @property
    def saldo(self):
        return max(CERO, self.valor - self.valor_pagado)

    @property
    def esta_pagada(self):
        return self.valor_pagado >= self.valor

    def estado_real(self, hoy=None):
        """Estado que se muestra, teniendo en cuenta la fecha de hoy."""
        if self.esta_pagada:
            return EstadoCuota.PAGADA
        if hoy is None:
            hoy = timezone.localdate()
        if self.fecha_vencimiento < hoy:
            return EstadoCuota.VENCIDA
        if self.valor_pagado > CERO:
            return EstadoCuota.PARCIAL
        return EstadoCuota.PENDIENTE

    @property
    def dias_de_atraso(self):
        """Dias que se lleva de atraso. 0 si no esta vencida ni pagada tarde."""
        if self.esta_pagada and self.fecha_pago:
            base = self.fecha_pago
        else:
            base = timezone.localdate()
        return max(0, (base - self.fecha_vencimiento).days)

    def pago_tardio(self, dias_gracia=0):
        """True si se pago despues de la fecha (o sigue sin pagarse y ya vencio)."""
        if self.esta_pagada:
            if not self.fecha_pago:
                return False
            return self.fecha_pago > self.fecha_vencimiento + timezone.timedelta(days=dias_gracia)
        return timezone.localdate() > self.fecha_vencimiento + timezone.timedelta(days=dias_gracia)


# ===========================================================================
# PAGOS
# ===========================================================================


class Pago(models.Model):
    """Un abono del cliente.

    - Un pago puede quedar dentro de UNA cuota.
    - Si el valor no alcanza para terminar la cuota, la cuota queda PARCIAL.
    - Si el valor se pasa, se reparte entre la cuota y las siguientes
      (pago anticipado) y el sobrante queda como anticipo a futuro.
    - Un pago NO se borra jamas. Si se equivoquen, se anula y queda el rastro.
    - `token` es un identificador unico: si el usuario recarga la pagina o
      pulsa dos veces el boton, el segundo intento se reconoce y NO se
      duplica el pago.
    """

    credito = models.ForeignKey(
        Credito, on_delete=models.PROTECT, related_name="pagos",
        verbose_name="Credito",
    )
    cuota = models.ForeignKey(
        Cuota, on_delete=models.PROTECT, related_name="pagos",
        verbose_name="Cuota principal",
        null=True, blank=True,
        help_text="La primera cuota que recibio el pago. Para ver como se "
                  "repartio el resto, mire las Aplicaciones de pago.",
    )
    fecha = models.DateField("Fecha del pago", default=timezone.localdate, db_index=True)
    hora = models.TimeField("Hora del pago", default=timezone.localtime)
    valor = models.DecimalField(
        "Valor pagado", max_digits=14, decimal_places=0,
        validators=[MinValueValidator(Decimal("1"))],
    )
    metodo = models.ForeignKey(
        MetodoPago, on_delete=models.PROTECT, related_name="pagos",
        verbose_name="Metodo de pago",
    )
    referencia = models.CharField(
        "Referencia / No. transaccion", max_length=80, blank=True,
    )
    observaciones = models.TextField("Observaciones", blank=True)

    # --- Estado del pago ------------------------------------------------
    anulado = models.BooleanField("Anulado", default=False)
    fecha_anulacion = models.DateTimeField("Fecha de anulacion", null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=300, blank=True)
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pagos_anulados", verbose_name="Anulado por",
    )

    # --- Comprobante ----------------------------------------------------
    saldo_antes = models.DecimalField("Saldo antes del pago", max_digits=14, decimal_places=0)
    saldo_despues = models.DecimalField("Saldo despues del pago", max_digits=14, decimal_places=0)
    recibo = models.CharField(
        "Numero de comprobante", max_length=20, unique=True,
    )

    # --- Control --------------------------------------------------------
    token = models.CharField(
        "Identificador unico", max_length=40, unique=True, db_index=True,
        help_text="Sirve para que un pago no se registre dos veces.",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="pagos", verbose_name="Registrado por",
    )
    fecha_registro = models.DateTimeField("Fecha de registro", auto_now_add=True)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["-fecha", "-hora", "-id"]
        indexes = [
            models.Index(fields=["credito", "fecha"], name="idx_pago_cred_fec"),
            models.Index(fields=["anulado"], name="idx_pago_anulado"),
        ]

    def __str__(self):
        return f"Recibo {self.recibo} - {self.valor}"

    @property
    def nombre_producto(self):
        return self.credito.nombre_producto

    @staticmethod
    def nuevo_token():
        return uuid.uuid4().hex


class AplicacionPago(models.Model):
    """Reparte un pago entre las cuotas a las que se aplico.

    Hace falta porque UN pago puede cubrir VARIAS cuotas: si el cliente
    paga dos cuotas de una vez, ese solo abono queda en un pago, pero se
    reparte en dos aplicaciones (una por cuota). Sin esta tabla, al
    recalcular los saldos el dinero de la segunda cuota se perdia.
    """

    pago = models.ForeignKey(
        Pago, on_delete=models.CASCADE, related_name="aplicaciones",
        verbose_name="Pago",
    )
    cuota = models.ForeignKey(
        Cuota, on_delete=models.CASCADE, related_name="aplicaciones",
        verbose_name="Cuota",
    )
    valor = models.DecimalField(
        "Valor aplicado en esta cuota", max_digits=14, decimal_places=0,
    )
    fecha_aplicacion = models.DateField("Fecha de aplicacion")

    class Meta:
        verbose_name = "Aplicacion de pago"
        verbose_name_plural = "Aplicaciones de pago"
        ordering = ["cuota__numero"]

    def __str__(self):
        return f"{self.valor} a la cuota {self.cuota.numero}"

    def save(self, *args, **kwargs):
        if not self.fecha_aplicacion:
            self.fecha_aplicacion = timezone.localdate()
        return super().save(*args, **kwargs)


# ===========================================================================
# HISTORIAL DE MOVIMIENTOS (auditoria)
# ===========================================================================


class HistorialMovimiento(models.Model):
    """Todo lo que se hizo en el sistema, para saber quien y cuando.

    Nunca se borra. Sirve para responder '¿quien cambio este saldo?'.
    """

    class Tipo(models.TextChoices):
        CLIENTE = "CLIENTE", "Cliente"
        CREDITO = "CREDITO", "Credito"
        CUOTA = "CUOTA", "Cuota"
        PAGO = "PAGO", "Pago"
        ANULACION = "ANULACION", "Anulacion de pago"
        USUARIO = "USUARIO", "Usuario"
        CONFIGURACION = "CONFIG", "Configuracion"
        RESPALDO = "RESPALDO", "Respaldo"
        INGRESO = "INGRESO", "Ingreso al sistema"

    fecha = models.DateTimeField("Fecha", auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movimientos", verbose_name="Usuario",
    )
    tipo = models.CharField("Tipo", max_length=12, choices=Tipo.choices)
    descripcion = models.CharField("Descripcion", max_length=300)
    cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movimientos", verbose_name="Cliente",
    )
    credito = models.ForeignKey(
        Credito, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movimientos", verbose_name="Credito",
    )
    datos = models.JSONField("Datos del cambio", default=dict, blank=True)
    direccion_ip = models.GenericIPAddressField("IP", null=True, blank=True)

    class Meta:
        verbose_name = "Movimiento del historial"
        verbose_name_plural = "Historial de movimientos"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()}: {self.descripcion}"


# ===========================================================================
# CONFIGURACION DE REGULARIDAD GUARDADA
# ===========================================================================


class ReglaRegularidad(models.Model):
    """Reglas de la barra de regularidad, editables desde Configuracion.

    Se separan de Configuracion para que se puedan agregar reglas nuevas
    (por ejemplo, castigar mas los morosos) sin cambiar el codigo.
    """

    CATEGORIAS = [
        ("EXCELENTE", "Excelente"),
        ("BUENO", "Bueno"),
        ("IRREGULAR", "Irregular"),
        ("ATRASADO", "Atrasado"),
        ("MOROSO", "Moroso"),
    ]

    categoria = models.CharField(max_length=12, choices=CATEGORIAS, unique=True)
    porcentaje_minimo = models.PositiveSmallIntegerField(
        "Puntualidad minima (%)", default=0,
    )
    max_cuotas_vencidas = models.PositiveSmallIntegerField(
        "Maximo de cuotas vencidas", default=999,
    )
    max_dias_atraso = models.PositiveSmallIntegerField(
        "Maximo de dias de atraso", default=999,
    )
    color = models.CharField(
        "Color de la barra", max_length=9, default="#22c55e",
    )
    orden = models.PositiveSmallIntegerField("Orden", default=100)
    activa = models.BooleanField("Activa", default=True)

    class Meta:
        verbose_name = "Regla de regularidad"
        verbose_name_plural = "Reglas de regularidad"
        ordering = ["orden"]

    def __str__(self):
        return self.get_categoria_display()
