# RutaBoss — Prompt de implementación para Claude Code

## Contexto

Construye **[[RutaBoss]]**, una aplicación web móvil-first para cronometrar rutas ciclistas reales en la ciudad. Los ciclistas escanean códigos QR físicos instalados en puntos de inicio y fin de cada ruta. El sistema registra tiempos, valida ubicación por GPS y mantiene un leaderboard permanente estilo arcade.

El proyecto se desarrolla en laptop y se despliega en el servidor `penelope` (Debian). Usa **Caddy** como reverse proxy y **systemd user services**. Directorio de producción: `/home/penelope/Dev/rutaBoss`.

---

## Stack

- **Backend:** Flask + SQLAlchemy + SQLite
- **Frontend:** Jinja2 + HTMX + Alpine.js
- **Mapas:** OpenStreetMap via Leaflet.js
- **Auth:** Flask-Login + OAuth (Google, Facebook) + modo anónimo
- **QR:** librería `qrcode` de Python
- **EXIF:** librería `Pillow` para extraer GPS de fotos
- **Proxy:** Caddy
- **Servicio:** systemd user service
- **Fuentes:** Press Start 2P (display), Rajdhani (body) via Google Fonts

---

## Estructura de archivos

```
rutaboss/
├── app.py
├── models.py
├── config.py
├── requirements.txt
├── rutaboss.service          # systemd user service
├── Caddyfile
├── static/
│   ├── css/
│   │   └── main.css
│   └── js/
│       └── main.js
├── templates/
│   ├── base.html
│   ├── index.html            # Explorar rutas
│   ├── ruta.html             # Detalle de ruta + leaderboard
│   ├── start.html            # Pantalla al escanear QR de inicio
│   ├── end.html              # Pantalla al escanear QR de fin
│   ├── resultado.html        # Tiempo final + formulario si top 10
│   ├── perfil.html           # Historial del usuario registrado
│   └── admin/
│       ├── index.html        # Panel admin
│       ├── nueva_ruta.html   # Formulario nueva ruta
│       └── qr.html           # Vista de QR para imprimir/PDF
└── uploads/
    └── rutas/                # Fotos de inicio y fin
```

---

## Modelos (models.py)

### Ruta

```
id, nombre, descripcion, dificultad (facil/intermedio/dificil),
distancia_km, desnivel_m,
lat_inicio, lon_inicio, lat_fin, lon_fin,
foto_inicio, foto_fin,
activa (bool), creada_en
```

### Sesion

```
id, ruta_id, token (uuid único),
lat_inicio_real, lon_inicio_real,
gps_valido (bool),
iniciada_en, completada_en,
tiempo_segundos,
estado (iniciada/completada/expirada/invalida),
usuario_id (nullable), iniciales_anonimo (nullable, 3 chars)
```

### Usuario

```
id, nombre, email, foto_url,
proveedor (google/facebook),
creado_en
```

### Tiempo

```
id, sesion_id, ruta_id, usuario_id (nullable),
iniciales_anonimo (nullable),
tiempo_segundos, gps_valido (bool),
registrado_en
```

---

## Rutas URL (Flask)

### Públicas

- `GET /` — página principal, lista de rutas con mini leaderboard top 3
- `GET /ruta/<ruta_id>` — detalle de ruta + leaderboard top 10
- `GET /start/<ruta_id>` — pantalla de inicio al escanear QR de inicio
- `POST /start/<ruta_id>` — registra sesión, valida GPS fence 10m, devuelve token
- `GET /end/<ruta_id>` — si no hay sesión activa válida → redirect a `/`
- `POST /end/<ruta_id>` — valida GPS fence fin, calcula tiempo, cierra sesión
- `GET /resultado/<sesion_token>` — muestra tiempo, formulario si top 10
- `POST /resultado/<sesion_token>/registrar` — guarda nombre/iniciales
- `GET /perfil` — historial del usuario autenticado

### Auth

- `GET /auth/google` — OAuth Google
- `GET /auth/google/callback`
- `GET /auth/facebook` — OAuth Facebook
- `GET /auth/facebook/callback`
- `POST /auth/logout`

### Admin (protegido por login admin)

- `GET /admin/` — dashboard: lista de rutas, stats
- `GET /admin/nueva` — formulario nueva ruta
- `POST /admin/nueva` — procesa fotos, extrae EXIF, crea ruta
- `GET /admin/ruta/<ruta_id>/qr` — vista QR para imprimir
- `POST /admin/ruta/<ruta_id>/toggle` — activar/desactivar ruta
- `POST /admin/ruta/<ruta_id>/borrar` — borrar ruta

---

## Lógica de negocio crítica

### GPS fence (10 metros)

Usar fórmula de Haversine para calcular distancia entre coordenadas del usuario y coordenadas del QR. Si distancia > 10m → rechazar con mensaje de error y distancia actual.

```python
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # metros
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))
```

### Expiración de sesiones (3 horas)

Tarea programada o verificación en cada request: si `iniciada_en` tiene más de 3 horas y estado es `iniciada` → marcar como `expirada`.

### Anti-trampa por velocidad

Al calcular el tiempo, verificar que la velocidad promedio no sea imposible para bicicleta:

- Velocidad máxima aceptable: **80 km/h** (considerando descensos)
- Si `distancia_km / (tiempo_segundos / 3600) > 80` → marcar sesión como `invalida` y no registrar en leaderboard

### Extracción GPS de fotos (admin)

Al subir fotos de inicio y fin:

1. Usar Pillow para leer datos EXIF
2. Si no hay datos GPS → rechazar la foto con mensaje claro
3. Convertir coordenadas DMS a decimal
4. Guardar lat/lon en la ruta

```python
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def get_exif_gps(image_path):
    img = Image.open(image_path)
    exif_data = img._getexif()
    # extraer GPSInfo → convertir a decimal
    # retornar (lat, lon) o None si no hay GPS
```

### Leaderboard

- Solo tiempos con `gps_valido = True` aparecen en el leaderboard
- Por usuario registrado: solo su **mejor tiempo** por ruta
- Anónimos: cada intento es independiente
- Top 10 por ruta, ordenado por `tiempo_segundos ASC`

### Sesión QR end sin inicio

En `GET /end/<ruta_id>`: verificar si existe cookie/token de sesión activa para esa ruta. Si no existe o está expirada → `redirect('/')`.

---

## Diseño (CSS)

Paleta de colores (variables CSS en `main.css`):

```css
--bg: #1a1f2e;
--bg2: #222840;
--bg3: #2a3150;
--card: #1e2438;
--border: #3a4468;
--gold: #f5c842;
--cyan: #4dd9e8;
--red: #e84d6a;
--green: #4de87a;
--text: #d8dff0;
--text2: #8a96b8;
```

Estética: arcade contenida. Fondo oscuro azul pizarrón, no negro puro. Grid sutil de fondo. Scanlines sutiles. Fuente Press Start 2P para títulos y datos clave, Rajdhani para texto corrido. No hipernéon — colores vivos pero respirables.

Elementos UI clave:

- Leaderboard con rank 1/2/3 en dorado/plata/bronce
- Usuarios anónimos muestran iniciales en fuente pixel color cyan
- Ticker horizontal en vivo en la home (actividad reciente)
- Botón de inicio grande con aviso de GPS fence
- Mapa Leaflet con ruta real entre inicio y fin
- Cards de ruta con mini mapa SVG esquemático

---

## Generación de QR

Usar librería `qrcode` de Python. Cada ruta tiene dos QR:

- QR inicio → URL: `https://rutaboss.nogson.com/start/<ruta_id>`
- QR fin → URL: `https://rutaboss.nogson.com/end/<ruta_id>`

Vista `/admin/ruta/<id>/qr` debe mostrar ambos QR con:

- Nombre de la ruta
- Etiqueta INICIO / FIN
- Botón imprimir (CSS print media query que oculta nav y muestra solo los QR)
- Botón exportar PDF (usando `window.print()` con destino PDF)

---

## Mapa con OpenStreetMap + Leaflet

En `ruta.html` y `start.html`: cargar Leaflet.js desde CDN, mostrar mapa con:

- Tile layer de OpenStreetMap
- Marcador verde en inicio, rojo en fin
- Ruta real usando OSRM routing API (gratuita):
  `http://router.project-osrm.org/route/v1/cycling/{lon_inicio},{lat_inicio};{lon_fin},{lat_fin}?overview=full&geometries=geojson`
- Línea cyan sobre la ruta

---

## Auth anónimo (iniciales arcade)

Si el usuario queda en top 10 y no está logueado, mostrar modal con:

- Campo de 3 caracteres (solo letras y números, uppercase automático)
- Estilo visual de máquina arcade de los 90s
- Opciones: "GUARDAR INICIALES" o "ENTRAR CON GOOGLE/FACEBOOK"
- Si no hace nada: el tiempo se guarda sin nombre visible

---

## Desarrollo local (laptop)

### Requisitos previos

- `uv` instalado
- Credenciales OAuth registradas con redirect URIs:
  - `http://localhost:5006/auth/google/callback`
  - `http://localhost:5006/auth/facebook/callback`

### Setup inicial

```bash
git clone <repo> rutaBoss
cd rutaBoss
uv sync
cp .env.example .env
# editar .env con tus credenciales
```

### Archivo `.env.example`

```env
FLASK_ENV=development
FLASK_DEBUG=1
SECRET_KEY=dev-secret-key-cambiar-en-produccion

# OAuth Google
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# OAuth Facebook
FACEBOOK_CLIENT_ID=
FACEBOOK_CLIENT_SECRET=

# Admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin

# URLs
BASE_URL=http://localhost:5006
```

### Correr en desarrollo

```bash
uv run flask run --port 5006
```

### config.py — detección de entorno

```python
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///rutaboss.db'
    BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5006')
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    FACEBOOK_CLIENT_ID = os.environ.get('FACEBOOK_CLIENT_ID')
    FACEBOOK_CLIENT_SECRET = os.environ.get('FACEBOOK_CLIENT_SECRET')
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads', 'rutas')

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    BASE_URL = 'https://rutaboss.nogson.com'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}
```

> **Nota:** Las credenciales OAuth deben registrarse manualmente en Google Cloud Console y Facebook Developers con ambas redirect URIs (localhost y producción). No se pueden automatizar.

---

## Configuración de despliegue

### systemd user service (`rutaboss.service`)

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

### Caddyfile

```
rutaboss.nogson.com {
    reverse_proxy 127.0.0.1:5006
    encode gzip
    file_server
}
```

---

## Gestión de dependencias con uv

Usar `uv` para manejar el entorno virtual y las dependencias.

### Inicializar el proyecto

```bash
uv init rutaBoss
cd rutaBoss
```

### Agregar dependencias

```bash
uv add flask flask-login flask-sqlalchemy flask-oauthlib gunicorn pillow "qrcode[pil]" requests python-dotenv
```

### Correr en desarrollo

```bash
uv run flask run
```

### Archivo `pyproject.toml` resultante (dependencias)

```toml
[project]
name = "rutaboss"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flask",
    "flask-login",
    "flask-sqlalchemy",
    "flask-oauthlib",
    "gunicorn",
    "pillow",
    "qrcode[pil]",
    "requests",
    "python-dotenv"
]
```

### systemd service con uv

El servicio usa el entorno virtual generado por uv:

```ini
ExecStart=/home/penelope/Dev/rutaBoss/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5006 app:app
```

---

## Notas de implementación

1. El token de sesión se guarda en una **cookie firmada** al iniciar la ruta. Se usa para validar el QR de fin.
2. La verificación del GPS fence se hace en el **backend**, nunca confiar solo en el frontend.
3. Las fotos subidas por el admin se guardan en `/home/penelope/Dev/rutaBoss/uploads/rutas/` con nombre `<ruta_id>_inicio.jpg` y `<ruta_id>_fin.jpg`.
4. Implementar un **comando CLI** `flask expire-sessions` para limpiar sesiones expiradas (puede correrse con cron cada hora).
5. El panel de admin usa un usuario hardcodeado en `config.py` (no OAuth), protegido con `@login_required` y verificación de rol admin.
6. Generar un `.gitignore` apropiado para el proyecto que excluya: `.env`, `*.db`, `__pycache__`, `.venv`, `uploads/rutas/`, `*.pyc`, `.DS_Store`.
