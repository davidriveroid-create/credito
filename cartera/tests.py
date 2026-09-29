"""
PRUEBAS AUTOMATICAS DEL SISTEMA DE VENTAS A CREDITO.

Estas pruebas revisan lo que de verdad importa: que los numeros cuadren y
que no se pierda ni se duplique nada.

    .venv\\Scripts\\python.exe manage.py test cartera

Si todas pasan, el sistema cumple lo que promete.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import (
    CERO, Cliente, Credito, Cuota, EstadoCredito, EstadoCuota, FrecuenciaPago,
    MetodoPago, Pago, PerfilUsuario, Producto, Rol, pesada,
)
from .servicios import cartera as servicio_cartera
from .servicios.calendario import (
    ErrorCalculo, calcular_fechas, calcular_valor_cuota, generar_plan_pagos,
    sumar_frecuencia,
)
from .servicios.cuotas import cuota_siguiente, crear_plan_credito, recalcular_credito
from .servicios.dinero import formato_dinero, numero_escrito
from .servicios.pagos import ErrorPago, anular_pago, registrar_pago
from .servicios.regularidad import calcular_regularidad
from .servicios.regularidad import configuracion as config


def hoy():
    return timezone.localdate()


class BasePrueba(TestCase):
    """Datos minimos que usan todas las pruebas."""

    @classmethod
    def setUpTestData(cls):
        cls.usuario = User.objects.create_user(
            username="probador", password="prueba123", first_name="Probador",
        )
        cls.metodo = MetodoPago.objects.create(nombre="Efectivo", orden=10)
        cls.semanal = FrecuenciaPago.objects.create(
            nombre="SEMANAL", dias=7, unidad=FrecuenciaPago.Unidad.DIAS, orden=20,
        )
        cls.mensual = FrecuenciaPago.objects.create(
            nombre="MENSUAL", dias=1, unidad=FrecuenciaPago.Unidad.MESES, orden=40,
        )
        cls.diario = FrecuenciaPago.objects.create(
            nombre="DIARIO", dias=1, unidad=FrecuenciaPago.Unidad.DIAS, orden=10,
        )
        config()

    def hacer_cliente(self, **kwargs):
        datos = {
            "nombres": "Juan", "apellidos": "Perez", "cedula": "123456789",
            "telefono": "3000000000", "direccion": "Calle 1 # 2-3",
            "ciudad": "Bogota",
        }
        datos.update(kwargs)
        return Cliente.objects.create(**datos)

    def hacer_credito(self, cliente=None, frecuencia=None, cuotas=20,
                      saldo=Decimal("2000000"), primera=None, **kwargs):
        """Crea un credito CON sus cuotas ya generadas.

        Por defecto el plan arranca HOY, que es como se hace en la vida real.
        Las pruebas que necesitan cuotas vencidas pasan `primera` con una
        fecha en el pasado.
        """
        cliente = cliente or self.hacer_cliente()
        frecuencia = frecuencia or self.semanal
        primera = primera or hoy()

        credito = Credito.objects.create(
            cliente=cliente,
            producto_texto=kwargs.pop("producto_texto", "Xiaomi Scooter"),
            fecha_venta=primera,
            precio_contado=Decimal("1000000"),
            precio_financiado=saldo + Decimal("200000"),
            cuota_inicial=Decimal("200000"),
            valor_financiado=saldo,
            numero_cuotas=cuotas,
            frecuencia=frecuencia,
            fecha_primera_cuota=primera,
            valor_cuota=pesada(saldo / cuotas),
            fecha_estimada_fin=primera,
            creado_por=self.usuario,
            **kwargs,
        )
        crear_plan_credito(credito)
        credito.refresh_from_db()
        return credito

    def pagar(self, credito, valor, cuota=None, fecha=None, token=None,
              metodo=None, usuario=None):
        return registrar_pago(
            credito=credito,
            valor=Decimal(str(valor)),
            metodo=metodo or self.metodo,
            usuario=usuario or self.usuario,
            cuota=cuota,
            fecha=fecha or hoy(),
            token=token,
        )


# ===========================================================================
# CALENDARIO Y DIVISION DE CUOTAS
# ===========================================================================


class PruebaCalendario(BasePrueba):

    def test_diario_suma_exactamente_un_dia(self):
        fecha = hoy()
        self.assertEqual(sumar_frecuencia(fecha, self.diario, 1), fecha + timedelta(days=1))

    def test_semanal_suma_siete_dias(self):
        fecha = hoy()
        self.assertEqual(
            sumar_frecuencia(fecha, self.semanal, 3), fecha + timedelta(days=21)
        )

    def test_quincenal_suma_quince_dias(self):
        quincenal = FrecuenciaPago.objects.create(
            nombre="QUINCENAL", dias=15, unidad=FrecuenciaPago.Unidad.DIAS)
        fecha = hoy()
        self.assertEqual(
            sumar_frecuencia(fecha, quincenal, 2), fecha + timedelta(days=30)
        )

    def test_mensual_usa_meses_de_calendario(self):
        """El pago mensual no es '30 dias': son meses de verdad."""
        from datetime import date
        self.assertEqual(
            sumar_frecuencia(date(2026, 1, 15), self.mensual, 1), date(2026, 2, 15)
        )
        self.assertEqual(
            sumar_frecuencia(date(2026, 1, 15), self.mensual, 12), date(2027, 1, 15)
        )

    def test_mensual_nunca_cae_en_una_fecha_que_no_existe(self):
        """31 de enero + 1 mes = 28/29 de febrero, no 3 de marzo."""
        from datetime import date
        resultado = sumar_frecuencia(date(2026, 1, 31), self.mensual, 1)
        self.assertEqual(resultado.month, 2)
        self.assertLessEqual(resultado.day, 29)

    def test_las_cuotas_suman_exactamente_el_saldo(self):
        """REGLA DE ORO: ni un peso de mas ni de menos."""
        for saldo in ("1800000", "1000000", "999999", "333333", "100000", "7000"):
            for cuotas in (1, 3, 12, 36, 100):
                plan, _, _ = generar_plan_pagos(
                    saldo_financiado=Decimal(saldo),
                    numero_cuotas=cuotas,
                    fecha_primera=hoy(),
                    frecuencia=self.diario,
                )
                total = sum(p["valor"] for p in plan)
                self.assertEqual(
                    total, Decimal(saldo),
                    f"Fallo con saldo {saldo} en {cuotas} cuotas: "
                    f"sumaron {total} en vez de {saldo}",
                )

    def test_ultima_cuota_ajusta_el_redondeo(self):
        """Ejemplo del enunciado: 1.800.000 en 36 cuotas diarias."""
        plan, valor_base, valor_ultima = generar_plan_pagos(
            saldo_financiado=Decimal("1800000"),
            numero_cuotas=36,
            fecha_primera=hoy(),
            frecuencia=self.diario,
        )
        self.assertEqual(len(plan), 36)
        self.assertEqual(valor_base, Decimal("50000"))
        # 36 x 50.000 = 1.800.000 exacto, la ultima no se adjusts
        self.assertEqual(valor_ultima, Decimal("50000"))

    def test_valor_manual_se_respeta_y_ultima_ajusta(self):
        """Si el usuario pone la cuota, la ultima cuadra la cuenta."""
        plan, valor_base, valor_ultima = generar_plan_pagos(
            saldo_financiado=Decimal("1000000"),
            numero_cuotas=3,
            fecha_primera=hoy(),
            frecuencia=self.mensual,
            valor_cuota_manual=Decimal("300000"),
        )
        self.assertEqual(valor_base, Decimal("300000"))
        self.assertEqual(valor_ultima, Decimal("400000"))
        self.assertEqual(sum(p["valor"] for p in plan), Decimal("1000000"))

    def test_divisiones_imposibles_dan_error_claro(self):
        with self.assertRaises(ErrorCalculo):
            calcular_valor_cuota(Decimal("100"), 1000)      # 10 centavos por cuota
        with self.assertRaises(ErrorCalculo):
            generar_plan_pagos(Decimal("0"), 10, hoy(), self.diario)
        with self.assertRaises(ErrorCalculo):
            generar_plan_pagos(Decimal("1000"), 0, hoy(), self.diario)

    def test_las_fechas_no_se_repiten(self):
        fechas = calcular_fechas(hoy(), self.diario, 30)
        self.assertEqual(len(fechas), 30)
        self.assertEqual(len(set(fechas)), 30, "Hay fechas repetidas en el plan")


# ===========================================================================
# GENERACION DEL PLAN DE PAGOS
# ===========================================================================


class PruebaGeneracionPlan(BasePrueba):

    def test_se_generan_todas_las_cuotas(self):
        credito = self.hacer_credito(cuotas=20)
        self.assertEqual(credito.cuotas.count(), 20)

    def test_las_cuotas_generadas_suman_el_valor_financiado(self):
        credito = self.hacer_credito(saldo=Decimal("1500000"), cuotas=15)
        suma = sum(c.valor for c in credito.cuotas.all())
        self.assertEqual(suma, credito.valor_financiado)

    def test_todas_las_cuotas_nacen_pendientes(self):
        credito = self.hacer_credito()
        for cuota in credito.cuotas.all():
            self.assertEqual(cuota.valor_pagado, CERO)
            self.assertEqual(cuota.estado_real(), EstadoCuota.PENDIENTE)

    def test_generar_dos_veces_no_duplica_cuotas(self):
        """Este es el error clasico. No puede pasar."""
        credito = self.hacer_credito(cuotas=10)
        antes = credito.cuotas.count()
        crear_plan_credito(credito)
        crear_plan_credito(credito)
        self.assertEqual(credito.cuotas.count(), antes)

    def test_numero_cuota_es_unico_en_el_credito(self):
        from django.db import IntegrityError, transaction
        credito = self.hacer_credito(cuotas=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Cuota.objects.create(
                    credito=credito, numero=1,
                    fecha_vencimiento=hoy(), valor=Decimal("1000"),
                )

    def test_la_fecha_estimada_es_la_ultima_cuota(self):
        credito = self.hacer_credito(cuotas=10)
        ultima = credito.cuotas.order_by("numero").last()
        self.assertEqual(credito.fecha_estimada_fin, ultima.fecha_vencimiento)


# ===========================================================================
# PAGOS: PARCIALES, ANTICIPOS E IDEMPOTENCIA
# ===========================================================================


class PruebaPagos(BasePrueba):

    def test_pago_completo_marca_la_cuota_pagada(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()

        pago, _ = self.pagar(credito, cuota.valor, cuota=cuota)

        cuota.refresh_from_db()
        self.assertEqual(cuota.estado_real(), EstadoCuota.PAGADA)
        self.assertEqual(cuota.valor_pagado, cuota.valor)
        self.assertIsNotNone(cuota.fecha_pago)
        self.assertEqual(pago.valor, cuota.valor)

    def test_pago_parcial_deja_la_cuota_en_parcial(self):
        """Ejemplo del enunciado: cuota 100.000, paga 60.000."""
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        self.assertEqual(cuota.valor, Decimal("400000"))  # 2.000.000 / 5

        self.pagar(credito, Decimal("60000"), cuota=cuota)

        cuota.refresh_from_db()
        self.assertEqual(cuota.estado_real(), EstadoCuota.PARCIAL)
        self.assertEqual(cuota.valor_pagado, Decimal("60000"))
        self.assertEqual(cuota.saldo, Decimal("340000"))

    def test_completar_un_parcial_pasa_a_pagada(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()

        self.pagar(credito, Decimal("60000"), cuota=cuota)
        cuota.refresh_from_db()
        self.assertEqual(cuota.estado_real(), EstadoCuota.PARCIAL)

        self.pagar(credito, cuota.saldo, cuota=cuota)
        cuota.refresh_from_db()
        self.assertEqual(cuota.estado_real(), EstadoCuota.PAGADA)
        self.assertEqual(cuota.saldo, CERO)

    def test_los_abonos_parciales_no_se_pisan(self):
        """Cada abono queda en el historial. Nada se sobrescribe."""
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()

        self.pagar(credito, Decimal("100000"), cuota=cuota)
        self.pagar(credito, Decimal("150000"), cuota=cuota)

        self.assertEqual(cuota.aplicaciones.filter(pago__anulado=False).count(), 2)
        cuota.refresh_from_db()
        self.assertEqual(cuota.valor_pagado, Decimal("250000"))

    def test_pago_anticipado_se_reparte_entre_cuotas(self):
        """Si paga mas que la cuota, el sobrante descuenta las siguientes."""
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        valor_cuota = cuota.valor

        pago, detalles = self.pagar(credito, valor_cuota * 2, cuota=cuota)

        primera = credito.cuotas.get(numero=1)
        segunda = credito.cuotas.get(numero=2)
        tercera = credito.cuotas.get(numero=3)
        self.assertEqual(primera.estado_real(), EstadoCuota.PAGADA)
        self.assertEqual(segunda.estado_real(), EstadoCuota.PAGADA)
        self.assertEqual(tercera.valor_pagado, CERO)

        # Y lo mas importante: el dinero sobrevive a un recalculo.
        recalcular_credito(credito)
        primera = credito.cuotas.get(numero=1)
        segunda = credito.cuotas.get(numero=2)
        self.assertEqual(primera.valor_pagado, valor_cuota)
        self.assertEqual(segunda.valor_pagado, valor_cuota)
        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, valor_cuota * 2)

    def test_pago_mayor_al_saldo_pide_confirmacion(self):
        credito = self.hacer_credito(cuotas=5)
        from .servicios.pagos import validar_pago

        revision = validar_pago(credito, Decimal("9999999999"))
        self.assertTrue(revision["requiere_confirmacion"])
        self.assertIn("anticipado", revision["mensaje"].lower())

        revision2 = validar_pago(
            credito, Decimal("9999999999"), es_anticipo_confirmado=True,
        )
        self.assertFalse(revision2["requiere_confirmacion"])

    def test_pago_sin_confirmar_se_rechaza(self):
        credito = self.hacer_credito(cuotas=5)
        with self.assertRaises(ErrorPago):
            self.pagar(credito, Decimal("9999999999"))

    def test_un_mismo_token_no_duplica_el_pago(self):
        """ESTO ES LO MAS IMPORTANTE: recargar no cobra dos veces."""
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        token = "token-unico-de-prueba-123"

        pago1, datos1 = self.pagar(credito, Decimal("50000"), cuota=cuota, token=token)
        pago2, datos2 = self.pagar(credito, Decimal("50000"), cuota=cuota, token=token)

        self.assertEqual(pago1.pk, pago2.pk)
        self.assertFalse(datos1["duplicado"])
        self.assertTrue(datos2["duplicado"])

        # Y el saldo solo se movio una vez.
        self.assertEqual(Pago.objects.filter(credito=credito).count(), 1)
        cuota.refresh_from_db()
        self.assertEqual(cuota.valor_pagado, Decimal("50000"))

    def test_sin_token_se_genera_uno(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        pago, _ = self.pagar(credito, Decimal("10000"), cuota=cuota, token=None)
        self.assertTrue(pago.token)
        self.assertEqual(len(pago.token), 32)

    def test_cada_pago_tiene_numero_de_comprobante_unico(self):
        credito = self.hacer_credito(cuotas=10)
        recibos = set()
        for i in range(5):
            cuota = credito.cuotas.get(numero=i + 1)
            pago, _ = self.pagar(credito, cuota.valor, cuota=cuota)
            recibos.add(pago.recibo)
        self.assertEqual(len(recibos), 5)

    def test_pago_de_credito_pagado_se_rechaza(self):
        credito = self.hacer_credito(cuotas=2)
        for cuota in list(credito.cuotas.all()):
            self.pagar(credito, cuota.valor, cuota=cuota)

        credito.refresh_from_db()
        self.assertEqual(credito.estado, EstadoCredito.PAGADO)
        with self.assertRaises(ErrorPago):
            self.pagar(credito, Decimal("1000"))

    def test_no_se_puede_pagar_valor_cero(self):
        credito = self.hacer_credito(cuotas=5)
        with self.assertRaises(ErrorPago):
            self.pagar(credito, Decimal("0"))


# ===========================================================================
# SALDOS DEL CREDITO
# ===========================================================================


class PruebaSaldos(BasePrueba):

    def test_saldo_baja_con_cada_pago(self):
        credito = self.hacer_credito(cuotas=5, saldo=Decimal("2000000"))
        self.assertEqual(credito.saldo, Decimal("2000000"))

        cuota = credito.cuotas.first()
        self.pagar(credito, Decimal("400000"), cuota=cuota)

        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, Decimal("400000"))
        self.assertEqual(credito.saldo, Decimal("1600000"))

    def test_credito_queda_pagado_al_completar(self):
        credito = self.hacer_credito(cuotas=4, saldo=Decimal("2000000"))
        for cuota in list(credito.cuotas.all()):
            self.pagar(credito, cuota.valor, cuota=cuota)

        credito.refresh_from_db()
        self.assertEqual(credito.estado, EstadoCredito.PAGADO)
        self.assertEqual(credito.saldo, CERO)
        self.assertEqual(credito.total_pagado, credito.valor_financiado)
        self.assertIsNotNone(credito.fecha_finalizacion)
        self.assertEqual(credito.cuotas_pagadas, 4)

    def test_las_cuotas_nunca_pagan_mas_de_lo_que_valen(self):
        """Aunque se pague de mas, la cuota no se pasa."""
        credito = self.hacer_credito(cuotas=4, saldo=Decimal("2000000"))
        cuota = credito.cuotas.first()

        self.pagar(credito, Decimal("999999"), cuota=cuota)

        cuota.refresh_from_db()
        self.assertEqual(cuota.valor_pagado, cuota.valor)
        self.assertEqual(cuota.saldo, CERO)

    def test_recalcular_arregla_cualquier_descuadre(self):
        """La funcion de referencia: siempre deja todo cuadrado."""
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        self.pagar(credito, Decimal("100000"), cuota=cuota)

        # Se rompen los saldos a proposito.
        credito.total_pagado = Decimal("999")
        credito.saldo = Decimal("1")
        credito.save()

        recalcular_credito(credito)

        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, Decimal("100000"))
        self.assertEqual(credito.saldo, credito.valor_financiado - Decimal("100000"))


# ===========================================================================
# ANULACION DE PAGOS  (no se borra nada)
# ===========================================================================


class PruebaAnulacion(BasePrueba):

    def test_anular_no_borra_el_pago(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        pago, _ = self.pagar(credito, Decimal("100000"), cuota=cuota)

        anular_pago(pago, self.usuario, "Se digito mal el valor")

        pago.refresh_from_db()
        self.assertTrue(pago.anulado)
        self.assertEqual(pago.motivo_anulacion, "Se digito mal el valor")
        self.assertIsNotNone(pago.anulado_por)
        # El registro sigue existiendo: no se borro.
        self.assertEqual(Pago.objects.filter(pk=pago.pk).count(), 1)

    def test_anular_devuelve_el_saldo(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        pago, _ = self.pagar(credito, Decimal("100000"), cuota=cuota)

        anular_pago(pago, self.usuario, "Error de digitacion")

        credito.refresh_from_db()
        cuota.refresh_from_db()
        self.assertEqual(credito.total_pagado, CERO)
        self.assertEqual(credito.saldo, credito.valor_financiado)
        self.assertEqual(cuota.valor_pagado, CERO)
        self.assertEqual(cuota.estado_real(), EstadoCuota.PENDIENTE)

    def test_anular_dos_veces_falla(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        pago, _ = self.pagar(credito, Decimal("100000"), cuota=cuota)
        anular_pago(pago, self.usuario, "Primer motivo")
        with self.assertRaises(ErrorPago):
            anular_pago(pago, self.usuario, "Segundo intento")

    def test_anular_exige_motivo(self):
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        pago, _ = self.pagar(credito, Decimal("100000"), cuota=cuota)
        with self.assertRaises(ErrorPago):
            anular_pago(pago, self.usuario, "x")


# ===========================================================================
# BARRA DE REGULARIDAD
# ===========================================================================


class PruebaRegularidad(BasePrueba):

    def _credito_vencido(self, cuotas=30, saldo=Decimal("3000000"), dias=0):
        """Credito cuyo plan ya vencio hace `dias` dias."""
        return self.hacer_credito(
            cuotas=cuotas, saldo=saldo,
            primera=hoy() - timedelta(days=7 * (cuotas - 1) + dias),
        )

    def test_ejemplo_del_enunciado_da_80_por_ciento(self):
        """12 a tiempo + 2 con retraso + 1 vencida = 80%.

        Es exactamente el ejemplo del sistema:
            12 cuotas pagadas a tiempo
             2 cuotas pagadas con retraso
             1 cuota vencida
            ->  ████████████████░░░░ 80%
        """
        # 30 cuotas semanales, todas ya vencidas.
        credito = self._credito_vencido(cuotas=30, dias=7)

        for numero in range(1, 13):          # 12 a tiempo
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento)

        for numero in (13, 14):              # 2 con retraso de 3 dias
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento + timedelta(days=3))

        # La cuota 15 NO se paga: queda vencida.
        regularidad = calcular_regularidad(credito=credito)

        self.assertEqual(regularidad["a_tiempo"], 12)
        self.assertEqual(regularidad["con_retraso"], 2)
        self.assertGreaterEqual(regularidad["vencidas"], 1)
        evaluadas = (regularidad["a_tiempo"] + regularidad["con_retraso"]
                     + regularidad["vencidas"])
        self.assertEqual(regularidad["porcentaje"], round(12 / evaluadas * 100))
        # Con 15 cuotas viejas sin pagar, el atraso es tan grande que el
        # cliente escala a MOROSO. Eso es correcto: no se premia a quien
        # deja acumular mora.
        self.assertEqual(regularidad["categoria"], "MOROSO")

    def test_12_2_1_da_exactamente_80_por_ciento(self):
        """Version cerrada del ejemplo: 12 + 2 + 1 = 15, 12/15 = 80%."""
        credito = self.hacer_credito(cuotas=15, saldo=Decimal("1500000"),
                                     primera=hoy() - timedelta(days=15 * 7))
        for numero in range(1, 13):
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento)
        for numero in (13, 14):
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento + timedelta(days=2))

        regularidad = calcular_regularidad(credito=credito)
        self.assertEqual(regularidad["a_tiempo"], 12)
        self.assertEqual(regularidad["con_retraso"], 2)
        self.assertEqual(regularidad["vencidas"], 1)
        self.assertEqual(regularidad["porcentaje"], 80)
        self.assertEqual(regularidad["barra"], "████████████████░░░░")

    def test_la_barra_se_dibuja_en_texto(self):
        regularidad = calcular_regularidad(cliente=self.hacer_cliente())
        self.assertEqual(len(regularidad["barra"]), 20)

    def test_todo_a_tiempo_da_excelente(self):
        credito = self._credito_vencido(cuotas=20, saldo=Decimal("2000000"))
        for cuota in credito.cuotas.all():
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento)

        regularidad = calcular_regularidad(credito=credito)
        self.assertEqual(regularidad["porcentaje"], 100)
        self.assertEqual(regularidad["categoria"], "EXCELENTE")
        self.assertEqual(regularidad["vencidas"], 0)

    def test_mucha_mora_da_moroso(self):
        # Todas vencidas hace mas de 15 dias y sin pagar.
        credito = self._credito_vencido(cuotas=20, saldo=Decimal("2000000"),
                                         dias=60)
        regularidad = calcular_regularidad(credito=credito)
        self.assertEqual(regularidad["categoria"], "MOROSO")
        self.assertGreater(regularidad["atraso_vigente"], 15)

    def test_una_fraccion_se_agrupa_solo(self):
        """Pagar una cuota de muchas cuenta como puntual, no como atraso."""
        credito = self._credito_vencido(cuotas=20, saldo=Decimal("2000000"))
        for cuota in credito.cuotas.all():
            self.pagar(credito, cuota.saldo, cuota=cuota,
                       fecha=cuota.fecha_vencimiento)

        regularidad = calcular_regularidad(credito=credito)
        self.assertEqual(regularidad["a_tiempo"], 20)
        self.assertEqual(regularidad["categoria"], "EXCELENTE")

    def test_credito_nuevo_sin_historial_da_sin_datos(self):
        """Un credito cuyas cuotas aun no vencen no se puede juzgar."""
        credito = self.hacer_credito(cuotas=5)   # arranca hoy
        regularidad = calcular_regularidad(credito=credito)
        self.assertEqual(regularidad["categoria"], "SIN_DATOS")
        self.assertEqual(regularidad["a_tiempo"], 0)
        self.assertEqual(regularidad["vencidas"], 0)

    def test_los_umbrales_son_configurables(self):
        """Cambiar la configuracion cambia el resultado."""
        cfg = config()
        credito = self.hacer_credito(
            cuotas=30, saldo=Decimal("3000000"),
            primera=hoy() - timedelta(days=7 * 30),
        )
        # 21 puntuales + 9 tardias (pero todas pagadas) = 70%, sin mora.
        for numero in range(1, 22):
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento)
        for numero in range(22, 31):
            cuota = credito.cuotas.get(numero=numero)
            self.pagar(credito, cuota.valor, cuota=cuota,
                       fecha=cuota.fecha_vencimiento + timedelta(days=4))

        cfg.umbral_excelente = 90
        cfg.umbral_bueno = 70
        cfg.save()

        regularidad = calcular_regularidad(credito=credito, config=cfg)
        self.assertEqual(regularidad["a_tiempo"], 21)
        self.assertEqual(regularidad["con_retraso"], 9)
        self.assertEqual(regularidad["vencidas"], 0)
        self.assertEqual(regularidad["porcentaje"], 70)
        self.assertEqual(regularidad["categoria"], "BUENO")

        # Si el admin sube el liston, el mismo cliente deja de ser BUENO.
        cfg.umbral_bueno = 80
        cfg.save()
        regularidad2 = calcular_regularidad(credito=credito, config=cfg)
        self.assertEqual(regularidad2["categoria"], "IRREGULAR")

        # Y si lo baja mas, sube a EXCELENTE sin que cambien los datos.
        cfg.umbral_bueno = 60
        cfg.umbral_excelente = 65
        cfg.save()
        regularidad3 = calcular_regularidad(credito=credito, config=cfg)
        self.assertEqual(regularidad3["categoria"], "EXCELENTE")

    def test_dias_de_gracia_cambian_el_cuento(self):
        cfg = config()
        cfg.dias_gracia = 0
        cfg.save()

        credito = self.hacer_credito(cuotas=10, saldo=Decimal("1000000"),
                                     primera=hoy() - timedelta(days=7 * 9))
        cuota = credito.cuotas.get(numero=1)
        # Paga 2 dias despues: con gracia 0 es tarde.
        self.pagar(credito, cuota.valor, cuota=cuota,
                   fecha=cuota.fecha_vencimiento + timedelta(days=2))

        self.assertEqual(calcular_regularidad(credito=credito)["con_retraso"], 1)

        # Con 3 dias de gracia, ya no cuenta como tarde.
        cfg.dias_gracia = 3
        cfg.save()
        self.assertEqual(calcular_regularidad(credito=credito)["con_retraso"], 0)


def modelos_inicio(inicio, credito, total):
    """Reescribe las fechas de vencimiento de un plan completo."""
    from .servicios.calendario import sumar_frecuencia
    fechas = [
        sumar_frecuencia(inicio, credito.frecuencia, i) for i in range(total)
    ]
    for i, fecha in enumerate(fechas, start=1):
        Cuota.objects.filter(credito=credito, numero=i).update(
            fecha_vencimiento=fecha,
        )
    return fechas


# ===========================================================================
# FORMATO DE DINERO
# ===========================================================================


class PruebaDinero(TestCase):

    def test_pesos_colombianos_sin_decimales(self):
        self.assertEqual(formato_dinero(1000000), "$1.000.000")
        self.assertEqual(formato_dinero(2500), "$2.500")
        self.assertEqual(formato_dinero(0), "$0")
        self.assertEqual(formato_dinero(None), "$0")

    def test_valores_grandes(self):
        self.assertEqual(formato_dinero(123456789), "$123.456.789")

    def test_numero_en_letras(self):
        self.assertEqual(numero_escrito(1000), "mil pesos")
        self.assertEqual(numero_escrito(500), "quinientos pesos")
        self.assertEqual(numero_escrito(1000000), "un millon pesos")


# ===========================================================================
# NO SE PIERDE INFORMACION
# ===========================================================================


class PruebaNoSePierde(BasePrueba):

    def test_un_cliente_no_se_borra_al_desactivarlo(self):
        cliente = self.hacer_cliente()
        credito = self.hacer_credito(cliente=cliente, cuotas=5)
        cuota = credito.cuotas.first()
        self.pagar(credito, Decimal("100000"), cuota=cuota)

        cliente.activo = False
        cliente.save()

        cliente.refresh_from_db()
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())
        self.assertEqual(cliente.creditos.count(), 1)
        self.assertEqual(Pago.objects.filter(credito__cliente=cliente).count(), 1)

    def test_credito_con_pagos_no_se_borra(self):
        from .servicios.cuotas import eliminar_credito_si_sin_pagos
        credito = self.hacer_credito(cuotas=5)
        cuota = credito.cuotas.first()
        self.pagar(credito, Decimal("1000"), cuota=cuota)

        self.assertFalse(eliminar_credito_si_sin_pagos(credito))
        self.assertTrue(Credito.objects.filter(pk=credito.pk).exists())

    def test_credito_sin_pagos_si_se_puede_borrar(self):
        from .servicios.cuotas import eliminar_credito_si_sin_pagos
        credito = self.hacer_credito(cuotas=5)
        self.assertTrue(eliminar_credito_si_sin_pagos(credito))
        self.assertFalse(Credito.objects.filter(pk=credito.pk).exists())

    def test_credito_terminado_conserva_el_historial(self):
        credito = self.hacer_credito(cuotas=2, saldo=Decimal("1000000"))
        for cuota in list(credito.cuotas.all()):
            self.pagar(credito, cuota.valor, cuota=cuota)

        credito.refresh_from_db()
        self.assertEqual(credito.estado, EstadoCredito.PAGADO)
        self.assertEqual(Pago.objects.filter(credito=credito).count(), 2)
        self.assertEqual(credito.cliente.creditos.count(), 1)

    def test_cedula_oculta_muestra_solo_ultimos_digitos(self):
        cliente = self.hacer_cliente(cedula="123456789")
        self.assertEqual(cliente.cedula_oculta, "*****789")

    def test_cedula_no_se_puede_repetir(self):
        self.hacer_cliente(cedula="123456789")
        with self.assertRaises(Exception):
            self.hacer_cliente(cedula="123456789")


# ===========================================================================
# CONSULTAS DEL PANEL
# ===========================================================================


class PruebaPanel(BasePrueba):

    def test_el_panel_responde_a_solo(self):
        """Si el panel truena cuando no hay datos, el sistema no sirve."""
        self.hacer_credito(cuotas=5)
        resumen = servicio_cartera.resumen_general()
        self.assertEqual(resumen["total_clientes"], 1)
        self.assertEqual(resumen["creditos_activos"], 1)
        self.assertIn("clientes_al_dia", resumen)
        self.assertIn("cartera_vencida", resumen)

    def test_el_calendario_arma_el_mes(self):
        credito = self.hacer_credito(cuotas=5)
        hoy_ = hoy()
        datos = servicio_cartera.calendario_del_mes(hoy_.year, hoy_.month)
        total_cuotas = sum(len(d["cuotas"]) for d in datos["dias"].values())

        # Solo cuentan las cuotas que vencen dentro del mes pedido.
        dentro_del_mes = credito.cuotas.filter(
            fecha_vencimiento__year=hoy_.year,
            fecha_vencimiento__month=hoy_.month,
        ).count()
        self.assertEqual(total_cuotas, dentro_del_mes)
        self.assertGreater(total_cuotas, 0)

    def test_los_cobros_pendientes_ordenan_por_atraso(self):
        cliente_1 = self.hacer_cliente(cedula="111111111")
        cliente_2 = self.hacer_cliente(cedula="222222222")

        # Cliente 1 con 30 dias de atraso, cliente 2 pagando hoy.
        atrasado = self.hacer_credito(
            cliente=cliente_1, cuotas=3,
            primera=hoy() - timedelta(days=7 * 2),
        )
        al_dia = self.hacer_credito(
            cliente=cliente_2, cuotas=3,
            primera=hoy(),
        )

        filas, resumen = servicio_cartera.cobros_pendientes(hoy())
        self.assertGreaterEqual(len(filas), 2)
        # El mas atrasado va primero.
        self.assertEqual(filas[0]["cliente"].id, cliente_1.id)
        self.assertGreater(filas[0]["atraso"], 0)
        self.assertEqual(filas[0]["cliente"].id, cliente_1.id)
        self.assertTrue(len(resumen["vencidas"]) >= 1)

    def test_busqueda_por_cedula_sin_puntos(self):
        self.hacer_cliente(cedula="123456789", nombres="Juan", apellidos="Perez")
        self.hacer_cliente(cedula="987654321", nombres="Maria", apellidos="Lopez")

        self.assertEqual(servicio_cartera.buscar_clientes("123456").count(), 1)
        self.assertEqual(servicio_cartera.buscar_clientes("123456789").count(), 1)
        self.assertEqual(servicio_cartera.buscar_clientes("Juan").count(), 1)
        self.assertEqual(servicio_cartera.buscar_clientes("Perez").count(), 1)
        self.assertEqual(servicio_cartera.buscar_clientes("x").count(), 0)

    def test_busqueda_ignora_puntos_guiones_espacios(self):
        self.hacer_cliente(cedula="123456789")
        for texto in ("1.234.567", "1-234-567", "1 234 567"):
            self.assertEqual(
                servicio_cartera.buscar_clientes(texto).count(), 1,
                f"Busco '{texto}' y no encontro el cliente",
            )

    def test_resumen_cliente_suma_todos_sus_creditos(self):
        cliente = self.hacer_cliente()
        self.hacer_credito(cliente=cliente, cuotas=5, saldo=Decimal("1000000"))
        self.hacer_credito(cliente=cliente, cuotas=5, saldo=Decimal("2000000"))

        resumen = servicio_cartera.resumen_cliente(cliente.id)
        self.assertEqual(resumen["financiado"], Decimal("3000000"))
        self.assertEqual(resumen["saldo"], Decimal("3000000"))
        self.assertEqual(resumen["creditos_activos"], 2)


# ===========================================================================
# CATALOGOS
# ===========================================================================


class PruebaCatalogos(BasePrueba):

    def test_crear_catalogos_no_duplica(self):
        from .servicios.catalogo import crear_catalogos_iniciales
        crear_catalogos_iniciales()
        crear_catalogos_iniciales()
        self.assertEqual(FrecuenciaPago.objects.filter(nombre="DIARIO").count(), 1)
        self.assertEqual(MetodoPago.objects.filter(nombre="Efectivo").count(), 1)

    def test_las_frecuencias_base_existen(self):
        from .servicios.catalogo import crear_catalogos_iniciales
        crear_catalogos_iniciales()
        for nombre in ("DIARIO", "SEMANAL", "QUINCENAL", "MENSUAL"):
            self.assertTrue(
                FrecuenciaPago.objects.filter(nombre=nombre).exists(),
                f"Falta la frecuencia {nombre}",
            )
