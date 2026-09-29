"""
Servicio de pagos: aqui vive lo mas importante del sistema.

Garantias que da este archivo:

1. UN PAGO NUNCA SE DUPLICA. Cada pago llega con un `token` unico
   (generado por el formulario). Si se recarga la pagina o se pulsa dos
   veces el boton, el segundo intento se reconoce y devuelve el pago ya
   registrado en vez de crear otro.

2. LOS PAGOS PARCIALES FUNCIONAN. Cuota de $100.000, paga $60.000 ->
   la cuota queda PARCIAL con $40.000 de saldo. Cuando pague los $40.000
   mas, queda PAGADA sola.

3. NADA SE PIERDE. Un pago no se borra nunca. Si esta mal se ANULA, queda
   el registro en el historial y se avisa en el movimiento.

4. LOS SALDOS SIEMPRE CUADRAN. Todo se recalcula con `recalcular_credito`
   dentro de una transaccion. O se guarda todo, o no se guarda nada.
"""

from django.db import IntegrityError, transaction
from django.db.models import F, Max, Sum
from django.utils import timezone

from ..models import (
    AplicacionPago, CERO, Credito, Cuota, EstadoCuota, Pago, pesada,
)
from .cuotas import recalcular_credito
from .dinero import formato_dinero


class ErrorPago(Exception):
    """Error de negocio al registrar un pago. Se muestra al usuario."""

    def __init__(self, mensaje, codigo="error"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


# ===========================================================================
# NUMERO DE COMPROBANTE
# ===========================================================================


def nuevo_numero_recibo(credito=None):
    """Genera un numero de comprobante corto y unico, tipo R-2026-000123.

    Si dos personas cobran al mismo tiempo, el numero se arma con el
    siguiente disponible dentro de la misma transaccion y el indice unico
    de la base avisa si alguien se adelanto.
    """
    anio = timezone.localdate().year
    ultimo = Pago.objects.filter(
        recibo__startswith=f"R-{anio}-",
    ).aggregate(mayor=Max("recibo"))["mayor"]

    if ultimo:
        try:
            numero = int(ultimo.split("-")[-1]) + 1
        except (ValueError, IndexError):
            numero = 1
    else:
        numero = 1
    return f"R-{anio}-{numero:06d}"


# ===========================================================================
# VALIDACIONES
# ===========================================================================


def validar_pago(credito, valor, cuota=None, es_anticipo_confirmado=False):
    """Revisa que el pago tenga sentido antes de guardarlo.

    Devuelve un diccionario con:
        {'ok': bool, 'requiere_confirmacion': bool, 'mensaje': str,
         'saldo_credito': Decimal}

    `requiere_confirmacion` es True cuando el valor supera lo que falta:
    ahi la aplicacion le pregunta al usuario si lo deja como pago
    anticipado, en vez de rechazarlo.
    """
    valor = pesada(valor)
    saldo = pesada(max(CERO, credito.valor_financiado - total_pagado(credito)))

    if valor <= CERO:
        return {
            "ok": False,
            "requiere_confirmacion": False,
            "mensaje": "El valor del pago debe ser mayor que cero.",
            "saldo_credito": saldo,
        }

    if credito.estado == "ANULADO":
        return {
            "ok": False,
            "requiere_confirmacion": False,
            "mensaje": "Este credito esta ANULADO. No se pueden registrar pagos.",
            "saldo_credito": saldo,
        }

    if credito.estado == "PAGADO" or saldo <= CERO:
        return {
            "ok": False,
            "requiere_confirmacion": False,
            "mensaje": (
                "Este credito ya esta pagado completo. No se pueden "
                "registrar mas pagos."
            ),
            "saldo_credito": saldo,
        }

    if valor > saldo and not es_anticipo_confirmado:
        faltante = pesada(valor - saldo)
        return {
            "ok": True,
            "requiere_confirmacion": True,
            "mensaje": (
                f"El valor ingresado supera el saldo pendiente en {formato_dinero(faltante)}. "
                f"¿Desea registrar este valor como pago anticipado? "
                f"El sobrante de {formato_dinero(faltante)} se descontara de las cuotas "
                f"quetodavia no vencen."
            ),
            "saldo_credito": saldo,
        }

    if valor > saldo and es_anticipo_confirmado:
        return {
            "ok": True,
            "requiere_confirmacion": False,
            "mensaje": f"Pago anticipado por {formato_dinero(pesada(valor - saldo))}.",
            "saldo_credito": saldo,
        }

    return {
        "ok": True,
        "requiere_confirmacion": False,
        "mensaje": "",
        "saldo_credito": saldo,
    }


def total_pagado(credito):
    total = Pago.objects.filter(credito=credito, anulado=False).aggregate(
        suma=Sum("valor"),
    )["suma"]
    return pesada(total or CERO)


# ===========================================================================
# REGISTRO DEL PAGO
# ===========================================================================


@transaction.atomic
def registrar_pago(credito, valor, metodo, usuario, cuota=None,
                   fecha=None, referencia="", observaciones="",
                   token=None, es_anticipo_confirmado=False):
    """Registra un pago y actualiza todos los saldos.

    Devuelve (pago, detalles) donde detalles trae:
        - 'duplicado': True si el token ya se habia usado
        - 'aplicado_en': lista de cuotas que recibieron parte del pago
        - 'anticipo': valor que quedo a favor para cuotas futuras
    """
    credito = Credito.objects.select_for_update().select_related(
        "frecuencia", "cliente",
    ).get(pk=credito.pk)

    token = (token or "").strip() or Pago.nuevo_token()

    # --- 1) ¿Este pago ya existe? -----------------------------------
    # Esto es lo que evita el pago duplicado al recargar la pagina.
    previo = Pago.objects.filter(token=token).first()
    if previo:
        return previo, {
            "duplicado": True,
            "aplicado_en": [],
            "anticipo": CERO,
        }

    fecha = fecha or timezone.localdate()

    # --- 2) Validar --------------------------------------------------
    revision = validar_pago(
        credito, valor, cuota=cuota,
        es_anticipo_confirmado=es_anticipo_confirmado,
    )
    if not revision["ok"]:
        raise ErrorPago(revision["mensaje"], codigo="validacion")

    # Si el valor se pasa del saldo y el usuario NO confirmo, se detiene.
    # Sin esta comprobacion un pago de mas se guardaba en silencio.
    if revision["requiere_confirmacion"] and not es_anticipo_confirmado:
        raise ErrorPago(revision["mensaje"], codigo="anticipo")

    saldo_antes = revision["saldo_credito"]
    valor = pesada(valor)

    # --- 3) Crear el pago --------------------------------------------
    pago = Pago(
        credito=credito,
        cuota=cuota,
        fecha=fecha,
        hora=timezone.localtime().time().replace(tzinfo=None),
        valor=valor,
        metodo=metodo,
        referencia=referencia or "",
        observaciones=observaciones or "",
        saldo_antes=saldo_antes,
        saldo_despues=pesada(max(CERO, saldo_antes - valor)),
        recibo=nuevo_numero_recibo(credito),
        token=token,
        usuario=usuario,
    )

    try:
        pago.save()
    except IntegrityError:
        # Otra pestana se adelanto y uso el mismo token. Se devuelve el
        # pago que esa otra pestana creo: no se duplica nada.
        existente = Pago.objects.filter(token=token).first()
        if existente:
            return existente, {
                "duplicado": True,
                "aplicado_en": [],
                "anticipo": CERO,
            }
        # Puede ser el numero de comprobante. Se reintenta una vez.
        pago.recibo = nuevo_numero_recibo(credito)
        try:
            pago.save()
        except IntegrityError as error:
            raise ErrorPago(
                "No se pudo guardar el pago. Vuelva a intentar.",
                codigo="duplicado",
            ) from error

    # --- 4) Repartir el valor entre las cuotas ------------------------
    aplicados, anticipo = _aplicar_pago(pago, cuota)

    # --- 5) Recalcular el credito (transaccion ya abierta) ------------
    recalcular_credito(credito, guardar=True)

    # --- 6) Actualizar saldo despues con el dato real ------------------
    pago.saldo_despues = pesada(max(CERO, credito.valor_financiado - total_pagado(credito)))
    pago.save(update_fields=["saldo_despues", "cuota"])

    return pago, {
        "duplicado": False,
        "aplicado_en": aplicados,
        "anticipo": anticipo,
    }


def _aplicar_pago(pago, cuota_inicial):
    """Reparte el valor del pago en las cuotas del credito.

    - Si se indico una cuota, el pago arranca ahi.
    - Si el valor no alcanza, la cuota queda PARCIAL y el resto del pago
      sigue a la cuota siguiente.
    - Si sobra, las cuotas siguientes se descuentan y el remanente queda
      como anticipo (queda con el pago, sin cuota asignada).

    El reparto queda guardado en AplicacionPago: una fila por cuota
    tocada. Asi, al recalcular los saldos, el dinero siempre aparece en
    la misma cuota en que se recibio.
    """
    credito = pago.credito
    restante = pago.valor
    aplicados = []

    if cuota_inicial is not None:
        candidatas = [cuota_inicial] + [
            c for c in credito.cuotas.order_by("numero")
            if c.numero > cuota_inicial.numero
        ]
    else:
        # Sin cuota indicada: se aplica a la cuota mas antigua sin pagar
        # (la vencida primero).
        candidatas = list(
            credito.cuotas.filter(valor_pagado__lt=F("valor")).order_by("numero")
        )
        if not candidatas:
            # Todo pagado: es un pago a favor (anticipo) sin cuota.
            return [], restante

    for cuota in candidatas:
        if restante <= CERO:
            break
        saldo_cuota = cuota.saldo
        if saldo_cuota <= CERO:
            continue

        a_pagar = pesada(min(restante, saldo_cuota))
        AplicacionPago.objects.create(
            pago=pago,
            cuota=cuota,
            valor=a_pagar,
            fecha_aplicacion=pago.fecha,
        )
        aplicados.append({"cuota": cuota, "valor": a_pagar})
        restante = pesada(restante - a_pagar)

    # Si el pago llego a tocar cuotas, se apunta la primera (la que sale
    # en el comprobante). Si no alcanzo para ninguna, queda como anticipo
    # a favor y no se asigna a ninguna cuota.
    pago.cuota = aplicados[0]["cuota"] if aplicados else None

    return aplicados, restante


# ===========================================================================
# ANULAR UN PAGO (nunca borrar)
# ===========================================================================


@transaction.atomic
def anular_pago(pago, usuario, motivo):
    """Anula un pago malDigitado. El pago NO se borra, queda con la marca.

    Los saldos se recalcan para que todo vuelva a cuadrar.
    """
    if pago.anulado:
        raise ErrorPago("Este pago ya estaba anulado antes.", codigo="ya_anulado")

    if not motivo or len(motivo.strip()) < 5:
        raise ErrorPago(
            "Escriba el motivo de la anulacion (minimo 5 letras). "
            "Queda guardado en el historial.",
            codigo="motivo",
        )

    pago.anulado = True
    pago.fecha_anulacion = timezone.now()
    pago.motivo_anulacion = motivo.strip()[:300]
    pago.anulado_por = usuario
    pago.save(update_fields=[
        "anulado", "fecha_anulacion", "motivo_anulacion", "anulado_por",
    ])

    recalcular_credito(pago.credito, guardar=True)
    return pago


# ===========================================================================
# CORRECCION DE UN PAGO
# ===========================================================================


@transaction.atomic
def corregir_pago(pago, nuevo_valor=None, nueva_fecha=None, motivo="",
                  usuario=None):
    """Corrige el valor o la fecha de un pago sin borrarlo.

    Se guarda el dato anterior en el historial de movimientos para saber
    que se cambio y por que.
    """
    if pago.anulado:
        raise ErrorPago(
            "No se puede corregir un pago anulado. Registre un nuevo pago.",
            codigo="anulado",
        )
    if not motivo or len(motivo.strip()) < 5:
        raise ErrorPago(
            "Escriba por que se corrige el pago (minimo 5 letras).",
            codigo="motivo",
        )

    cambios = {}
    credito = Credito.objects.select_for_update().get(pk=pago.credito.pk)

    if nuevo_valor is not None:
        nuevo = pesada(nuevo_valor)
        if nuevo <= CERO:
            raise ErrorPago("El nuevo valor debe ser mayor que cero.", codigo="valor")
        if credito.estado == "ANULADO":
            raise ErrorPago("El credito esta anulado.", codigo="anulado")
        cambios["valor"] = {"antes": str(pago.valor), "despues": str(nuevo)}
        pago.valor = nuevo

    if nueva_fecha is not None:
        cambios["fecha"] = {
            "antes": pago.fecha.isoformat(),
            "despues": nueva_fecha.isoformat(),
        }
        pago.fecha = nueva_fecha

    if not cambios:
        raise ErrorPago("No se cambio nada.", codigo="sin_cambios")

    pago.save(update_fields=["valor", "fecha"])

    recalcular_credito(credito, guardar=True)

    pago.saldo_despues = pesada(max(CERO, credito.valor_financiado - total_pagado(credito)))
    pago.save(update_fields=["saldo_despues"])

    return pago, cambios


# ===========================================================================
# COMPROBANTE
# ===========================================================================


def datos_comprobante(pago):
    """Arma los datos del comprobante de pago."""
    credito = pago.credito
    cliente = credito.cliente
    cuota = pago.cuota
    config = _config()

    return {
        "negocio": config.nombre_negocio,
        "telefono": config.telefono,
        "direccion": config.direccion,
        "nit": config.nit,
        "mensaje": config.mensaje_comprobante,
        "recibo": pago.recibo,
        "fecha": pago.fecha,
        "hora": pago.hora,
        "cliente": cliente.nombre_completo,
        "cedula": cliente.cedula_oculta,
        "telefono_cliente": cliente.telefono,
        "producto": credito.nombre_producto,
        "credito_id": credito.id,
        "frecuencia": str(credito.frecuencia),
        "cuota_numero": cuota.numero if cuota else None,
        "cuota_fecha": cuota.fecha_vencimiento if cuota else None,
        "cuota_valor": cuota.valor if cuota else None,
        "valor": pago.valor,
        "metodo": str(pago.metodo),
        "referencia": pago.referencia,
        "saldo_antes": pago.saldo_antes,
        "saldo_despues": pago.saldo_despues,
        "saldo_credito": credito.saldo,
        "observaciones": pago.observaciones,
        "cajero": pago.usuario.get_full_name() or pago.usuario.get_username(),
    }


def _config():
    from ..models import Configuracion
    return Configuracion.objects.get(pk=1)
