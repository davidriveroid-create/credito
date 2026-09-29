"""
Configuracion del sistema de ventas a credito y cobranza.

Proyecto independiente: base de datos, usuarios, sesiones, archivos y
estaticos propios. No comparte nada con ningun otro programa instalado
en este computador.

Arranque:      .venv\\Scripts\\python.exe manage.py runserver 127.0.0.1:9000
Pruebas:      .venv\\Scripts\\python.exe manage.py test
Respaldo:     .venv\\Scripts\\python.exe manage.py respaldar
"""

from pathlib import Path

from decouple import config

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# Carpeta de datos: base de datos, fotos de cedula y respaldos.
CARPETA_DATOS = Path(config("CARPETA_DATOS", default="datos"))
if not CARPETA_DATOS.is_absolute():
    CARPETA_DATOS = BASE_DIR / CARPETA_DATOS
CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

# Las fotos de cedula NUNCA se sirven como archivo publico. Se guardan aqui
# y solo se ven pasando por una vista que revisa que el usuario este
# conectado y tenga permiso.
CARPETA_DOCUMENTOS = CARPETA_DATOS / "documentos"
CARPETA_DOCUMENTOS.mkdir(parents=True, exist_ok=True)

CARPETA_RESPALDOS = BASE_DIR / "respaldos"
CARPETA_RESPALDOS.mkdir(parents=True, exist_ok=True)

CARPETA_TIEMPO = CARPETA_DATOS / "temporal"
CARPETA_TIEMPO.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------

SECRET_KEY = config("SECRET_KEY")

DEBUG = config("DEBUG", default=False, cast=bool)

# Compartir por la red local (Radmin VPN, otros equipos de la casa).
DIRECCION = config("DIRECCION", default="127.0.0.1")

PUERTO = config("PUERTO", default=9000, cast=int)

ALLOWED_HOSTS = ['*']
if DIRECCION == "0.0.0.0":
    ALLOWED_HOSTS += ["192.168.1.2", "26.30.0.89"]

# Cuantas veces puede mirar mal una contrasena antes de que se bloquee.
NUMERO_INTENTOS_LOGIN = 5
BLOQUEO_MINUTOS = 10


# ---------------------------------------------------------------------------
# Aplicaciones
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cartera",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "cartera.middleware.RegistroAccesosMiddleware",
]

ROOT_URLCONF = "credito.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "plantillas"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cartera.context_processors.negocio",
            ],
            # Los filtros de dinero y fechas (|peses, |fecha, |color_estado)
            # se cargan en cada plantilla con {% load formato %}. Ojo: Django
            # NO hereda los {% load %} a las plantillas hijas, asi que cada
            # archivo que los use necesita su propia linea. Las pruebas de
            # humo recorren todas las pantallas y avisan si falta alguna.
        },
    },
]

WSGI_APPLICATION = "credito.wsgi.application"
ASGI_APPLICATION = "credito.asgi.application"


# ---------------------------------------------------------------------------
# Base de datos (SQLite: un solo archivo, sin instalar nada mas)
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": CARPETA_DATOS / "credito.sqlite3",
        "OPTIONS": {
            # Espera si otro proceso tiene la base escrita. Evita errores
            # de "database is locked" cuando se hacen respaldos mientras
            # se esta usando el programa.
            "timeout": 20,
            # Llaves foraneas activas: la base no deja datos sueltos.
            "init_command": "PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Sesiones
#
# El nombre de la cookie es propio de esta aplicacion para que el programa
# de contabilidad que tambien esta instalado en este computador nunca se
# confunda con este sistema.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "credito_sesion"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12  # 12 horas de trabajo

CSRF_COOKIE_NAME = "credito_csrf"
CSRF_COOKIE_HTTPONLY = False  # el formulario lo necesita para enviarse
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [
    f"http://127.0.0.1:{PUERTO}",
    f"http://localhost:{PUERTO}",
]

CSRF_FAILURE_VIEW = "cartera.vistas.errores.error_csrf"

# Cookies seguras cuando el programa se sirve por https.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # en red local sin https, no rompe nada
    SECURE_HSTS_SECONDS = 0


# ---------------------------------------------------------------------------
# Archivos subidos
# ---------------------------------------------------------------------------

MEDIA_ROOT = CARPETA_DOCUMENTOS
MEDIA_URL = "/documentos/"

# NO se usa django.views.static.serve para /documentos/. Las fotos de cedula
# se entregan por una vista propia con control de acceso. Ver urls.py.
MEDIA_SERVE_PROHIBIDO = True

STATIC_URL = "estatico/"
STATICFILES_DIRS = [BASE_DIR / "estatico"]
STATIC_ROOT = BASE_DIR / "compilado-estatico"

# Uso temporal de archivos subidos.
FILE_UPLOAD_TEMP_DIR = CARPETA_TIEMPO
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024  # 12 MB por archivo
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# Politica de contrasenas: facil de recordar pero con un minimo razonable.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "entrar"


# ---------------------------------------------------------------------------
# Idioma, moneda, fechas
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# Los campos <input type=date> de HTML SOLO aceptan el formato ISO
# (AAAA-MM-DD). Si se deja el formato colombiano, el navegador rechaza el
# valor y el campo se ve vacio aunque el servidor lo mande bien. Por eso los
# formularios usan ISO y el sistema muestra dd/mm/aaaa al pintarlo.
DATE_INPUT_FORMATS = ['%Y-%m-%d']
DATETIME_INPUT_FORMATS = ['%Y-%m-%d %H:%M:%S']

# Formato de fechas que usa el programa en los listados.
FORMATO_FECHA = "%d/%m/%Y"
FORMATO_FECHA_LARGA = "%d de %B de %Y"
FORMATO_HORA = "%I:%M %p"

# Los pesos colombianos no usan decimales: 1.000.000 y no 1.000.000,00
MONEDA_SIMBOLO = "$"
MONEDA_CODIGO = "COP"
MONEDA_DECIMALES = 0

# Dias de atraso desde los cuales un cliente entra en categoria MOROSO.
DIAS_MORA_POR_DEFECTO = config("DIAS_MORA", default=15, cast=int)


# ---------------------------------------------------------------------------
# Correo: solo para recordar contrasenas. Se deja vacio a proposito para
# que el sistema no intente salir a internet solo para eso.
# ---------------------------------------------------------------------------

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "sistema@credito.local"


# ---------------------------------------------------------------------------
# Registro de errores
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detallado": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "archivo": {
            "class": "logging.FileHandler",
            "filename": str(CARPETA_DATOS / "errores.log"),
            "formatter": "detallado",
            "encoding": "utf-8",
        },
        "consola": {
            "class": "logging.StreamHandler",
            "formatter": "detallado",
        },
    },
    "loggers": {
        "cartera": {
            "handlers": ["archivo", "consola"],
            "level": "INFO",
            "propagate": False,
        },
        "cartera.errores": {
            "handlers": ["archivo", "consola"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
