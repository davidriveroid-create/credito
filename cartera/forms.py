"""
Formularios del sistema.

Todo lo que entra del navegador se valida aqui. Los formularios no confian
en el navegador: aunque alguien disables el JavaScript o mande datos a
mano, las reglas se vuelven a comprobar en el servidor.

Ademas, los formularios de pago llevan un `token` unico generado al
abrir la pagina. Ese token es lo que impide que un pago se registre dos
veces si el usuario recarga o pulsa el boton dos veces.
"""

import re
import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    Cliente, Configuracion, Credito, Credito as ModeloCredito, Cuota, DocumentoCliente,
    EstadoCredito, FrecuenciaPago, MetodoPago, Pago, PerfilUsuario, Producto, Rol,
    pesada,
)
from .servicios.calendario import ErrorCalculo, generar_plan_pagos
from .servicios.dinero import formato_dinero
from .servicios.cuotas import cuota_siguiente


# ===========================================================================
# UTILIDADES
# ===========================================================================


class CampoDinero(forms.IntegerField):
    """Campo de plata que acepta como se escribe en Colombia.

    El navegador y los usuarios escriben $1.000.000, 1.000.000 o 1000000.
    Django, en cambio, solo entiende el ultimo. Este campo quita los
    simbolos y los separadores antes de convertir a numero, para que
    nadie tenga que pensar en el formato.
    """

    def to_python(self, valor):
        if valor is None:
            return None
        if isinstance(valor, str):
            valor = re.sub(r"[^0-9]", "", valor) or "0"
        return super().to_python(valor)

    def prepare_value(self, valor):
        # Al pintar se muestra con separadores de miles: mas facil de leer.
        from .servicios.dinero import numero_plano
        if valor in (None, ""):
            return valor
        return numero_plano(valor)


class CampoFecha(forms.DateInput):
    """Campo de fecha que el navegadorentiende.

    Los <input type="date"> de HTML SOLO aceptan el formato ISO
    (AAAA-MM-DD). Con el formato colombiano (dd/mm/aaaa) el navegador
    rechaza el valor y el campo se ve VACIO, aunque el servidor si lo
    mande bien. Este widget obliga a usar ISO en todos los formularios
    y el sistema lo muestra en dd/mm/aaaa al pintarlo.
    """

    ISO = "%Y-%m-%d"

    def __init__(self, attrs=None, format=None):
        atributos = {"type": "date", "class": "campo"}
        atributos.update(attrs or {})
        super().__init__(atributos)
        # OJO: DateInput.__init__ deja self.format = None en la instancia,
        # tapando el atributo de la clase. Por eso se vuelve a poner aqui.
        self.format = format or self.ISO





def solo_numeros(valor):
    """'1.234.567' -> '1234567'"""
    return "".join(c for c in str(valor or "") if c.isdigit())


def validar_cedula(valor):
    """La cedula colombiana no puede tener letras ni simbolos raro."""
    limpio = solo_numeros(valor)
    if not limpio:
        raise ValidationError("Escriba el numero de cedula.")
    if len(limpio) < 6:
        raise ValidationError("La cedula debe tener al menos 6 digitos.")
    if len(limpio) > 13:
        raise ValidationError("Ese numero de cedula es demasiado largo.")
    return limpio


def validar_telefono(valor):
    limpio = re.sub(r"[^0-9+]", "", str(valor or ""))
    if not limpio:
        raise ValidationError("Escriba el telefono.")
    if len(limpio) < 7:
        raise ValidationError("Ese numero de telefono esta muy corto.")
    return limpio


def limpiar_cedula(valor):
    return solo_numeros(valor)


# ===========================================================================
# CLIENTES
# ===========================================================================


class ClienteForm(forms.ModelForm):
    """Crear y editar clientes."""

    # Las fotos van aparte (subida aparte) para que editar los datos del
    # cliente no borre las fotos que ya tenia.
    class Meta:
        model = Cliente
        fields = [
            "nombres", "apellidos", "cedula", "telefono", "telefono_alternativo",
            "direccion", "ciudad", "barrio", "referencia_nombre",
            "referencia_telefono", "ocupacion", "fecha_nacimiento",
            "observaciones",
        ]
        widgets = {
            "nombres": forms.TextInput(attrs={
                "placeholder": "Juan", "autocomplete": "given-name",
                "class": "campo", "autofocus": "autofocus",
            }),
            "apellidos": forms.TextInput(attrs={
                "placeholder": "Perez", "autocomplete": "family-name",
                "class": "campo",
            }),
            "cedula": forms.TextInput(attrs={
                "placeholder": "123456789", "inputmode": "numeric",
                "class": "campo", "autocomplete": "off",
            }),
            "telefono": forms.TextInput(attrs={
                "placeholder": "300 000 0000", "inputmode": "tel",
                "class": "campo", "autocomplete": "tel",
            }),
            "telefono_alternativo": forms.TextInput(attrs={
                "placeholder": "Opcional", "inputmode": "tel", "class": "campo",
            }),
            "direccion": forms.TextInput(attrs={
                "placeholder": "Calle 10 # 20-30", "class": "campo",
            }),
            "ciudad": forms.TextInput(attrs={
                "placeholder": "Bogota", "class": "campo",
            }),
            "barrio": forms.TextInput(attrs={
                "placeholder": "La Esperanza", "class": "campo",
            }),
            "referencia_nombre": forms.TextInput(attrs={
                "placeholder": "Maria Perez (hermana)", "class": "campo",
            }),
            "referencia_telefono": forms.TextInput(attrs={
                "placeholder": "310 111 1111", "inputmode": "tel", "class": "campo",
            }),
            "ocupacion": forms.TextInput(attrs={
                "placeholder": "Comerciante", "class": "campo",
            }),
            "fecha_nacimiento": CampoFecha(),
            "observaciones": forms.Textarea(attrs={
                "rows": 3, "class": "campo",
                "placeholder": "Notas internas sobre el cliente",
            }),
        }
        labels = {
            "nombres": "Nombres *", "apellidos": "Apellidos *",
            "cedula": "Numero de cedula *", "telefono": "Telefono principal *",
            "direccion": "Direccion *", "ciudad": "Ciudad *",
        }

    def clean_nombres(self):
        valor = (self.cleaned_data.get("nombres") or "").strip()
        if len(valor) < 2:
            raise ValidationError("Escriba el nombre del cliente.")
        return valor

    def clean_apellidos(self):
        valor = (self.cleaned_data.get("apellidos") or "").strip()
        if len(valor) < 2:
            raise ValidationError("Escriba el apellido del cliente.")
        return valor

    def clean_cedula(self):
        cedula = validar_cedula(self.cleaned_data.get("cedula"))
        # Unica en toda la base. Si ya existe, no se deja crear el cliente.
        otros = Cliente.objects.filter(cedula=cedula)
        if self.instance.pk:
            otros = otros.exclude(pk=self.instance.pk)
        if otros.exists():
            cliente = otros.first()
            raise ValidationError(
                f"Ya existe un cliente con esa cedula: {cliente.nombre_completo}. "
                f"Abra ese cliente para agregarle otro credito."
            )
        return cedula

    def clean_telefono(self):
        return validar_telefono(self.cleaned_data.get("telefono"))

    def clean_telefono_alternativo(self):
        valor = self.cleaned_data.get("telefono_alternativo")
        return validar_telefono(valor) if valor else ""

    def clean_referencia_telefono(self):
        valor = self.cleaned_data.get("referencia_telefono")
        return validar_telefono(valor) if valor else ""

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get("fecha_nacimiento")
        if fecha and fecha > timezone.localdate():
            raise ValidationError("La fecha de nacimiento no puede ser futura.")
        if fecha and fecha.year < 1900:
            raise ValidationError("Revise la fecha de nacimiento.")
        return fecha


class DocumentoClienteForm(forms.ModelForm):
    """Subir foto de la cedula (frente o reverso)."""

    class Meta:
        model = DocumentoCliente
        fields = ["tipo", "archivo"]
        widgets = {
            "tipo": forms.Select(attrs={"class": "campo"}),
            "archivo": forms.ClearableFileInput(attrs={
                "accept": "image/*",
                "capture": "environment",  # abre la camara en el celular
                "class": "campo",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.cliente = kwargs.pop("cliente", None)
        super().__init__(*args, **kwargs)
        self.fields["tipo"].label = "Parte de la cedula *"

    def clean_archivo(self):
        from .servicios.documentos import ErrorDocumento, validar_imagen
        archivo = self.cleaned_data.get("archivo")
        try:
            validar_imagen(archivo)
        except ErrorDocumento as error:
            raise ValidationError(str(error))
        return archivo

    def clean(self):
        limpio = super().clean()
        tipo = limpio.get("tipo")
        if self.cliente and tipo and not self.instance.pk:
            if self.cliente.documentos.filter(tipo=tipo).exists():
                etiqueta = dict(self.fields["tipo"].choices).get(tipo, tipo)
                raise ValidationError(
                    f"Este cliente ya tiene la foto de la {etiqueta.lower()}. "
                    f"Reemplace la foto existente."
                )
        return limpio


# ===========================================================================
# PRODUCTOS
# ===========================================================================


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ["nombre", "marca", "modelo", "numero_serie", "descripcion",
                  "precio_contado", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "placeholder": "Xiaomi Scooter", "class": "campo",
            }),
            "marca": forms.TextInput(attrs={"placeholder": "Xiaomi", "class": "campo"}),
            "modelo": forms.TextInput(attrs={"placeholder": "Mi Electric", "class": "campo"}),
            "numero_serie": forms.TextInput(attrs={"placeholder": "Opcional", "class": "campo"}),
            "descripcion": forms.Textarea(attrs={"rows": 2, "class": "campo"}),
            "precio_contado": forms.TextInput(attrs={
                "inputmode": "numeric", "class": "campo dinero",
                "placeholder": "1000000",
            }),
            "activo": forms.CheckboxInput(attrs={"class": "casilla"}),
        }

    def clean_precio_contado(self):
        valor = limpia_dinero(self.cleaned_data.get("precio_contado"))
        if valor < 0:
            raise ValidationError("El precio no puede ser negativo.")
        return valor


def limpia_dinero(valor):
    """'1.000.000' o '$1.000.000' -> 1000000"""
    limpio = re.sub(r"[^0-9]", "", str(valor or ""))
    if not limpio:
        return 0
    return int(limpio)


# ===========================================================================
# CREDITOS
# ===========================================================================


class CreditoForm(forms.ModelForm):
    """Crear una venta a credito.

    Hace las cuentas solo y avisa si los numeros no cuadran, en vez de
    dejar que el usuario se equivoque.
    """

    fecha_venta = forms.DateField(
        label="Fecha de la venta *",
        initial=timezone.localdate,
        widget=CampoFecha(),
    )
    producto_id = forms.ModelChoiceField(
        queryset=Producto.objects.none(),
        label="Producto del catalogo",
        required=False,
        empty_label="-- Escribir el producto a mano --",
        widget=forms.Select(attrs={"class": "campo"}),
    )
    precio_contado = CampoDinero(
        label="Precio de contado *", min_value=0,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo dinero", "placeholder": "1000000",
        }),
    )
    precio_financiado = CampoDinero(
        label="Precio financiado (total) *", min_value=0,
        help_text="Lo que va a pagar el cliente en total, cuota inicial incluida.",
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo dinero", "placeholder": "2000000",
        }),
    )
    cuota_inicial = CampoDinero(
        label="Cuota inicial (abono al contado)", min_value=0, initial=0,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo dinero", "placeholder": "200000",
        }),
    )
    valor_financiado = CampoDinero(
        label="Saldo a financiar *", min_value=0,
        help_text="Se calcula solo: precio financiado menos cuota inicial.",
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo dinero",
            "id": "id_valor_financiado", "readonly": "readonly",
        }),
    )
    numero_cuotas = forms.IntegerField(
        label="Numero de cuotas *", min_value=1, max_value=600,
        widget=forms.NumberInput(attrs={"class": "campo", "min": 1, "max": 600}),
    )
    frecuencia = forms.ModelChoiceField(
        queryset=FrecuenciaPago.objects.filter(activo=True),
        label="Forma de pago *",
        widget=forms.Select(attrs={"class": "campo"}),
    )
    fecha_primera_cuota = forms.DateField(
        label="Fecha de la primera cuota *",
        widget=CampoFecha(),
    )
    valor_cuota = CampoDinero(
        label="Valor de cada cuota", min_value=0, required=False,
        help_text="Dejelo vacio para que el sistema lo calcule solo.",
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo dinero",
            "id": "id_valor_cuota", "placeholder": "Se calcula solo",
        }),
    )

    class Meta:
        model = ModeloCredito
        fields = [
            "cliente", "fecha_venta", "producto_id", "producto_texto",
            "precio_contado", "precio_financiado", "cuota_inicial",
            "valor_financiado", "numero_cuotas", "frecuencia",
            "fecha_primera_cuota", "valor_cuota", "observaciones",
        ]
        widgets = {
            "cliente": forms.Select(attrs={"class": "campo"}),
            "producto_texto": forms.TextInput(attrs={
                "placeholder": "Solo si no esta en el catalogo", "class": "campo",
                "id": "id_producto_texto",
            }),
            "observaciones": forms.Textarea(attrs={
                "rows": 3, "class": "campo",
                "placeholder": "Ej: el cliente se lleva el producto el lunes",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)
        self.fields["producto_id"].queryset = Producto.objects.filter(activo=True)
        self.fields["cliente"].queryset = Cliente.objects.filter(activo=True).order_by(
            "apellidos", "nombres")
        self.fields["cliente"].empty_label = "-- Elija el cliente --"
        if not self.instance.pk:
            self.fields["fecha_primera_cuota"].initial = timezone.localdate()
        self.fields["valor_financiado"].required = False
        self.fields["valor_cuota"].required = False

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        if not cliente:
            raise ValidationError("Elija el cliente de la venta.")
        if not cliente.activo:
            raise ValidationError(
                f"{cliente.nombre_completo} esta INACTIVO. Active el cliente "
                f"en la ficha del cliente antes de venderle."
            )
        return cliente

    def clean(self):
        limpio = super().clean()
        hoy = timezone.localdate()

        precio_contado = limpio.get("precio_contado") or 0
        precio_financiado = limpio.get("precio_financiado") or 0
        cuota_inicial = limpio.get("cuota_inicial") or 0
        numero_cuotas = limpio.get("numero_cuotas")
        frecuencia = limpio.get("frecuencia")
        fecha_venta = limpio.get("fecha_venta")
        fecha_primera = limpio.get("fecha_primera_cuota")
        valor_cuota_manual = limpio.get("valor_cuota") or None
        producto = limpio.get("producto_id")
        producto_texto = (limpio.get("producto_texto") or "").strip()

        # --- Producto: del catalogo o escrito a mano ---------------------
        if producto:
            producto_texto = producto.nombre
        elif not producto_texto:
            self.add_error(
                "producto_texto",
                "Elija el producto del catalogo o escriba el nombre a mano.",
            )
            producto_texto = ""

        # --- Dinero: nada de negativos ----------------------------------
        if precio_financiado < 0:
            self.add_error("precio_financiado", "El precio financiado no puede ser negativo.")
        if cuota_inicial < 0:
            self.add_error("cuota_inicial", "La cuota inicial no puede ser negativa.")
        if precio_contado < 0:
            self.add_error("precio_contado", "El precio de contado no puede ser negativo.")

        # --- El saldo financiado se calcula solo ------------------------
        valor_financiado = pesada(precio_financiado - cuota_inicial)
        if valor_financiado < 0:
            self.add_error(
                "cuota_inicial",
                "La cuota inicial no puede ser mayor que el precio financiado.",
            )
            valor_financiado = pesada(0)
        limpio["valor_financiado"] = valor_financiado

        if valor_financiado <= 0:
            self.add_error(
                "precio_financiado",
                "El precio financiado debe ser mayor que la cuota inicial. "
                "Si el cliente solo paga contado, no es un credito.",
            )

        # --- Numero de cuotas vs saldo ----------------------------------
        if numero_cuotas and valor_financiado > 0:
            if numero_cuotas * 1000 > float(valor_financiado) and valor_financiado > 0:
                # mas de 1000 cuotas para un saldo pequeno: casi seguro
                # se equivoco de campo.
                self.add_error(
                    "numero_cuotas",
                    f"Con un saldo de {formato_dinero(valor_financiado)} no alcanza para "
                    f"{numero_cuotas} cuotas. Revise el numero de cuotas.",
                )

        # --- Fechas ------------------------------------------------------
        if fecha_venta and fecha_venta > hoy:
            self.add_error("fecha_venta", "La fecha de la venta no puede ser futura.")
        if fecha_primera and fecha_venta and fecha_primera < fecha_venta:
            self.add_error(
                "fecha_primera_cuota",
                "La primera cuota no puede ser anterior a la fecha de la venta.",
            )
        if fecha_venta and not fecha_venta.year > 2000:
            self.add_error("fecha_venta", "Revise la fecha de la venta.")

        # --- Plan de pagos: que las cuotas sumen exacto -----------------
        if frecuencia and numero_cuotas and valor_financiado > 0 and fecha_primera:
            try:
                plan, valor_base, valor_ultima = generar_plan_pagos(
                    saldo_financiado=valor_financiado,
                    numero_cuotas=numero_cuotas,
                    fecha_primera=fecha_primera,
                    frecuencia=frecuencia,
                    valor_cuota_manual=valor_cuota_manual,
                )
                limpio["valor_cuota"] = valor_base
                self.datos_preview = {
                    "valor_cuota": valor_base,
                    "valor_ultima": valor_ultima,
                    "total": pesada(sum(p["valor"] for p in plan)),
                    "cantidad": len(plan),
                    "primera": plan[0]["fecha"],
                    "ultima": plan[-1]["fecha"],
                    "muestra": plan[:5],
                }
            except ErrorCalculo as error:
                self.add_error("numero_cuotas", str(error))

        return limpio

    def save(self, commit=True):
        credito = super().save(commit=False)
        if self.cleaned_data.get("producto_id"):
            credito.producto = self.cleaned_data["producto_id"]
        credito.valor_financiado = self.cleaned_data.get("valor_financiado", 0)
        credito.valor_cuota = self.cleaned_data.get("valor_cuota") or 0

        # La fecha estimada de fin se calcula aqui para que el credito
        # quede completo desde el primer guardado (se vuelve a confirmar
        # cuando se genera el plan de cuotas).
        frecuencia = self.cleaned_data.get("frecuencia")
        primera = self.cleaned_data.get("fecha_primera_cuota")
        numero = self.cleaned_data.get("numero_cuotas")
        if frecuencia and primera and numero:
            from .servicios.calendario import sumar_frecuencia
            credito.fecha_estimada_fin = sumar_frecuencia(
                primera, frecuencia, numero - 1,
            )

        if self.usuario is not None and not credito.creado_por_id:
            credito.creado_por = self.usuario
        if commit:
            credito.save()
        return credito


class EditarCreditoForm(forms.ModelForm):
    """Editar un credito.

    Los datos que NO se pueden cambiar despues de creado (saldo, numero de
    cuotas, frecuencia) van bloqueados: cambiarlos desbarataria todo el
    historial de pagos. Para eso esta la anulacion.
    """

    class Meta:
        model = ModeloCredito
        fields = [
            "producto_texto", "precio_contado", "precio_financiado",
            "observaciones", "fecha_venta",
        ]
        widgets = {
            "producto_texto": forms.TextInput(attrs={"class": "campo"}),
            "precio_contado": forms.TextInput(attrs={
                "inputmode": "numeric", "class": "campo dinero"}),
            "precio_financiado": forms.TextInput(attrs={
                "inputmode": "numeric", "class": "campo dinero"}),
            "observaciones": forms.Textarea(attrs={"rows": 3, "class": "campo"}),
            "fecha_venta": CampoFecha(),
        }

    def clean_precio_financiado(self):
        valor = limpia_dinero(self.cleaned_data.get("precio_financiado"))
        if valor < self.instance.total_pagado:
            raise ValidationError(
                f"El precio financiado no puede ser menor que lo que ya pago "
                f"el cliente ({formato_dinero(self.instance.total_pagado)})."
            )
        if valor < self.instance.valor_financiado:
            raise ValidationError(
                "No se puede bajar el saldo financiado de un credito que ya "
                "tiene pagos. Use la anulacion del pago para corregir."
            )
        return valor

    def clean_fecha_venta(self):
        fecha = self.cleaned_data.get("fecha_venta")
        if fecha and fecha > timezone.localdate():
            raise ValidationError("La fecha de la venta no puede ser futura.")
        return fecha


# ===========================================================================
# PAGOS
# ===========================================================================


class PagoForm(forms.Form):
    """Registrar un abono.

    El campo `token` es la clave anti-duplicados. Se genera una sola vez al
    abrir la pagina y viaja con cada envio.
    """

    credito = forms.ModelChoiceField(
        queryset=Credito.objects.none(),
        widget=forms.HiddenInput,
    )
    cuota = forms.ModelChoiceField(
        queryset=Cuota.objects.none(),
        required=False,
        widget=forms.HiddenInput,
    )
    valor = CampoDinero(
        label="Valor que recibio *",
        min_value=1,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "class": "campo campo-grande dinero",
            "id": "id_valor", "autofocus": "autofocus",
            "placeholder": "0",
        }),
    )
    metodo = forms.ModelChoiceField(
        queryset=MetodoPago.objects.none(),
        label="Como pago *",
        widget=forms.Select(attrs={"class": "campo"}),
    )
    fecha = forms.DateField(
        label="Fecha del pago *",
        initial=timezone.localdate,
        widget=CampoFecha(),
    )
    referencia = forms.CharField(
        label="Referencia / No. de transaccion",
        required=False,
        widget=forms.TextInput(attrs={
            "class": "campo", "placeholder": "Solo para transferencia, Nequi, etc.",
        }),
    )
    observaciones = forms.CharField(
        label="Observaciones", required=False,
        widget=forms.TextInput(attrs={"class": "campo", "placeholder": "Opcional"}),
    )
    es_anticipo_confirmado = forms.BooleanField(
        required=False, widget=forms.HiddenInput,
    )
    token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        self.credito_fijo = kwargs.pop("credito", None)
        super().__init__(*args, **kwargs)
        self.fields["metodo"].queryset = MetodoPago.objects.filter(activo=True)
        self.fields["metodo"].empty_label = "-- Como pago? --"

        creditos = Credito.objects.filter(estado=EstadoCredito.ACTIVO)
        if self.credito_fijo:
            creditos = creditos.filter(pk=self.credito_fijo.pk)
        self.fields["credito"].queryset = creditos

        # El campo 'cuota' es un selector escondido, pero Django lo valida
        # igual: si su lista de opciones esta vacia, NINGUN envio con cuota
        # pasa. Por eso se arma con las cuotas del credito del formulario.
        if self.credito_fijo:
            cuotas = Cuota.objects.filter(credito=self.credito_fijo)
        elif self.is_bound and self.data.get("credito"):
            cuotas = Cuota.objects.filter(credito_id=self.data.get("credito"))
        else:
            cuotas = Cuota.objects.none()
        self.fields["cuota"].queryset = cuotas

        # El token se genera aqui si el formulario viene vacio. Si ya viene
        # (porque se reenvio la pagina), se conserva el mismo.
        if not self.is_bound:
            self.fields["token"].initial = uuid.uuid4().hex
        if not self.is_bound:
            self.fields["fecha"].initial = timezone.localdate()

    def clean_token(self):
        token = (self.cleaned_data.get("token") or "").strip()
        if not token:
            # Si el navegador borro el token, se genera uno nuevo. El
            # riesgo de duplicar se cubre con la doble confirmacion del
            # boton y con revisar la ultima cuota.
            token = uuid.uuid4().hex
        return token

    def clean_valor(self):
        valor = limpia_dinero(self.cleaned_data.get("valor"))
        if valor <= 0:
            raise ValidationError("Escriba el valor recibido. Debe ser mayor que cero.")
        if valor > 500_000_000:
            raise ValidationError(
                "Ese valor es demasiado alto. Revise las cifras "
                "(maximo 500 millones por pago)."
            )
        return valor

    def clean_fecha(self):
        fecha = self.cleaned_data.get("fecha")
        hoy = timezone.localdate()
        if fecha and fecha > hoy:
            raise ValidationError("No se puede registrar un pago con fecha futura.")
        if fecha and fecha < hoy - timezone.timedelta(days=365 * 3):
            raise ValidationError("Esa fecha es muy vieja. Revise la fecha del pago.")
        return fecha

    def clean(self):
        limpio = super().clean()
        credito = limpio.get("credito")
        cuota = limpio.get("cuota")

        if credito:
            if credito.estado == EstadoCredito.ANULADO:
                raise ValidationError("Este credito esta anulado. No admite pagos.")
            if credito.estado == EstadoCredito.PAGADO:
                raise ValidationError(
                    "Este credito ya esta pagado completo. No se pueden "
                    "registrar mas pagos."
                )
            if cuota and cuota.credito_id != credito.pk:
                raise ValidationError("La cuota no pertenece a este credito.")
        return limpio


class AnularPagoForm(forms.Form):
    """Anular un pago mal digitado (no se borra, se marca)."""

    motivo = forms.CharField(
        label="Motivo de la anulacion *",
        min_length=5,
        widget=forms.Textarea(attrs={
            "rows": 3, "class": "campo",
            "placeholder": "Ej: se digito 500.000 en vez de 50.000",
        }),
    )


class CorregirPagoForm(forms.Form):
    """Corregir el valor o la fecha de un pago, guardando el antes."""

    valor = CampoDinero(
        label="Valor correcto *", min_value=1,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "class": "campo dinero"}),
    )
    fecha = forms.DateField(
        label="Fecha correcta *",
        widget=CampoFecha(),
    )
    motivo = forms.CharField(
        label="Por que se corrige *", min_length=5,
        widget=forms.TextInput(attrs={"class": "campo"}),
    )


# ===========================================================================
# CONFIGURACION
# ===========================================================================


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = [
            "nombre_negocio", "logo", "telefono", "direccion", "nit",
            "mensaje_comprobante", "moneda_simbolo", "moneda_codigo",
            "moneda_decimales", "formato_fecha",
            "umbral_excelente", "umbral_bueno", "dias_para_moroso",
            "dias_gracia", "minimo_cuotas_para_clasificar",
        ]
        widgets = {
            "nombre_negocio": forms.TextInput(attrs={"class": "campo"}),
            "logo": forms.ClearableFileInput(attrs={"class": "campo", "accept": "image/*"}),
            "telefono": forms.TextInput(attrs={"class": "campo"}),
            "direccion": forms.TextInput(attrs={"class": "campo"}),
            "nit": forms.TextInput(attrs={"class": "campo"}),
            "mensaje_comprobante": forms.Textarea(attrs={"rows": 2, "class": "campo"}),
            "moneda_simbolo": forms.TextInput(attrs={"class": "campo pequeno"}),
            "moneda_codigo": forms.TextInput(attrs={"class": "campo pequeno"}),
            "moneda_decimales": forms.NumberInput(attrs={"class": "campo pequeno"}),
            "formato_fecha": forms.TextInput(attrs={"class": "campo pequeno"}),
            "umbral_excelente": forms.NumberInput(attrs={
                "class": "campo pequeno", "min": 0, "max": 100}),
            "umbral_bueno": forms.NumberInput(attrs={
                "class": "campo pequeno", "min": 0, "max": 100}),
            "dias_para_moroso": forms.NumberInput(attrs={
                "class": "campo pequeno", "min": 1, "max": 365}),
            "dias_gracia": forms.NumberInput(attrs={
                "class": "campo pequeno", "min": 0, "max": 30}),
            "minimo_cuotas_para_clasificar": forms.NumberInput(attrs={
                "class": "campo pequeno", "min": 0, "max": 100}),
        }

    def clean_nombre_negocio(self):
        valor = (self.cleaned_data.get("nombre_negocio") or "").strip()
        if len(valor) < 2:
            raise ValidationError("Escriba el nombre del negocio.")
        return valor

    def clean_umbral_excelente(self):
        return self._porcentaje("umbral_excelente", self.cleaned_data.get("umbral_excelente"))

    def clean_umbral_bueno(self):
        return self._porcentaje("umbral_bueno", self.cleaned_data.get("umbral_bueno"))

    def _porcentaje(self, campo, valor):
        if valor is None:
            return 0
        if valor < 0 or valor > 100:
            raise ValidationError("El porcentaje debe estar entre 0 y 100.")
        return valor

    def clean(self):
        limpio = super().clean()
        excelente = limpio.get("umbral_excelente", 0)
        bueno = limpio.get("umbral_bueno", 0)
        if excelente < bueno:
            self.add_error(
                "umbral_bueno",
                f"El umbral de BUENO ({bueno}%) no puede ser mayor que el de "
                f"EXCELENTE ({excelente}%).",
            )
        return limpio


class FrecuenciaPagoForm(forms.ModelForm):
    class Meta:
        model = FrecuenciaPago
        fields = ["nombre", "dias", "unidad", "activo", "orden"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "campo"}),
            "dias": forms.NumberInput(attrs={"class": "campo pequeno", "min": 1}),
            "orden": forms.NumberInput(attrs={"class": "campo pequeno"}),
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip().upper()
        if not nombre:
            raise ValidationError("Escriba el nombre de la frecuencia.")
        return nombre

    def clean_dias(self):
        dias = self.cleaned_data.get("dias")
        if not dias or dias < 1:
            raise ValidationError("El intervalo debe ser de 1 o mas.")
        if dias > 365:
            raise ValidationError("Un intervalo de mas de 365 dias no es un pago.")
        return dias


class MetodoPagoForm(forms.ModelForm):
    class Meta:
        model = MetodoPago
        fields = ["nombre", "activo", "orden"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "campo"}),
            "orden": forms.NumberInput(attrs={"class": "campo pequeno"}),
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise ValidationError("Escriba el nombre del metodo de pago.")
        return nombre


# ===========================================================================
# USUARIOS
# ===========================================================================


class UsuarioForm(forms.Form):
    """Crear un usuario nuevo (cobrador o administrador)."""

    nombre = forms.CharField(
        label="Nombre completo *",
        widget=forms.TextInput(attrs={"class": "campo", "autofocus": "autofocus"}),
    )
    usuario = forms.CharField(
        label="Usuario (para entrar) *",
        widget=forms.TextInput(attrs={"class": "campo", "autocomplete": "off"}),
    )
    clave = forms.CharField(
        label="Contrasena *",
        widget=forms.PasswordInput(attrs={"class": "campo", "autocomplete": "new-password"}),
    )
    clave2 = forms.CharField(
        label="Repita la contrasena *",
        widget=forms.PasswordInput(attrs={"class": "campo", "autocomplete": "new-password"}),
    )
    rol = forms.ChoiceField(
        label="Rol *",
        choices=Rol.choices,
        widget=forms.Select(attrs={"class": "campo"}),
    )
    telefono = forms.CharField(
        label="Telefono", required=False,
        widget=forms.TextInput(attrs={"class": "campo", "inputmode": "tel"}),
    )
    activo = forms.BooleanField(label="Usuario activo", initial=True, required=False)

    def clean_usuario(self):
        from django.contrib.auth.models import User
        nombre = (self.cleaned_data.get("usuario") or "").strip().lower()
        if len(nombre) < 3:
            raise ValidationError("El usuario debe tener al menos 3 letras.")
        if not nombre.replace("_", "").replace(".", "").isalnum():
            raise ValidationError(
                "El usuario solo puede tener letras, numeros, punto y guion bajo."
            )
        if User.objects.filter(username__iexact=nombre).exists():
            raise ValidationError(f"Ya existe un usuario llamado '{nombre}'.")
        return nombre

    def clean_clave(self):
        clave = self.cleaned_data.get("clave") or ""
        if len(clave) < 6:
            raise ValidationError("La contrasena debe tener al menos 6 caracteres.")
        if clave.isdigit():
            raise ValidationError(
                "La contrasena no puede ser solo numeros. Ponga tambien letras."
            )
        if clave.lower() in ("password", "123456", "admin123", "123456789"):
            raise ValidationError("Esa contrasena es muy facil de adivinar. Ponga otra.")
        return clave

    def clean(self):
        limpio = super().clean()
        if limpio.get("clave") != limpio.get("clave2"):
            self.add_error("clave2", "Las dos contrasenas no son iguales.")
        return limpio


class CambiarClaveForm(forms.Form):
    """Cambiar la propia contrasena."""

    actual = forms.CharField(
        label="Contrasena actual *",
        widget=forms.PasswordInput(attrs={"class": "campo", "autofocus": "autofocus"}),
    )
    nueva = forms.CharField(
        label="Contrasena nueva *",
        widget=forms.PasswordInput(attrs={"class": "campo", "autocomplete": "new-password"}),
    )
    nueva2 = forms.CharField(
        label="Repita la contrasena nueva *",
        widget=forms.PasswordInput(attrs={"class": "campo", "autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        # Se guarda el usuario para poder comprobar la contrasena actual.
        self.usuario = kwargs.pop("usuario", None)
        super().__init__(*args, **kwargs)

    def clean_actual(self):
        from django.contrib.auth import authenticate
        clave = self.cleaned_data.get("actual")
        if self.usuario is None:
            raise ValidationError("No se pudo identificar al usuario.")
        if not authenticate(username=self.usuario.get_username(), password=clave):
            raise ValidationError("La contrasena actual no es correcta.")
        return clave

    def clean_nueva(self):
        clave = self.cleaned_data.get("nueva") or ""
        if len(clave) < 6:
            raise ValidationError("La contrasena nueva debe tener al menos 6 caracteres.")
        if clave.isdigit():
            raise ValidationError("La contrasena no puede ser solo numeros.")
        return clave

    def clean(self):
        limpio = super().clean()
        if limpio.get("nueva") != limpio.get("nueva2"):
            self.add_error("nueva2", "Las dos contrasenas nuevas no son iguales.")
        return limpio
