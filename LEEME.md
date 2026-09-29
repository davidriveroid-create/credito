# Sistema de ventas a credito y cobranza

Programa para vender appliances, muebles, tecnologia y otros productos
**a credito de largo plazo**, y cobrarle al cliente diario, semanal,
quincenal o mensualmente.

Funciona en computador, tablet y celular. **Es un proyecto totalmente
independiente**: no comparte codigo, base de datos, usuarios ni
configuracion con ningun otro programa instalado en este computador.

---

## Como se enciende

Doble clic en:

```
iniciar.bat
```

Se abre solo en el navegador en **http://127.0.0.1:9000/**

| Usuario | Contrasena |
|---------|------------|
| `admin` | `admin12345` |

> **Cambie esa contrasena la primera vez que entre.**
> Menu lateral -> *Cerrar sesion* al lado, o Configuracion -> Usuarios.

Para apagarlo: doble clic en `detener.bat`

---

## Las pantallas

| Pantalla | Para que sirve |
|----------|----------------|
| **Panel** | Como va el negocio hoy: cuantos clientes, cuanto se ha cobrado, a quien hay que llamar |
| **Clientes** | Todos los clientes, con su barra de regularidad de pago |
| **Creditos** | Las ventas a credito y el plan de pagos de cada una |
| **Registrar pago** | La pantalla rapida para cobrar (lo mas usado del dia) |
| **Cobros pendientes** | La agenda del dia: a quien llamar, de mayor atraso a menor |
| **Calendario** | Vista de mes con los dias que hay que cobrar |
| **Reportes** | Cartera, vencida, cobros por metodo y por dia; exporta a Excel |
| **Configuracion** | Nombre del negocio, logo, y las reglas de la barra de regularidad |
| **Usuarios** | Administradores y cobradores |
| **Respaldos** | Copias de seguridad de la base de datos |
| **Auditoria** | Quien hizo que y cuando |

---

## El flujo del dia a dia

```
1. Buscar el cliente            ->  /cobrar/
2. Abrir el credito
3. Ver la cuota que toca
4. Escribir el valor recibido
5. Elegir el metodo de pago
6. Registrar
7. Sale el comprobante con el saldo antes y despues
8. El saldo se actualiza al instante
```

En la pantalla de cobro hay atajos: *Cuota completa*, *Saldo total* y
*Mitad*, para no tener que escribir la plata.

---

## La barra de regularidad de pago

Cada cliente tiene una barra que se calcula **sola**, con el historial real
de pagos. No la marca nadie a mano.

```
███████████████░░░░ 80%
```

| Categoria | Cuando sale |
|-----------|-------------|
| **Excelente** | 90% o mas de sus cuotas pagadas a tiempo y ninguna vencida |
| **Bueno** | 70% a 89% de puntualidad y ninguna vencida |
| **Irregular** | Varios pagos tarde, pero sin cuotas vencidas |
| **Atrasado** | Tiene cuotas vencidas, con menos de 15 dias de atraso |
| **Moroso** | Cuotas vencidas de hace mas de 15 dias |
| **Sin datos** | Todavia no hay suficientes cuotas cobradas |

La cuenta es sencilla y se puede ver:

```
porcentaje = cuotas a tiempo / (cuotas cobradas + cuotas vencidas) x 100
```

- 12 a tiempo + 2 con retraso + 1 vencida  ->  12 / 15 = **80%**
- Los pagos parciales cuentan como puntuales si seestan al dia.

**Todo esto se cambia desde** Configuracion -> *Reglas de la regularidad*:
el porcentaje de Excelente, el de Bueno, cuantos dias de atraso marcan
moroso, cuantos dias de gracia se dan, y cuantos pagos necesita para
poder clasificar a alguien.

---

## Como se calcula el plan de pagos

Al crear un credito, el sistema genera todas las cuotas de una vez.

- **La suma de las cuotas siempre es exactamente el saldo financiado.**
  Ni un peso de mas ni de menos. La ultima cuota absorbe la diferencia del
  redondeo.
- Si deja vacio *Valor de cada cuota*, el sistema lo divide solo.
- El **pago mensual usa meses de calendario**, no 30 dias: si la primera
  cuota es el 31 de enero, la siguiente cae el 28 o 29 de febrero, no en
  una fecha que no existe.

Ejemplo del sistema:

```
Producto:      Xiaomi Scooter
Precio de contado:  $1.000.000
Precio financiado:  $2.000.000
Cuota inicial:      $200.000
Saldo financiado:   $1.800.000
Forma de pago:      Semanal, 36 cuotas
Cuota:              $50.000
```

---

## Pagos parciales y anticipos

| Situacion | Que hace el sistema |
|-----------|---------------------|
| Cuota de $100.000, paga $60.000 | Queda **PARCIAL** con $40.000 de saldo |
| ...y despues paga los $40.000 | Pasa sola a **PAGADA** |
| Paga mas de lo que debe la cuota | El sobrante descuenta las cuotas siguientes |
| Paga mas que el saldo total | Pide confirmacion y lo deja como **anticipo** |

Cada abono queda en el historial. **Nunca se pisa un pago anterior.**

### Un pago jamas se duplica

Cada formulario de cobro lleva un identificador unico. Si el usuario
recarga la pagina, pulsa dos veces el boton o cierra y vuelve a abrir, el
sistema reconoce que ya se cobro y **no cobra otra vez**.

---

## Nada se borra

| Situacion | Que hace el sistema |
|-----------|---------------------|
| Un cliente ya no compra | Se **desactiva**. Sus creditos, pagos e historial siguen |
| Un pago se registro mal | Se **anula** con motivo. El registro queda en la auditoria |
| Un credito se creo mal, sin pagos | Se puede **eliminar** (no hay plata perdida) |
| Un credito tiene pagos | **Nunca** se borra: se anula y el historial queda intacto |
| Un credito ya se termino | Pasa a **PAGADO** y el cliente sigue existiendo |

---

## Seguridad

- **Las fotos de la cedula no son publicas.** No tienen una direccion de
  internet: se entregan por una pantalla que revisa que el usuario haya
  iniciado sesion, y se envian con cabeceras que impiden guardarlas en
  cache o embeberlas en otra pagina.
- Las contrasenas se guardan **cifradas** (nunca en texto plano).
- Despues de 5 intentos fallidos la cuenta se bloquea 10 minutos.
- Un cobrador **no puede** anular pagos, cambiar la configuracion, crear
  usuarios ni hacer respaldos.
- Cada pantalla sin sesion manda a la de entrada.
- Todo lo que se hace queda en la *Auditoria*: quien, cuando y desde que
  direccion IP.

---

## Respaldos

Hagalos seguido. Desde el menu *Respaldos* o desde la consola:

```
.venv\Scripts\python.exe manage.py respaldar
```

Cada respaldo es una copia comprimida en la carpeta `respaldos/`.
Copiela de vez en cuando a una memoria USB: si se dania el disco duro,
una copia en la misma maquina no sirve de mucho.

Al restaurar un respaldo, el sistema **primero guarda una copia de los
datos actuales**, por si hay que volver atras.

### Si un saldo no cuadra

```
.venv\Scripts\python.exe manage.py revisar_saldos
```

Dice exactamente que credito esta descuadrado y por cuanto. Para arreglarlo:

```
.venv\Scripts\python.exe manage.py revisar_saldos --corregir
```

Recalcula los saldos desde los pagos reales. **Nunca borra pagos.**

---

## Comandos utiles

| Comando | Para que sirve |
|---------|----------------|
| `manage.py crear_admin` | Crea o actualiza el usuario administrador |
| `manage.py respaldar` | Crea un respaldo de la base de datos |
| `manage.py respaldar --listar` | Muestra los respaldos existentes |
| `manage.py revisar_saldos` | Revisa que todos los saldos cuadren |
| `manage.py revisar_plantillas` | Revisa que las pantallas tengan todo lo que necesitan |
| `manage.py test cartera` | Ejecuta las 84 pruebas automaticas |

---

## Estructura del proyecto

```
credito/
  manage.py                 Utilidad de linea de comandos
  iniciar.bat               Encender
  detener.bat               Apagar
  requisitos.txt            Librerias necesarias

  credito/                  Configuracion del proyecto
    settings.py             Puerto, base de datos, seguridad, moneda
    urls.py                 Direcciones del sistema

  cartera/                  La aplicacion (todo el codigo del negocio)
    models.py               Clientes, creditos, cuotas, pagos, historial
    forms.py                Formularios con todas las validaciones
    urls.py                 Las direcciones de cada pantalla

    servicios/              Toda la logica de calculo
      calendario.py         Cuando vence cada cuota y como se reparten
      cuotas.py             Crear el plan de pagos y recalcular saldos
      pagos.py              Registrar abonos, parciales, anticipos
      regularidad.py        La barra de comportamiento de pago
      cartera.py            Los numeros del panel, alertas y reportes
      documentos.py         Fotos de cedula protegidas
      respaldo.py           Copias de seguridad
      dinero.py             Formato de pesos y fechas

    vistas/                 Las pantallas
      acceso.py             Entrar y salir
      dashboard.py          Panel
      clientes.py           Clientes y su ficha
      creditos.py           Creditos y cuotas
      cobranza.py           Cobrar, comprobante, anular
      alertas.py            Cobros pendientes
      calendario.py         Calendario de cobros
      reportes.py           Reportes y exportaciones
      configuracion.py      Ajustes, usuarios, respaldos
      api.py                Busqueda rapida

    templatetags/
      formato.py            Etiquetas de pesos, fechas y barras

    management/commands/    Comandos de linea de comandos
    tests.py                62 pruebas de la logica de calculo
    test_pantallas.py       22 pruebas de todas las pantallas

  plantillas/               Las pantallas en HTML
  estatico/css/estilos.css  Como se ve el sistema
  estatico/js/app.js        Como se siente el sistema
  datos/                    La base de datos y las fotos (NO BORRAR)
  respaldos/                Copias de seguridad
```

---

## Como esta armado

**La logica esta en `cartera/servicios/`, no en las pantallas.** Las
pantallas solo pintan. Eso permite cambiar el diseno entero sin tocar un
solo calculo, y probar los calculos sin abrir el navegador.

Las 84 pruebas automaticas (`manage.py test cartera`) comprueban:

- Que la suma de las cuotas sea **exactamente** el saldo financiado, con
  cualquier numero de cuotas y saldo.
- Que un pago con el mismo identificador **no se duplique**.
- Que los pagos parciales, anticipos y anulaciones dejen los saldos
  cuadrados.
- Que la barra de regularidad clasifique bien y respete los umbrales
  configurados.
- Que las 24 pantallas abran sin errores.
- Que las fotos de la cedula no se puedan ver sin iniciar sesion.
- Que un cobrador no pueda tocar la configuracion ni anular pagos.

---

## Se puede usar sin internet

Todo esta instalado en este computador: no hay servicios en la nube ni
librerias que se descarguen en el momento. La base de datos es un solo
archivo (`datos/credito.sqlite3`).

Si quiere entrar desde otro equipo de la casa, en el archivo `.env`
cambie:

```
DIRECCION=0.0.0.0
```

Y abra el puerto 9000 en el firewall de Windows. **Solo en una red de
confianza, con usuarios propios del sistema.**

---

## Se puede crecer despues

La arquitectura ya esta preparada para agregar, sin rehacer nada:

- WhatsApp y recordatorios de cobro (tabla de mensajes + tarea programada)
- Firma digital del cliente al recibir el producto
- Geolocalizacion de clientes y ruta del cobrador
- Varias sucursales y varios cobradores
- Inventario y control de productos entregados
- Facturacion electronica
- Sincronizacion en la nube

---

## Si algo sale mal

1. **Revise el registro de errores:** `datos/errores.log`
2. **Revise que los saldos esten bien:** `manage.py revisar_saldos`
3. **Haga un respaldo antes de tocar nada:** `manage.py respaldar`
4. **Revise que las pantallas estén completas:** `manage.py revisar_plantillas`

Para desarrollo, hay una seccion tecnica opcional en `/admin/` con el
administrador de Django. Esta ahi por si algun dia hace falta revisar
datos de forma directa; el uso normal es por las pantallas del sistema.
