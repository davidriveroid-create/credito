/* ==========================================================================
   JavaScript del sistema de ventas a credito y cobranza.

   Sin librerias externas: todo funciona aunque no haya internet.
   ========================================================================== */
(function () {
  "use strict";

  // ------------------------------------------------------------------------
  // Utilidades
  // ------------------------------------------------------------------------

  const $ = (sel, raiz) => (raiz || document).querySelector(sel);
  const $$ = (sel, raiz) => Array.from((raiz || document).querySelectorAll(sel));

  function csrf() {
    const campo = document.querySelector("[name=csrfmiddlewaretoken]");
    if (campo) return campo.value;
    const cookie = document.cookie.split(";").find(c => c.trim().startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  function ajax(url, opciones) {
    opciones = opciones || {};
    return fetch(url, {
      method: opciones.method || "GET",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrf(),
      },
    }).then(r => r.json());
  }

  /* Formatea un numero como pesos colombianos: 1000000 -> $1.000.000 */
  function pesos(valor) {
    const numero = Number(valor || 0);
    if (isNaN(numero)) return "$0";
    return "$" + Math.round(numero).toLocaleString("es-CO");
  }

  /* Quita todo lo que no es numero de un campo de dinero mientras escribe */
  function soloNumeros(campo) {
    campo.addEventListener("input", function () {
      const limpio = campo.value.replace(/[^0-9]/g, "");
      if (campo.value !== limpio) campo.value = limpio;
    });
  }

  /* =========================================================================
     1. BUSQUEDA GLOBAL (barra superior)
     ========================================================================= */
  function busquedaGlobal() {
    const entrada = $("#busqueda-global");
    const contenedor = $("#resultados-busqueda");
    if (!entrada || !contenedor) return;

    let temporizador = null;
    let ultimaPeticion = 0;

    function cerrar() {
      contenedor.classList.remove("visible");
    }

    function pintar(resultados) {
      if (!resultados.length) {
        contenedor.innerHTML = '<div class="vacio">No se encontro ningun cliente con "'
          + escapeHtml(entrada.value) + '"</div>';
        contenedor.classList.add("visible");
        return;
      }

      const html = resultados.map(function (c) {
        return '<a href="' + c.url + '">'
          + '<div class="avatar">' + escapeHtml(c.inicial || "?") + "</div>"
          + '<div class="info">'
          + "<strong>" + escapeHtml(c.nombre) + "</strong>"
          + "<small>" + escapeHtml(c.cedula) + " &middot; " + escapeHtml(c.telefono || "sin telefono") + "</small>"
          + "</div>"
          + '<div class="derecha">'
          + '<div class="' + (c.saldo > 0 ? "texto-naranja negrita" : "texto-verde") + '">'
          + escapeHtml(c.saldo_texto) + "</div>"
          + '<small style="color:' + escapeHtml(c.color) + '">'
          + escapeHtml(c.categoria) + " " + c.regularidad + "%</small>"
          + "</div></a>";
      }).join("");

      contenedor.innerHTML = html;
      contenedor.classList.add("visible");
    }

    entrada.addEventListener("input", function () {
      const texto = entrada.value.trim();
      clearTimeout(temporizador);

      if (texto.length < 2) { cerrar(); return; }

      // Se espera a que el usuario deje de escribir.
      temporizador = setTimeout(function () {
        const numero = ++ultimaPeticion;
        ajax("/api/buscar/?q=" + encodeURIComponent(texto))
          .then(function (datos) {
            // Si el usuario ya escribio mas, se ignora esta respuesta.
            if (numero !== ultimaPeticion) return;
            pintar(datos.resultados || []);
          })
          .catch(function () { /* si falla la red, no se molesta al usuario */ });
      }, 220);
    });

    entrada.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { cerrar(); entrada.blur(); }
      if (e.key === "Enter") {
        e.preventDefault();
        const primero = contenedor.querySelector("a");
        if (primero) window.location = primero.href;
      }
    });

    document.addEventListener("click", function (e) {
      if (!contenedor.contains(e.target) && e.target !== entrada) cerrar();
    });
  }

  function escapeHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto == null ? "" : texto;
    return div.innerHTML;
  }

  /* =========================================================================
     2. MENU LATERAL EN CELULARES
     ========================================================================= */
  function menuLateral() {
    const lateral = $("#lateral");
    const boton = $("#boton-menu");
    const tapa = $("#tapa-menu");
    if (!lateral || !boton) return;

    function abrir() {
      lateral.classList.add("abierto");
      if (tapa) tapa.classList.add("visible");
    }

    function cerrar() {
      lateral.classList.remove("abierto");
      if (tapa) tapa.classList.remove("visible");
    }

    boton.addEventListener("click", function () {
      lateral.classList.contains("abierto") ? cerrar() : abrir();
    });

    if (tapa) tapa.addEventListener("click", cerrar);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") cerrar();
    });
  }

  /* =========================================================================
     3. MENSAJES: se pueden cerrar
     ========================================================================= */
  function mensajesCerrables() {
    $$(".mensaje .cerrar").forEach(function (boton) {
      boton.addEventListener("click", function () {
        const mensaje = boton.closest(".mensaje");
        mensaje.style.opacity = "0";
        setTimeout(function () { mensaje.remove(); }, 200);
      });
    });

    // Los mensajes de exito se van solos despues de 7 segundos.
    $$(".mensaje-exito").forEach(function (mensaje) {
      setTimeout(function () {
        mensaje.style.transition = "opacity .4s";
        mensaje.style.opacity = "0";
        setTimeout(function () { mensaje.remove(); }, 400);
      }, 7000);
    });
  }

  /* =========================================================================
     4. CELDAS DE DINERO: se puede escribir con o sin puntos
     ========================================================================= */
  function camposDinero() {
    $$(".dinero").forEach(soloNumeros);

    // Al salir el campo, le pone los separadores de miles para que se lea
    // mejor. Al volver a entrar, se los quita para poder editar.
    $$(".dinero").forEach(function (campo) {
      campo.addEventListener("blur", function () {
        const valor = campo.value.replace(/[^0-9]/g, "");
        if (valor) {
          campo.value = Number(valor).toLocaleString("es-CO");
        }
      });
      campo.addEventListener("focus", function () {
        campo.value = campo.value.replace(/[^0-9]/g, "");
      });
    });
  }

  /* =========================================================================
     5. COBRO RAPIDO: atajos, cuota seleccionada y aviso de anticipo
     ========================================================================= */
  function cobroRapido() {
    const form = $("#form-cobro");
    if (!form) return;

    const campoValor = $("#id_valor", form);
    const ocultoCuota = $("#id_cuota", form);
    const ocultoAnticipo = $("#id_es_anticipo_confirmado", form);
    const infoCuota = $("#info-cuota");
    const aviso = $("#aviso-anticipo");
    const creditoId = form.dataset.credito;
    const saldoTotal = Number(form.dataset.saldo || 0);

    // --- Atajos de monto (cuota completa, mitad, saldo total) ---------
    $$("[data-monto]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        const tipo = boton.dataset.monto;
        let valor = 0;

        if (tipo === "cuota") {
          valor = Math.floor(Number(boton.dataset.valor || 0));
        } else if (tipo === "saldo") {
          valor = Math.floor(saldoTotal);
        } else if (tipo === "mitad") {
          valor = Math.floor(Number(boton.dataset.valor || 0) / 2);
        }

        if (campoValor) {
          campoValor.value = valor.toLocaleString("es-CO");
          campoValor.focus();
          campoValor.setSelectionRange(campoValor.value.length, campoValor.value.length);
        }
        revisarAnticipo();
      });
    });

    // --- Al elegir otra cuota ------------------------------------------
    $$(".cuota-fila").forEach(function (fila) {
      fila.addEventListener("click", function () {
        $$(".cuota-fila").forEach(f => f.classList.remove("elegida"));
        fila.classList.add("elegida");

        if (ocultoCuota) ocultoCuota.value = fila.dataset.cuota;
        if (campoValor) campoValor.value = Number(fila.dataset.saldo || 0).toLocaleString("es-CO");

        if (infoCuota) {
          infoCuota.innerHTML = fila.dataset.info || "";
        }
        revisarAnticipo();
      });
    });

    var ocultarAnticipo = false;

    /* Revisa si el valor supera el saldo y pide confirmacion. */
    function revisarAnticipo() {
      if (!campoValor || !aviso || !ocultoAnticipo) return;

      const valor = Number(campoValor.value.replace(/[^0-9]/g, "") || 0);

      if (valor > saldoTotal) {
        const exceso = valor - saldoTotal;
        aviso.style.display = "block";
        aviso.innerHTML = "<strong>&#9888; El valor supera el saldo pendiente</strong>"
          + "El cliente deberia " + pesos(saldoTotal) + " pero usted digito " + pesos(valor) + ".<br>"
          + "Si registra " + pesos(valor) + ", quedara un <strong>anticipo de "
          + pesos(exceso) + "</strong> que se descontara de las proximas cuotas.<br>"
          + '<label style="display:inline-flex;align-items:center;gap:.4rem;margin-top:.5rem;cursor:pointer">'
          + '<input type="checkbox" id="confirmar-anticipo" class="casilla"> '
          + "Si, registrar como pago anticipado</label>";
      } else {
        aviso.style.display = "none";
        ocultoAnticipo.value = "";
      }
    }

    // Al marcar la confirmacion del anticipo, se le avisa al formulario
    // (asi Django recibe el campo escondido y no lo descarta).
    function alCambiarConfirmacion(e) {
      if (!e.target || e.target.id !== "confirmar-anticipo") return;
      if (ocultoAnticipo) {
        ocultoAnticipo.value = e.target.checked ? "1" : "";
      }
    }
    document.addEventListener("change", alCambiarConfirmacion);
    document.addEventListener("click", function (e) {
      if (e.target && e.target.id === "confirmar-anticipo") alCambiarConfirmacion(e);
    });

    if (campoValor) campoValor.addEventListener("input", revisarAnticipo);
    revisarAnticipo();

    // --- Evita el doble clic: el segundo intento ya no cobra ----------
    let enviando = false;
    form.addEventListener("submit", function (e) {
      if (enviando) {
        e.preventDefault();
        return;
      }

      const valor = Number((campoValor ? campoValor.value : "").replace(/[^0-9]/g, "") || 0);
      if (valor <= 0) {
        e.preventDefault();
        alert("Escriba el valor que recibio. Debe ser mayor que cero.");
        if (campoValor) campoValor.focus();
        return;
      }

      enviando = true;
      const boton = $("button[type=submit]", form);
      if (boton) {
        boton.disabled = true;
        boton.dataset.textoOriginal = boton.innerHTML;
        boton.innerHTML = "Registrando...";
      }
    });
  }

  /* =========================================================================
     6. FORMULARIO DE CREDITO: calculo en vivo del plan de pagos
     ========================================================================= */
  function creditoEnVivo() {
    const form = $("#form-credito");
    if (!form) return;

    const precioContado = $("#id_precio_contado", form);
    const precioFinanciado = $("#id_precio_financiado", form);
    const cuotaInicial = $("#id_cuota_inicial", form);
    const valorFinanciado = $("#id_valor_financiado", form);
    const numeroCuotas = $("#id_numero_cuotas", form);
    const frecuencia = $("#id_frecuencia", form);
    const primeraCuota = $("#id_fecha_primera_cuota", form);
    const valorCuota = $("#id_valor_cuota", form);
    const productoId = $("#id_producto_id", form);
    const productoTexto = $("#id_producto_texto", form);
    const panel = $("#preview-plan");

    if (precioContado) soloNumeros(precioContado);
    if (precioFinanciado) soloNumeros(precioFinanciado);
    if (cuotaInicial) soloNumeros(cuotaInicial);
    if (valorCuota) soloNumeros(valorCuota);

    // Si elige un producto del catalogo, el nombre se pasa al campo de texto.
    if (productoId) {
      productoId.addEventListener("change", function () {
        const opcion = productoId.options[productoId.selectedIndex];
        if (!opcion || !opcion.value) return;
        const nombre = opcion.textContent.split(" - ")[0];
        if (productoTexto && !productoTexto.value) {
          productoTexto.value = nombre;
        }
      });
    }

    // El saldo financiado se calcula solo.
    function calcularSaldo() {
      if (!precioFinanciado || !cuotaInicial || !valorFinanciado) return 0;
      const total = Number(precioFinanciado.value.replace(/[^0-9]/g, "") || 0);
      const inicial = Number(cuotaInicial.value.replace(/[^0-9]/g, "") || 0);
      const saldo = Math.max(0, total - inicial);
      valorFinanciado.value = saldo.toLocaleString("es-CO");
      return saldo;
    }

    // Pide al servidor el plan de pagos y lo muestra.
    function pedirPlan() {
      if (!panel) return;
      const saldo = calcularSaldo();
      const cuotas = numeroCuotas ? Number(numeroCuotas.value || 0) : 0;

      if (saldo <= 0 || cuotas <= 0 || !frecuencia || !frecuencia.value) {
        panel.style.display = "none";
        return;
      }

      const params = new URLSearchParams({
        precio_financiado: String(saldo),
        cuota_inicial: "0",
        numero_cuotas: String(cuotas),
        frecuencia: frecuencia.value,
        fecha_primera_cuota: primeraCuota ? primeraCuota.value : "",
        valor_cuota: valorCuota ? valorCuota.value.replace(/[^0-9]/g, "") : "",
      });

      panel.style.display = "block";
      panel.innerHTML = '<div class="texto-suave texto-pequeno">Calculando...</div>';

      ajax("/creditos/plan/?" + params.toString())
        .then(function (datos) {
          if (datos.error) {
            panel.innerHTML = '<div class="mensaje mensaje-error">' + escapeHtml(datos.error) + "</div>";
            return;
          }
          if (valorCuota && !valorCuota.value) {
            valorCuota.placeholder = pesos(datos.valor_cuota);
          }

          let filas = "";
          (datos.muestra || []).forEach(function (c) {
            filas += "<tr><td>Cuota " + c.numero + "</td><td>" + formatearFecha(c.fecha)
              + "</td><td class='derecha texto-dinero'>" + pesos(c.valor) + "</td></tr>";
          });
          if (datos.cantidad > 6) {
            filas += '<tr><td colspan="3" class="texto-suave centrado">... y '
              + (datos.cantidad - 6) + " cuotas mas</td></tr>";
          }

          panel.innerHTML =
            '<h4 style="margin:.6rem 0 .3rem">Como quedaria el plan de pagos</h4>'
            + '<div class="tarjeta-mini mb-1">'
            + '<span class="titulo">'
            + datos.cantidad + " cuotas de " + pesos(datos.valor_cuota) + " (" + datos.frecuencia + ")</span>"
            + "Saldo a financiar: <strong>" + pesos(datos.saldo) + "</strong><br>"
            + "Termina aproximadamente el <strong>" + formatearFecha(datos.ultima) + "</strong>"
            + "</div>"
            + '<div class="tabla-envoltura"><table class="tabla-mini">'
            + "<thead><tr><th>Cuota</th><th>Vence</th><th class='derecha'>Valor</th></tr></thead>"
            + "<tbody>" + filas + "</tbody></table></div>";
        })
        .catch(function () {
          panel.innerHTML = '<div class="texto-suave texto-pequeno">No se pudo calcular la '
            + "previsualizacion. Los numeros se calcularan igual al guardar.</div>";
        });
    }

    function formatearFecha(iso) {
      if (!iso) return "-";
      const partes = iso.split("-");
      return partes[2] + "/" + partes[1] + "/" + partes[0];
    }

    [precioFinanciado, cuotaInicial].forEach(function (campo) {
      if (campo) campo.addEventListener("input", pedirPlan);
    });
    [numeroCuotas, frecuencia, primeraCuota, valorCuota].forEach(function (campo) {
      if (campo) campo.addEventListener("change", pedirPlan);
    });

    if (precioContado && precioFinanciado) {
      precioContado.addEventListener("blur", function () {
        if (!precioFinanciado.value) {
          precioFinanciado.value = precioContado.value;
        }
      });
    }
  }

  /* =========================================================================
     7. DATOS SENSIBLES: ver / ocultar cedula
     ========================================================================= */
  function datosSensibles() {
    $$("[data-ver-cifrado]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        const elemento = document.getElementById(boton.dataset.verCifrado);
        if (!elemento) return;
        const oculto = elemento.dataset.real;
        if (elemento.textContent.indexOf("*") === -1) {
          elemento.textContent = "*".repeat(Math.max(6, oculto.length - 3)) + oculto.slice(-3);
          boton.textContent = "ver";
        } else {
          elemento.textContent = oculto;
          boton.textContent = "ocultar";
        }
      });
    });
  }

  /* =========================================================================
     8. CONFIRMAR ACCIONES PELIGROSAS
     ========================================================================= */
  function confirmarPeligroso() {
    $$("[data-confirmar]").forEach(function (elemento) {
      elemento.addEventListener("click", function (e) {
        if (!window.confirm(elemento.dataset.confirmar)) {
          e.preventDefault();
        }
      });
    });
  }

  /* =========================================================================
     9. FILTROS: se aplican al cambiar el campo
     ========================================================================= */
  function filtrosAuto() {
    $$("[data-filtro-auto]").forEach(function (campo) {
      campo.addEventListener("change", function () {
        const form = campo.closest("form");
        if (form) form.submit();
      });
    });
  }

  /* =========================================================================
     10. FOTOS DE CEDULA: subir desde el celular o camara
     ========================================================================= */
  function camaraCedula() {
    $$("input[type=file][accept='image/*']").forEach(function (entrada) {
      entrada.addEventListener("change", function () {
        const archivo = entrada.files && entrada.files[0];
        if (!archivo) return;

        const limite = 12 * 1024 * 1024;
        if (archivo.size > limite) {
          alert("La foto pesa " + Math.round(archivo.size / 1048576) + " MB y el maximo es 12 MB.\n"
            + "Tomela de nuevo con menos calidad.");
          entrada.value = "";
          return;
        }
        if (!archivo.type.startsWith("image/")) {
          alert("Ese archivo no es una imagen.");
          entrada.value = "";
          return;
        }

        // Muestra la vista previa antes de guardar.
        const contenedor = entrada.closest(".grupo");
        if (contenedor) {
          let previa = contenedor.querySelector(".previa-foto");
          if (!previa) {
            previa = document.createElement("img");
            previa.className = "previa-foto";
            previa.style.cssText = "max-width:100%;max-height:180px;margin-top:.5rem;"
              + "border-radius:8px;border:1px solid #e2e8f0";
            contenedor.appendChild(previa);
          }
          const lector = new FileReader();
          lector.onload = function (e) { previa.src = e.target.result; };
          lector.readAsDataURL(archivo);
        }
      });
    });
  }

  /* =========================================================================
     11. AMPLIAR FOTOS (la lupa del comprobante y la cedula)
     ========================================================================= */
  function ampliarFotos() {
    const capa = document.createElement("div");
    capa.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,.9);"
      + "z-index:1000;display:none;align-items:center;justify-content:center;padding:1rem;cursor:zoom-out";
    const imagen = document.createElement("img");
    imagen.style.cssText = "max-width:100%;max-height:100%;border-radius:8px";
    capa.appendChild(imagen);
    document.body.appendChild(capa);

    capa.addEventListener("click", function () { capa.style.display = "none"; });

    $$("[data-ampliar]").forEach(function (img) {
      img.addEventListener("click", function () {
        imagen.src = img.dataset.ampliar || img.src;
        capa.style.display = "flex";
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") capa.style.display = "none";
    });
  }

  /* =========================================================================
     12. IMPRIMIR SOLO UNA PARTE
     ========================================================================= */
  function imprimirParte() {
    $$("[data-imprimir]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        const objetivo = document.getElementById(boton.dataset.imprimir);
        if (!objetivo) return;

        document.body.classList.add("imprimiendo-parte");
        constoriginal = document.body.innerHTML;

        // Se imprime solo el objetivo: se copia al final y se usa CSS.
        const estilos = document.createElement("style");
        estilos.textContent = "@media print{body *{visibility:hidden}#"
          + objetivo.id + ",#" + objetivo.id + " *{visibility:visible}"
          + "#" + objetivo.id + "{position:absolute;left:0;top:0;width:100%}}";
        document.head.appendChild(estilos);

        window.print();

        setTimeout(function () {
          estilos.remove();
        }, 300);
      });
    });
  }

  /* =========================================================================
     13. HISTORIAL DE PAGOS: filtros rapidos
     ========================================================================= */
  function filtrosHistorial() {
    $$("[data-rango]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        const hoy = new Date();
        const desde = new Date();
        const dias = Number(boton.dataset.rango);

        if (boton.dataset.rango === "mes") {
          desde.setDate(1);
        } else if (dias > 0) {
          desde.setDate(hoy.getDate() - dias);
        }

        const campoDesde = $("#desde");
        const campoHasta = $("#hasta");
        if (campoDesde) campoDesde.value = aISO(desde);
        if (campoHasta) campoHasta.value = aISO(hoy);

        const form = boton.closest("form");
        if (form) form.submit();
      });
    });
  }

  function aISO(fecha) {
    return fecha.getFullYear() + "-"
      + String(fecha.getMonth() + 1).padStart(2, "0") + "-"
      + String(fecha.getDate()).padStart(2, "0");
  }

  /* =========================================================================
     ARRANQUE
     ========================================================================= */
  document.addEventListener("DOMContentLoaded", function () {
    busquedaGlobal();
    menuLateral();
    mensajesCerrables();
    camposDinero();
    cobroRapido();
    creditoEnVivo();
    datosSensibles();
    confirmarPeligroso();
    filtrosAuto();
    camaraCedula();
    ampliarFotos();
    imprimirParte();
    filtrosHistorial();
  });
})();
