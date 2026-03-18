# RutaBoss 🚴

**Cronómetro de rutas ciclistas urbanas con QR físicos, validación GPS y leaderboard arcade.**

Los ciclistas escanean códigos QR instalados en los puntos de inicio y fin de cada ruta. El sistema registra el tiempo, valida la ubicación por GPS (fence de 10 metros) y mantiene un ranking permanente estilo arcade de los años 90.

---

## Características

- **QR físicos en la ciudad** — Inicio y fin de ruta con código QR imprimible
- **Validación GPS en backend** — Fence de 10 metros usando fórmula de Haversine
- **Leaderboard arcade** — Top 10 por ruta, dorado/plata/bronce, ticker en vivo en la home
- **Usuarios anónimos** — Guardan iniciales de 3 caracteres estilo máquina arcade
- **Login social** — Google y Facebook via OAuth2 (Authlib)
- **Anti-trampa** — Rechaza tiempos con velocidad media superior a 80 km/h
- **Mapas reales** — OpenStreetMap + Leaflet.js + OSRM routing para ciclistas
- **Panel admin** — Crear rutas, generar QR, activar/desactivar, stats
- **Fotos con EXIF GPS** — El admin puede subir fotos tomadas in situ para extraer coordenadas automáticamente

---

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Flask + SQLAlchemy + SQLite |
| Frontend | Jinja2 + HTMX + Alpine.js |
| Auth | Flask-Login + Authlib (OAuth2) |
| Mapas | Leaflet.js + OpenStreetMap + OSRM |
| QR | librería `qrcode` de Python |
| EXIF | Pillow |
| Tipografías | Press Start 2P (display) · Rajdhani (body) |
| Proxy | Caddy |
| Servicio | systemd user service |
| Paquetes | uv |

---

## Estructura del proyecto

```
rutaBoss/
├── app.py                    # Aplicación Flask y todas las rutas
├── models.py                 # Modelos SQLAlchemy
├── config.py                 # Configuración desarrollo / producción
├── pyproject.toml            # Dependencias (uv)
├── rutaboss.service          # systemd user service
├── Caddyfile                 # Reverse proxy
├── .env.example              # Variables de entorno de ejemplo
├── static/
│   ├── css/main.css          # Estilos arcade (variables, grid, scanlines)
│   └── js/main.js            # GPS, timer, Leaflet, iniciales arcade
├── templates/
│   ├── base.html             # Layout base con navbar y ticker
│   ├── index.html            # Home: lista de rutas + mini leaderboard + ticker
│   ├── ruta.html             # Detalle de ruta + leaderboard top 10 + mapa
│   ├── start.html            # Pantalla de inicio al escanear QR
│   ├── end.html              # Pantalla de llegada al escanear QR
│   ├── resultado.html        # Tiempo final + modal arcade de iniciales
│   ├── perfil.html           # Historial del usuario autenticado
│   └── admin/
│       ├── login.html        # Login del panel admin
│       ├── index.html        # Dashboard admin con stats
│       ├── nueva_ruta.html   # Formulario para crear ruta
│       └── qr.html           # Vista QR para imprimir / exportar PDF
└── uploads/rutas/            # Fotos de inicio y fin (ignoradas en git)
```

---

## Instalación y desarrollo local

### Requisitos

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) instalado

### Setup

```bash
git clone <repo> rutaBoss
cd rutaBoss

# Instalar dependencias
uv sync

# Copiar y editar variables de entorno
cp .env.example .env

# Inicializar la base de datos
uv run flask --app app init-db

# Correr en desarrollo
uv run flask run --port 5006
```

La aplicación queda disponible en `http://localhost:5006`.

### Variables de entorno (`.env`)

```env
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=cambia-esto-en-produccion

# OAuth Google (Google Cloud Console)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# OAuth Facebook (Facebook Developers)
FACEBOOK_CLIENT_ID=
FACEBOOK_CLIENT_SECRET=

# Panel admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin

# URL base de la app
BASE_URL=http://localhost:5006
```

> Las credenciales OAuth deben registrarse manualmente en Google Cloud Console y Facebook Developers. Los redirect URIs necesarios son:
> - `http://localhost:5006/auth/google/callback`
> - `https://rutaboss.nogson.com/auth/google/callback`
> - Equivalentes para Facebook

---

## Panel de administración

Acceder en `/admin/login` con las credenciales definidas en `.env`.

Desde el panel se pueden:

- Crear rutas con foto (extrae GPS del EXIF) o coordenadas manuales
- Generar QR de inicio y fin (imprimibles / exportables a PDF)
- Activar y desactivar rutas
- Ver estadísticas globales (rutas, sesiones completadas, usuarios)

---

## Rutas de la API

### Públicas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Home con lista de rutas y leaderboard top 3 |
| GET | `/ruta/<id>` | Detalle de ruta + leaderboard top 10 + mapa |
| GET | `/start/<id>` | Pantalla de inicio (escaneo QR inicio) |
| POST | `/start/<id>` | Registra sesión y valida GPS fence |
| GET | `/end/<id>` | Pantalla de llegada (escaneo QR fin) |
| POST | `/end/<id>` | Valida GPS, calcula tiempo, cierra sesión |
| GET | `/resultado/<token>` | Resultado final y leaderboard |
| POST | `/resultado/<token>/registrar` | Guarda iniciales anónimas |
| GET | `/perfil` | Historial del usuario autenticado |

### Auth

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/auth/google` | Iniciar OAuth Google |
| GET | `/auth/google/callback` | Callback Google |
| GET | `/auth/facebook` | Iniciar OAuth Facebook |
| GET | `/auth/facebook/callback` | Callback Facebook |
| POST | `/auth/logout` | Cerrar sesión |

### Admin (requiere login admin)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/admin/` | Dashboard |
| GET/POST | `/admin/nueva` | Crear ruta |
| GET | `/admin/ruta/<id>/qr` | Ver QR para imprimir |
| POST | `/admin/ruta/<id>/toggle` | Activar / desactivar ruta |
| POST | `/admin/ruta/<id>/borrar` | Eliminar ruta |

---

## Lógica de negocio

### GPS fence (10 metros)

Cada vez que un ciclista pulsa "Iniciar" o "Registrar llegada", el navegador obtiene la ubicación GPS y la envía al backend. El servidor calcula la distancia usando la fórmula de Haversine. Si el ciclista está a más de 10 metros del punto marcado, la acción se rechaza con la distancia actual.

### Sesiones y expiración

Cada sesión tiene una duración máxima de 3 horas. Las sesiones vencidas se marcan como `expirada` en cada request al home, o manualmente con:

```bash
uv run flask --app app expire-sessions
```

Se recomienda ejecutar este comando con cron cada hora en producción.

### Anti-trampa por velocidad

Si el tiempo registrado implica una velocidad media superior a **80 km/h** (considerando descensos extremos), la sesión se marca como `invalida` y no se registra en el leaderboard.

### Leaderboard

- Usuarios registrados: se muestra solo su **mejor tiempo** por ruta.
- Usuarios anónimos: cada intento aparece de forma independiente.
- Solo se muestran tiempos con GPS válido (`gps_valido = True`).

---

## Despliegue en producción (servidor `penelope`)

### Requisitos en el servidor

- Python 3.13+, uv, Caddy, systemd

### Pasos

```bash
# En el servidor
git clone <repo> /home/penelope/Dev/rutaBoss
cd /home/penelope/Dev/rutaBoss
uv sync
cp .env.example .env
# Editar .env con SECRET_KEY segura y credenciales OAuth

uv run flask --app app init-db

# Instalar y activar el servicio
cp rutaboss.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rutaboss

# Instalar Caddyfile
# Añadir o fusionar con el Caddyfile global de Caddy
```

### systemd service

```ini
[Unit]
Description=RutaBoss Flask App
After=network.target

[Service]
WorkingDirectory=/home/penelope/Dev/rutaBoss
ExecStart=/home/penelope/Dev/rutaBoss/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5006 app:app
Restart=always
Environment=FLASK_ENV=production

[Install]
WantedBy=default.target
```

### Caddy

```
rutaboss.nogson.com {
    reverse_proxy 127.0.0.1:5006
    encode gzip
    file_server
}
```

---

## Comandos CLI

```bash
# Inicializar la base de datos
uv run flask --app app init-db

# Expirar sesiones antiguas (>3h)
uv run flask --app app expire-sessions
```

---

## Modelos de datos

```
Usuario       id · nombre · email · foto_url · proveedor · creado_en
Ruta          id · nombre · descripcion · dificultad · distancia_km · desnivel_m
              lat_inicio · lon_inicio · lat_fin · lon_fin · foto_inicio · foto_fin · activa · creada_en
Sesion        id · ruta_id · token · lat_inicio_real · lon_inicio_real · gps_valido
              iniciada_en · completada_en · tiempo_segundos · estado · usuario_id · iniciales_anonimo
Tiempo        id · sesion_id · ruta_id · usuario_id · iniciales_anonimo
              tiempo_segundos · gps_valido · registrado_en
```

---

## Licencia

Uso privado. Todos los derechos reservados.
