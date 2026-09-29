/*
 * Modo sin conexion del sistema de ventas a credito.
 *
 * Este programa esta pensado para funcionar en lugares donde la senal
 * se cae. Como todo esta instalado en este computador (no en internet),
 * el sistema sigue_ando sin Internet. Este archivo solo guarda en el
 * navegador las pantallas ya vistas, para que si se recarga una pagina
 * mientras no hay senal, no se quede en blanco.
 *
 * NOTA IMPORTANTE: los datos de clientes NO se guardan aqui. Son datos
 * personales. Este archivo solo cachea la estructura de las paginas.
 */

const NOMBRE = "credito-v1";
const ARCHIVOS = [
  "/estatico/css/estilos.css",
  "/estatico/js/app.js",
];

/* Al instalar: se guardan los archivos base. */
self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(NOMBRE)
      .then((cache) => cache.addAll(ARCHIVOS))
      .then(() => self.skipWaiting())
  );
});

/* Al activar: se borra la version vieja. */
self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nombres) => Promise.all(
        nombres.filter((n) => n !== NOMBRE).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
  );
});

/* Al pedir un archivo: primero la red, si no el que esta guardado. */
self.addEventListener("fetch", (evento) => {
  const peticion = evento.request;

  // Solo archivos del sistema. Las consultas de datos (JSON) y las
  // peticiones de escritura SIEMPRE van a la base de datos, nunca al
  // cache: cobrar dos veces seria un desastre.
  if (peticion.method !== "GET") return;
  if (!peticion.url.includes("/estatico/")) return;
  if (peticion.url.includes("/api/")) return;

  evento.respondWith(
    fetch(peticion)
      .then((respuesta) => {
        const copia = respuesta.clone();
        caches.open(NOMBRE).then((cache) => cache.put(peticion, copia));
        return respuesta;
      })
      .catch(() => caches.match(peticion))
  );
});
