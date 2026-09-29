"""
PRUEBAS DE HUMO DE TODAS LAS PANTALLAS.

Las pruebas de `tests.py` revisan la logica (que las cuentas cuadren).
Estas revisan que CADA PANTALLA se abra de verdad: que la plantilla exista,
que no falte un filtro, que no haya un error de programacion escondido.

Un error aqui significa que el usuario veria una pantalla roja. Por eso
se recorren todas, incluso las que estan vacias.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Cliente, Credito, Cuota, EstadoCredito, FrecuenciaPago, MetodoPago, Pago,
    PerfilUsuario, Producto, Rol,
)
from .servicios.calendario import sumar_frecuencia
from .servicios.cuotas import crear_plan_credito
from .servicios.pagos import registrar_pago
from .servicios.regularidad import configuracion as config


def hoy():
    return timezone.localdate()


class BaseHumo(TestCase):
    """Arma un negocio pequeno pero completo y revisa que todo se abra."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="Ana", password="prueba123", first_name="Ana",
        )
        PerfilUsuario.objects.create(usuario=cls.admin, rol=Rol.ADMINISTRADOR)

        cls.cobrador = User.objects.create_user(
            username="Luis", password="prueba123", first_name="Luis",
        )
        PerfilUsuario.objects.create(usuario=cls.cobrador, rol=Rol.COBRADOR)

        cls.metodo = MetodoPago.objects.create(nombre="Efectivo", orden=10)
        cls.semanal = FrecuenciaPago.objects.create(
            nombre="SEMANAL", dias=7, unidad=FrecuenciaPago.Unidad.DIAS, orden=20,
        )
        config()

        # --- Un cliente al dia -----------------------------------------
        cls.cliente_ok = Cliente.objects.create(
            nombres="Juan", apellidos="Perez", cedula="123456789",
            telefono="3000000000", telefono_alternativo="3010000000",
            direccion="Calle 10 # 20-30", ciudad="Bogota", barrio="La Esperanza",
            referencia_nombre="Maria Perez", referencia_telefono="3101111111",
        )
        cls.credito_ok = cls._crear_credito(cls.cliente_ok, pagadas=5, vencidas=0)

        # --- Un cliente atrasado ---------------------------------------
        cls.cliente_mora = Cliente.objects.create(
            nombres="Pedro", apellidos="Lopez", cedula="987654321",
            telefono="3009999999", direccion="Calle 5", ciudad="Medellin",
        )
        cls.credito_mora = cls._crear_credito(
            cls.cliente_mora, pagadas=2, vencidas=3, atraso_dias=40,
        )

        # --- Un credito terminado --------------------------------------
        cls.cliente_pagado = Cliente.objects.create(
            nombres="Maria", apellidos="Lopez", cedula="555555555",
            telefono="3005555555", direccion="Calle 9", ciudad="Cali",
        )
        cls.credito_pagado = cls._crear_credito(cls.cliente_pagado, pagadas=4, vencidas=0)
        cls.credito_pagado.estado = EstadoCredito.PAGADO
        cls.credito_pagado.saldo = Decimal("0")
        cls.credito_pagado.fecha_finalizacion = hoy() - timedelta(days=5)
        cls.credito_pagado.save()

        Producto.objects.create(nombre="Xiaomi Scooter", marca="Xiaomi",
                                 modelo="Mi Electric", precio_contado=Decimal("1000000"))

    @classmethod
    def _crear_credito(cls, cliente, pagadas, vencidas, atraso_dias=0):
        total_cuotas = 10
        saldo = Decimal("2000000")
        # Las 'vencidas' cuotas se ponen en el pasado.
        primera = hoy() - timedelta(
            days=7 * (pagadas + vencidas + atraso_dias // 7) + atraso_dias
        )
        credito = Credito.objects.create(
            cliente=cliente,
            producto_texto="Xiaomi Scooter",
            fecha_venta=primera,
            precio_contado=Decimal("1000000"),
            precio_financiado=Decimal("2200000"),
            cuota_inicial=Decimal("200000"),
            valor_financiado=saldo,
            numero_cuotas=total_cuotas,
            frecuencia=cls.semanal,
            fecha_primera_cuota=primera,
            valor_cuota=Decimal("200000"),
            fecha_estimada_fin=primera,
            creado_por=cls.admin,
        )
        crear_plan_credito(credito)
        credito.refresh_from_db()

        # Las vencidas se atrasan a proposito.
        for numero in range(1, vencidas + 1):
            Cuota.objects.filter(credito=credito, numero=numero).update(
                fecha_vencimiento=hoy() - timedelta(days=max(1, atraso_dias)),
            )

        # Pagar las 'pagadas' a tiempo.
        for numero in range(1, pagadas + 1):
            cuota = Cuota.objects.filter(credito=credito, numero=numero).first()
            if not cuota:
                continue
            registrar_pago(
                credito=credito, valor=cuota.valor, metodo=cls.metodo,
                usuario=cls.admin, cuota=cuota, fecha=cuota.fecha_vencimiento,
            )

        credito.refresh_from_db()
        return credito


# ===========================================================================
# PANTALLAS DEL ADMINISTRADOR
# ===========================================================================


class PruebaPantallasAdmin(BaseHumo):

    def setUp(self):
        self.client.login(username="Ana", password="prueba123")

    def test_todas_las_pantallas_abren(self):
        """Recorre una por una y revisa que ninguna de rojo."""
        ahora = hoy()
        pantallas = [
            (reverse("dashboard"), "Panel"),
            (reverse("clientes"), "Clientes"),
            (reverse("nuevo_cliente"), "Nuevo cliente"),
            (reverse("ficha_cliente", args=[self.cliente_ok.id]), "Juan"),
            (reverse("editar_cliente", args=[self.cliente_ok.id]), "Editar"),
            (reverse("documentos_cliente", args=[self.cliente_ok.id]), "Cedula"),
            (reverse("creditos"), "Creditos"),
            (reverse("nuevo_credito"), "Nuevo credito"),
            (reverse("productos"), "Catalogo"),
            (reverse("ficha_credito", args=[self.credito_ok.id]), "Xiaomi"),
            (reverse("editar_credito", args=[self.credito_ok.id]), "Editar credito"),
            (reverse("cobrar"), "Registrar pago"),
            (reverse("cobrar_cliente", args=[self.cliente_mora.id]), "Cobrar a"),
            (reverse("registrar_pago", args=[self.credito_ok.id]), "Cobrar a"),
            (reverse("historial_pagos"), "Historial"),
            (reverse("cobros_pendientes"), "Cobros pendientes"),
            (reverse("calendario"), "Calendario"),
            (reverse("dia_calendario", args=[ahora.year, ahora.month, ahora.day]), "dia"),
            (reverse("reportes"), "Reportes"),
            (reverse("ajustes"), "Configuracion"),
            (reverse("usuarios"), "Usuarios"),
            (reverse("respaldos"), "Respaldos"),
            (reverse("historial"), "Auditoria"),
            (reverse("cambiar_clave"), "Mi contrasena"),
        ]

        for url, texto_esperado in pantallas:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(
                    respuesta.status_code, 200,
                    f"La pagina {url} no abrio (codigo {respuesta.status_code})",
                )
                contenido = respuesta.content.decode("utf-8", errors="ignore")
                self.assertIn(
                    texto_esperado, contenido,
                    f"La pagina {url} no mencionaba '{texto_esperado}'",
                )
                # Si aparece la pagina de error, la plantilla esta mala.
                self.assertNotIn("DoesNotExist", contenido)
                self.assertNotIn("VariableDoesNotExist", contenido)
                self.assertNotIn("Invalid block tag", contenido)

    def test_comprobantes_abren(self):
        for credito in (self.credito_ok, self.credito_mora, self.credito_pagado):
            pago = Pago.objects.filter(credito=credito, anulado=False).first()
            if not pago:
                continue
            with self.subTest(pago=pago.recibo):
                respuesta = self.client.get(
                    reverse("comprobante", args=[pago.id]))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, pago.recibo)

    def test_las_plantillas_de_anular_y_corregir_abren(self):
        pago = Pago.objects.filter(credito=self.credito_ok, anulado=False).first()
        for nombre in ("anular_pago", "corregir_pago"):
            with self.subTest(nombre=nombre):
                respuesta = self.client.get(reverse(nombre, args=[pago.id]))
                self.assertEqual(respuesta.status_code, 200)

    def test_consultas_json_de_la_busqueda(self):
        respuesta = self.client.get(reverse("api_buscar"), {"q": "Juan"})
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(len(datos["resultados"]), 1)
        self.assertEqual(datos["resultados"][0]["nombre"], "Juan Perez")

        respuesta = self.client.get(reverse("api_buscar"), {"q": "123456"})
        self.assertEqual(len(respuesta.json()["resultados"]), 1)

        respuesta = self.client.get(reverse("api_credito"), {"credito": self.credito_ok.id})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["cuotas"], 10)

    def test_el_plan_de_pagos_se_calcula_por_json(self):
        respuesta = self.client.get(reverse("calcular_plan"), {
            "precio_financiado": "2000000",
            "cuota_inicial": "200000",
            "numero_cuotas": "36",
            "frecuencia": self.semanal.id,
            "fecha_primera_cuota": hoy().isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertTrue(datos["ok"])
        self.assertEqual(datos["cantidad"], 36)
        self.assertEqual(datos["saldo"], "1800000")

    def test_exportar_excel(self):
        respuesta = self.client.get(reverse("exportar_excel"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(
            "spreadsheetml", respuesta["Content-Type"],
        )
        self.assertTrue(len(respuesta.content) > 5000)

    def test_exportar_csv(self):
        respuesta = self.client.get(reverse("exportar_csv"), {"tipo": "pagos"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("text/csv", respuesta["Content-Type"])


# ===========================================================================
# SEGURIDAD: LO QUE NO SE DEBE PODER HACER
# ===========================================================================


class PruebaSeguridad(BaseHumo):

    def test_sin_entrar_no_se_ve_nada(self):
        """Cada pantalla protegida manda a la de entrada."""
        protecciones = [
            reverse("dashboard"),
            reverse("clientes"),
            reverse("creditos"),
            reverse("cobrar"),
            reverse("cobros_pendientes"),
            reverse("calendario"),
            reverse("reportes"),
            reverse("ficha_cliente", args=[self.cliente_ok.id]),
            reverse("ficha_credito", args=[self.credito_ok.id]),
            reverse("usuarios"),
            reverse("respaldos"),
            reverse("api_buscar") + "?q=Juan",
        ]
        for url in protecciones:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertIn(
                    respuesta.status_code, (302, 401),
                    f"{url} dejo pasar a alguien sin entrar",
                )

    def test_las_fotos_de_cedula_no_son_publicas(self):
        """Sin entrar, la foto NO se entrega."""
        from .models import DocumentoCliente
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        import io

        # Se crea una imagen valida de prueba.
        bufer = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(bufer, format="JPEG")
        bufer.seek(0)

        documento = DocumentoCliente.objects.create(
            cliente=self.cliente_ok,
            tipo=DocumentoCliente.Tipo.FRONTAL,
            archivo=SimpleUploadedFile(
                "cedula.jpg", bufer.read(), content_type="image/jpeg"),
        )

        url = reverse("ver_documento", args=[documento.id])

        # 1) Sin sesion: no se entrega.
        respuesta = self.client.get(url)
        self.assertIn(respuesta.status_code, (302, 401, 404))

        # 2) Con sesion: si se entrega, con cabeceras de proteccion.
        self.client.login(username="Ana", password="prueba123")
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", respuesta["Cache-Control"])
        respuesta.close()

    def test_una_url_inexistente_no_filtra_informacion(self):
        respuesta = self.client.get("/documentos/loquersea.jpg")
        self.assertNotEqual(respuesta.status_code, 200)

    def test_el_cobrador_no_entra_a_configuracion(self):
        """El cobrador no puede cambiar el sistema ni crear usuarios."""
        self.client.login(username="Luis", password="prueba123")
        for url in (
            reverse("ajustes"),
            reverse("usuarios"),
            reverse("respaldos"),
            reverse("historial"),
        ):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(
                    respuesta.status_code, 302,
                    f"El cobrador alcanzo {url}",
                )

    def test_el_cobrador_no_puede_anular_pagos(self):
        pago = Pago.objects.filter(credito=self.credito_ok, anulado=False).first()
        self.client.login(username="Luis", password="prueba123")
        respuesta = self.client.get(reverse("anular_pago", args=[pago.id]))
        self.assertEqual(respuesta.status_code, 302)

        respuesta = self.client.post(
            reverse("anular_pago", args=[pago.id]),
            {"motivo": "Intento sin permisos"},
        )
        pago.refresh_from_db()
        self.assertFalse(pago.anulado, "Un cobrador pudo anular un pago")

    def test_el_cobrador_si_puede_cobrar(self):
        self.client.login(username="Luis", password="prueba123")
        respuesta = self.client.get(
            reverse("registrar_pago", args=[self.credito_ok.id]))
        self.assertEqual(respuesta.status_code, 200)

    def test_no_se_puede_crear_cliente_despues_de_salir(self):
        self.client.login(username="Ana", password="prueba123")
        self.client.post(reverse("salir"))
        respuesta = self.client.get(reverse("nuevo_cliente"))
        self.assertIn(respuesta.status_code, (302, 401))

    def test_sin_token_csrf_no_se_paga(self):
        """Un pago enviado sin el token de seguridad se rechaza."""
        pagos_antes = Pago.objects.count()
        total_antes = sum(
            (c.total_pagado for c in Credito.objects.all()), Decimal("0"))

        cliente = self.client_class(enforce_csrf_checks=True)
        cliente.login(username="Ana", password="prueba123")
        respuesta = cliente.post(
            reverse("registrar_pago", args=[self.credito_ok.id]),
            {
                "credito": self.credito_ok.id,
                "cuota": "",
                "valor": "10000",
                "metodo": self.metodo.id,
                "fecha": hoy().isoformat(),
                "token": "intento-sin-token-csrf",
            },
        )
        # Falla por CSRF (403) o por validacion (200 con errores).
        self.assertIn(respuesta.status_code, (200, 403))

        # Lo importante: no se creo ningun pago ni se movio ningun saldo.
        self.assertEqual(
            Pago.objects.count(), pagos_antes,
            "Un pago se registro sin el token de seguridad",
        )
        total_despues = sum(
            (c.total_pagado for c in Credito.objects.all()), Decimal("0"))
        self.assertEqual(total_despues, total_antes)


# ===========================================================================
# FLUJOS COMPLETOS DE TRABAJO
# ===========================================================================


class PruebaFlujos(BaseHumo):
    """Recorre el camino completo que hace un cobrador en un dia."""

    def setUp(self):
        self.client.login(username="Ana", password="prueba123")

    def test_crear_cliente_credito_y_cobrar_desde_cero(self):
        # 1) Crear el cliente.
        respuesta = self.client.post(reverse("nuevo_cliente"), {
            "nombres": "Carlos", "apellidos": "Nuevo", "cedula": "777777777",
            "telefono": "3007777777", "direccion": "Calle 99", "ciudad": "Bogota",
            "referencia_nombre": "Ana Nueva", "referencia_telefono": "3107777777",
        })
        self.assertEqual(respuesta.status_code, 302)
        cliente = Cliente.objects.get(cedula="777777777")

        # 2) Crearle el credito: 1.800.000 en 36 cuotas semanales.
        respuesta = self.client.post(reverse("nuevo_credito"), {
            "cliente": cliente.id,
            "producto_texto": "Lavadora",
            "fecha_venta": hoy().isoformat(),
            "precio_contado": "1000000",
            "precio_financiado": "2000000",
            "cuota_inicial": "200000",
            "numero_cuotas": "36",
            "frecuencia": self.semanal.id,
            "fecha_primera_cuota": hoy().isoformat(),
            "valor_cuota": "",
        })
        self.assertEqual(respuesta.status_code, 302)

        credito = Credito.objects.get(cliente=cliente)
        self.assertEqual(credito.valor_financiado, Decimal("1800000"))
        self.assertEqual(credito.numero_cuotas, 36)
        self.assertEqual(credito.cuotas.count(), 36)
        self.assertEqual(credito.valor_cuota, Decimal("50000"))
        # La primera cuota vence el dia de la entrega.
        self.assertEqual(
            credito.cuotas.first().fecha_vencimiento, hoy())

        # 3) Cobrar 60.000 (abono parcial de la cuota 1).
        respuesta = self.client.post(
            reverse("registrar_pago", args=[credito.id]),
            {
                "credito": credito.id,
                "cuota": credito.cuotas.first().id,
                "valor": "60000",
                "metodo": self.metodo.id,
                "fecha": hoy().isoformat(),
                "referencia": "", "observaciones": "",
                "token": "token-de-prueba-flujo-1",
            },
        )
        self.assertEqual(respuesta.status_code, 302)

        cuota = credito.cuotas.first()
        cuota.refresh_from_db()
        # La cuota vale $50.000 (1.800.000 / 36). Con un abono de $60.000 la
        # cuota queda PAGADA y los $10.000 sobrantes pasan de anticipo a la
        # cuota 2.
        self.assertEqual(cuota.valor, Decimal("50000"))
        self.assertEqual(cuota.valor_pagado, Decimal("50000"))
        self.assertEqual(cuota.estado_real(), "PAGADA")
        self.assertEqual(credito.cuotas.get(numero=2).valor_pagado, Decimal("10000"))

        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, Decimal("60000"))
        self.assertEqual(credito.saldo, Decimal("1740000"))

        # 4) Recargar el mismo formulario con el MISMO token: no cobra doble.
        respuesta = self.client.post(
            reverse("registrar_pago", args=[credito.id]),
            {
                "credito": credito.id,
                "cuota": cuota.id,
                "valor": "60000",
                "metodo": self.metodo.id,
                "fecha": hoy().isoformat(),
                "token": "token-de-prueba-flujo-1",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            Pago.objects.filter(credito=credito).count(), 1,
            "El pago se duplico al recargar",
        )
        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, Decimal("60000"))

        # 5) Pagar el resto de la cuota 2 ($50.000 - $10.000 = $40.000).
        segunda = credito.cuotas.get(numero=2)
        respuesta = self.client.post(
            reverse("registrar_pago", args=[credito.id]),
            {
                "credito": credito.id,
                "cuota": segunda.id,
                "valor": "40000",
                "metodo": self.metodo.id,
                "fecha": hoy().isoformat(),
                "token": "token-de-prueba-flujo-2",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        segunda.refresh_from_db()
        self.assertEqual(segunda.valor_pagado, Decimal("50000"))
        self.assertEqual(segunda.estado_real(), "PAGADA")

        # 6) El panel ya refleja los 100.000 cobrados.
        credito.refresh_from_db()
        self.assertEqual(credito.total_pagado, Decimal("100000"))
        self.assertEqual(credito.saldo, Decimal("1700000"))
        self.assertEqual(credito.cuotas_pagadas, 2)

        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "$100.000", html=False)

    def test_no_se_puede_crear_cedula_repetida(self):
        respuesta = self.client.post(reverse("nuevo_cliente"), {
            "nombres": "Otro", "apellidos": "Cliente", "cedula": "123456789",
            "telefono": "3000000000", "direccion": "Calle 1", "ciudad": "Bogota",
        })
        self.assertEqual(respuesta.status_code, 200)   # vuelve al formulario
        self.assertTrue(
            Cliente.objects.filter(cedula="123456789").count() == 1,
            "Se creo un cliente repetido",
        )

    def test_credito_sin_cliente_se_rechaza(self):
        respuesta = self.client.post(reverse("nuevo_credito"), {
            "producto_texto": "Algo", "precio_financiado": "1000000",
            "cuota_inicial": "0", "numero_cuotas": "10",
            "frecuencia": self.semanal.id,
            "fecha_primera_cuota": hoy().isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Credito.objects.filter(producto_texto="Algo").count(), 0)

    def test_precios_negativos_se_rechazan(self):
        respuesta = self.client.post(reverse("nuevo_credito"), {
            "cliente": self.cliente_ok.id, "producto_texto": "Algo",
            "fecha_venta": hoy().isoformat(),
            "precio_contado": "-500", "precio_financiado": "-1000",
            "cuota_inicial": "0", "numero_cuotas": "10",
            "frecuencia": self.semanal.id,
            "fecha_primera_cuota": hoy().isoformat(),
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Credito.objects.filter(producto_texto="Algo").count(), 0)

    def test_desactivar_un_cliente_no_borra_nada(self):
        respuesta = self.client.post(
            reverse("activar_cliente", args=[self.cliente_ok.id]))
        self.assertEqual(respuesta.status_code, 302)

        cliente = Cliente.objects.get(pk=self.cliente_ok.id)
        self.assertFalse(cliente.activo)
        self.assertEqual(cliente.creditos.count(), 1)
        self.assertGreater(Pago.objects.filter(credito__cliente=cliente).count(), 0)
        # Y el historial del movimiento queda.
        from .models import HistorialMovimiento
        self.assertTrue(
            HistorialMovimiento.objects.filter(cliente=cliente).exists()
        )

    def test_un_credito_con_pagos_no_se_borra(self):
        respuesta = self.client.post(
            reverse("anular_credito", args=[self.credito_ok.id]))
        self.assertEqual(respuesta.status_code, 302)

        credito = Credito.objects.filter(pk=self.credito_ok.id).first()
        self.assertIsNotNone(credito, "Se borro un credito que tenia pagos")
        self.assertEqual(credito.estado, EstadoCredito.ANULADO)
        self.assertGreater(Pago.objects.filter(credito=credito).count(), 0)

    def test_un_credito_sin_pagos_si_se_borra(self):
        credito_vacio = self._crear_credito(
            Cliente.objects.create(
                nombres="Temporal", apellidos="Cliente", cedula="333333333",
                telefono="3003333333", direccion="Calle 3", ciudad="Bogota",
            ),
            pagadas=0, vencidas=0,
        )
        id_credito = credito_vacio.id
        respuesta = self.client.post(
            reverse("anular_credito", args=[id_credito]))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Credito.objects.filter(pk=id_credito).exists())
