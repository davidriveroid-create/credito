"""
Revisa que todos los saldos del sistema esten cuadrados.

Este comando es la red de seguridad. Si algo quedo descuadrado (un cobro a
la mitad, un error de power, una anulacion), aqui se ve y se corrige.

Uso:
    manage.py revisar_saldos              # solo informa
    manage.py revisar_saldos --corregir   # recalcula y guarda
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from cartera.models import CERO, AplicacionPago, Credito, Cuota, Pago, pesada
from cartera.servicios.cuotas import recalcular_credito
from cartera.servicios.dinero import formato_dinero


class Command(BaseCommand):
    help = "Verifica que los saldos de los creditos y cuotas esten correctos."

    def add_arguments(self, parser):
        parser.add_argument("--corregir", action="store_true",
                            help="Recalcula y guarda los saldos que esten mal.")

    def handle(self, *args, **opciones):
        problemas = []

        for credito in Credito.objects.select_related("cliente").all():
            # 1) Total pagado del credito vs la suma real de sus pagos
            real = pesada(sum(
                Pago.objects.filter(credito=credito, anulado=False)
                .values_list("valor", flat=True),
                CERO,
            ))

            if credito.total_pagado != real:
                problemas.append(
                    f"Credito #{credito.id} ({credito.cliente}): total pagado "
                    f"guardado {formato_dinero(credito.total_pagado)} pero los pagos "
                    f"suman {formato_dinero(real)}"
                )

            # 2) Saldo
            saldo_esperado = pesada(max(CERO, credito.valor_financiado - real))
            if credito.saldo != saldo_esperado:
                problemas.append(
                    f"Credito #{credito.id}: saldo guardado {formato_dinero(credito.saldo)} "
                    f"pero corresponde {formato_dinero(saldo_esperado)}"
                )

            # 3) Cuotas: el abonado debe coincidir con las aplicaciones
            for cuota in credito.cuotas.all():
                pagado_cuota = pesada(sum(
                    AplicacionPago.objects.filter(
                        cuota=cuota, pago__anulado=False,
                    ).values_list("valor", flat=True), CERO,
                ))
                if pagado_cuota != cuota.valor_pagado:
                    problemas.append(
                        f"Credito #{credito.id} cuota {cuota.numero}: pagado "
                        f"guardado {formato_dinero(cuota.valor_pagado)} pero las "
                        f"aplicaciones suman {formato_dinero(pagado_cuota)}"
                    )

        # 4) Las cuotas deben sumar exactamente el saldo financiado.
        for credito in Credito.objects.exclude(estado="ANULADO"):
            if not credito.cuotas.exists():
                problemas.append(
                    f"Credito #{credito.id}: tiene saldo "
                    f"{formato_dinero(credito.valor_financiado)} pero no tiene ninguna "
                    f"cuota generada."
                )
                continue
            suma_cuotas = pesada(sum(
                credito.cuotas.values_list("valor", flat=True), CERO,
            ))
            if abs(suma_cuotas - credito.valor_financiado) > 1:
                problemas.append(
                    f"Credito #{credito.id}: las cuotas suman {formato_dinero(suma_cuotas)} "
                    f"pero el saldo financiado es {formato_dinero(credito.valor_financiado)}. "
                    f"Diferencia de {formato_dinero(suma_cuotas - credito.valor_financiado)}."
                )

        if not problemas:
            self.stdout.write(self.style.SUCCESS(
                "Todo esta bien. No se encontro ningun descuadre."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"Se encontraron {len(problemas)} problema(s):"
        ))
        for problema in problemas:
            self.stdout.write(f"  - {problema}")

        if not opciones["corregir"]:
            self.stdout.write("")
            self.stdout.write(
                "Para corregirlo, vuelva a correr con:  "
                "manage.py revisar_saldos --corregir"
            )
            return

        with transaction.atomic():
            for credito in Credito.objects.all():
                recalcular_credito(credito, guardar=True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Se recalcularon {Credito.objects.count()} credito(s). "
            f"Los pagos no se tocaron: solo se ajustaron los saldos."
        ))
