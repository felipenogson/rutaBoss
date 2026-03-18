import os
import uuid
import io
import base64
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timedelta
from functools import wraps

import qrcode
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, make_response
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth

from config import config
from models import db, Usuario, Ruta, Sesion, Tiempo


def create_app(env=None):
    app = Flask(__name__)
    if env is None:
        env = os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config[env])
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)

    login_manager = LoginManager(app)
    login_manager.login_view = 'index'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Usuario, int(user_id))

    oauth = OAuth(app)

    google = oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

    facebook = oauth.register(
        name='facebook',
        client_id=app.config.get('FACEBOOK_CLIENT_ID'),
        client_secret=app.config.get('FACEBOOK_CLIENT_SECRET'),
        api_base_url='https://graph.facebook.com/',
        access_token_url='https://graph.facebook.com/oauth/access_token',
        authorize_url='https://www.facebook.com/dialog/oauth',
        client_kwargs={'scope': 'email'},
    )

    # ── Helpers ────────────────────────────────────────────────────────────

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))

    def get_exif_gps(image_path):
        try:
            img = Image.open(image_path)
            exif_data = img._getexif()
            if not exif_data:
                return None
            gps_info = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == 'GPSInfo':
                    for gps_tag_id, gps_value in value.items():
                        gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                        gps_info[gps_tag] = gps_value
            if not gps_info:
                return None

            def dms_to_dd(dms, ref):
                d, m, s = dms
                dd = float(d) + float(m) / 60 + float(s) / 3600
                if ref in ('S', 'W'):
                    dd = -dd
                return dd

            lat = dms_to_dd(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
            lon = dms_to_dd(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
            return lat, lon
        except Exception:
            return None

    def expire_old_sessions():
        cutoff = datetime.utcnow() - timedelta(hours=3)
        old = Sesion.query.filter(
            Sesion.estado == 'iniciada',
            Sesion.iniciada_en < cutoff
        ).all()
        for s in old:
            s.estado = 'expirada'
        if old:
            db.session.commit()

    def get_leaderboard(ruta_id, limit=10):
        user_times = (
            db.session.query(
                db.func.min(Tiempo.tiempo_segundos).label('mejor'),
                Usuario.nombre,
                Usuario.foto_url,
                Tiempo.usuario_id,
            )
            .join(Usuario, Tiempo.usuario_id == Usuario.id)
            .filter(Tiempo.ruta_id == ruta_id, Tiempo.gps_valido == True, Tiempo.usuario_id != None)
            .group_by(Tiempo.usuario_id)
            .all()
        )
        anon_times = (
            Tiempo.query
            .filter(Tiempo.ruta_id == ruta_id, Tiempo.gps_valido == True, Tiempo.usuario_id == None)
            .all()
        )
        entries = []
        for t in user_times:
            entries.append({
                'tiempo': t.mejor,
                'nombre': t.nombre,
                'foto_url': t.foto_url,
                'anonimo': False,
                'iniciales': None,
            })
        for t in anon_times:
            entries.append({
                'tiempo': t.tiempo_segundos,
                'nombre': None,
                'foto_url': None,
                'anonimo': True,
                'iniciales': t.iniciales_anonimo or '???',
            })
        entries.sort(key=lambda x: x['tiempo'])
        for i, e in enumerate(entries):
            e['rank'] = i + 1
        return entries[:limit]

    def admin_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('admin_logged_in'):
                return redirect(url_for('admin_login'))
            return f(*args, **kwargs)
        return decorated

    def format_tiempo(segundos):
        m, s = divmod(segundos, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    app.jinja_env.filters['format_tiempo'] = format_tiempo

    # ── CLI commands ───────────────────────────────────────────────────────

    @app.cli.command('expire-sessions')
    def expire_sessions_cmd():
        expire_old_sessions()
        print("Sesiones expiradas procesadas.")

    @app.cli.command('init-db')
    def init_db_cmd():
        db.create_all()
        print("Base de datos inicializada.")

    # ── Public routes ──────────────────────────────────────────────────────

    @app.route('/')
    def index():
        expire_old_sessions()
        rutas = Ruta.query.filter_by(activa=True).all()
        rutas_data = []
        for r in rutas:
            lb = get_leaderboard(r.id, limit=3)
            rutas_data.append({'ruta': r, 'leaderboard': lb})
        actividad = (
            Tiempo.query
            .order_by(Tiempo.registrado_en.desc())
            .limit(20)
            .all()
        )
        return render_template('index.html', rutas_data=rutas_data, actividad=actividad)

    @app.route('/ruta/<int:ruta_id>')
    def ruta_detalle(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        leaderboard = get_leaderboard(ruta_id, limit=10)
        return render_template('ruta.html', ruta=ruta, leaderboard=leaderboard)

    @app.route('/start/<int:ruta_id>', methods=['GET', 'POST'])
    def start(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        if not ruta.activa:
            flash('Esta ruta no está activa.')
            return redirect(url_for('index'))

        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
            try:
                lat = float(data.get('lat'))
                lon = float(data.get('lon'))
            except (TypeError, ValueError):
                return jsonify({'error': 'GPS requerido'}), 400

            distancia = haversine(lat, lon, ruta.lat_inicio, ruta.lon_inicio)
            gps_valido = distancia <= 10

            token = str(uuid.uuid4())
            sesion = Sesion(
                ruta_id=ruta_id,
                token=token,
                lat_inicio_real=lat,
                lon_inicio_real=lon,
                gps_valido=gps_valido,
                usuario_id=current_user.id if current_user.is_authenticated else None,
            )
            db.session.add(sesion)
            db.session.commit()

            resp = make_response(jsonify({
                'token': token,
                'gps_valido': gps_valido,
                'distancia': round(distancia, 1),
            }))
            resp.set_cookie(f'sesion_{ruta_id}', token, max_age=3 * 3600, httponly=True, samesite='Lax')
            return resp

        return render_template('start.html', ruta=ruta)

    @app.route('/end/<int:ruta_id>', methods=['GET', 'POST'])
    def end(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        token = request.cookies.get(f'sesion_{ruta_id}')
        if not token:
            return redirect(url_for('index'))

        sesion = Sesion.query.filter_by(token=token, ruta_id=ruta_id).first()
        if not sesion or sesion.estado != 'iniciada':
            return redirect(url_for('index'))

        if datetime.utcnow() - sesion.iniciada_en > timedelta(hours=3):
            sesion.estado = 'expirada'
            db.session.commit()
            return redirect(url_for('index'))

        if request.method == 'POST':
            data = request.get_json(silent=True) or request.form
            try:
                lat = float(data.get('lat'))
                lon = float(data.get('lon'))
            except (TypeError, ValueError):
                return jsonify({'error': 'GPS requerido'}), 400

            distancia = haversine(lat, lon, ruta.lat_fin, ruta.lon_fin)
            if distancia > 10:
                return jsonify({'error': f'Estás a {round(distancia, 1)}m del punto de llegada. Máximo 10m.'}), 400

            ahora = datetime.utcnow()
            tiempo_segundos = int((ahora - sesion.iniciada_en).total_seconds())

            if ruta.distancia_km and tiempo_segundos > 0:
                velocidad = ruta.distancia_km / (tiempo_segundos / 3600)
                if velocidad > 80:
                    sesion.estado = 'invalida'
                    sesion.completada_en = ahora
                    sesion.tiempo_segundos = tiempo_segundos
                    db.session.commit()
                    return jsonify({'error': 'Tiempo inválido: velocidad imposible para bicicleta.'}), 400

            sesion.completada_en = ahora
            sesion.tiempo_segundos = tiempo_segundos
            sesion.estado = 'completada'
            db.session.commit()

            tiempo = Tiempo(
                sesion_id=sesion.id,
                ruta_id=ruta_id,
                usuario_id=sesion.usuario_id,
                tiempo_segundos=tiempo_segundos,
                gps_valido=sesion.gps_valido,
            )
            db.session.add(tiempo)
            db.session.commit()

            resp = make_response(jsonify({'redirect': url_for('resultado', token=token)}))
            resp.delete_cookie(f'sesion_{ruta_id}')
            return resp

        return render_template('end.html', ruta=ruta, sesion=sesion)

    @app.route('/resultado/<token>')
    def resultado(token):
        sesion = Sesion.query.filter_by(token=token).first_or_404()
        ruta = sesion.ruta
        leaderboard = get_leaderboard(ruta.id, limit=10)

        is_top10 = False
        if sesion.tiempo_registrado and sesion.estado == 'completada':
            t = sesion.tiempo_registrado[0]
            matching = [e for e in leaderboard if e['tiempo'] == t.tiempo_segundos]
            if matching and matching[0]['rank'] <= 10:
                is_top10 = True

        return render_template('resultado.html', sesion=sesion, ruta=ruta,
                               leaderboard=leaderboard, is_top10=is_top10)

    @app.route('/resultado/<token>/registrar', methods=['POST'])
    def registrar_resultado(token):
        sesion = Sesion.query.filter_by(token=token).first_or_404()
        iniciales = request.form.get('iniciales', '').upper()[:3]
        if not iniciales.isalnum():
            flash('Iniciales inválidas. Solo letras y números.')
            return redirect(url_for('resultado', token=token))

        if sesion.tiempo_registrado:
            t = sesion.tiempo_registrado[0]
            t.iniciales_anonimo = iniciales
            sesion.iniciales_anonimo = iniciales
            db.session.commit()

        return redirect(url_for('resultado', token=token))

    @app.route('/perfil')
    @login_required
    def perfil():
        tiempos = (
            Tiempo.query
            .filter_by(usuario_id=current_user.id)
            .order_by(Tiempo.registrado_en.desc())
            .all()
        )
        return render_template('perfil.html', tiempos=tiempos)

    # ── Auth routes ────────────────────────────────────────────────────────

    @app.route('/auth/google')
    def auth_google():
        redirect_uri = url_for('auth_google_callback', _external=True)
        return google.authorize_redirect(redirect_uri)

    @app.route('/auth/google/callback')
    def auth_google_callback():
        try:
            token = google.authorize_access_token()
            userinfo = token.get('userinfo') or google.userinfo()
        except Exception:
            flash('Login con Google fallido.')
            return redirect(url_for('index'))

        email = userinfo.get('email')
        if not email:
            flash('No se pudo obtener el email de Google.')
            return redirect(url_for('index'))

        usuario = Usuario.query.filter_by(email=email).first()
        if not usuario:
            usuario = Usuario(
                nombre=userinfo.get('name', ''),
                email=email,
                foto_url=userinfo.get('picture'),
                proveedor='google',
            )
            db.session.add(usuario)
            db.session.commit()
        login_user(usuario)
        return redirect(url_for('index'))

    @app.route('/auth/facebook')
    def auth_facebook():
        redirect_uri = url_for('auth_facebook_callback', _external=True)
        return facebook.authorize_redirect(redirect_uri)

    @app.route('/auth/facebook/callback')
    def auth_facebook_callback():
        try:
            facebook.authorize_access_token()
            resp = facebook.get('/me?fields=id,name,email,picture')
            data = resp.json()
        except Exception:
            flash('Login con Facebook fallido.')
            return redirect(url_for('index'))

        email = data.get('email', f"fb_{data['id']}@facebook.local")
        usuario = Usuario.query.filter_by(email=email).first()
        if not usuario:
            pic = data.get('picture', {}).get('data', {}).get('url')
            usuario = Usuario(
                nombre=data.get('name', ''),
                email=email,
                foto_url=pic,
                proveedor='facebook',
            )
            db.session.add(usuario)
            db.session.commit()
        login_user(usuario)
        return redirect(url_for('index'))

    @app.route('/auth/logout', methods=['POST'])
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for('index'))

    # ── Admin routes ───────────────────────────────────────────────────────

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if (username == app.config['ADMIN_USERNAME'] and
                    password == app.config['ADMIN_PASSWORD']):
                session['admin_logged_in'] = True
                return redirect(url_for('admin_index'))
            flash('Credenciales incorrectas.')
        return render_template('admin/login.html')

    @app.route('/admin/logout', methods=['POST'])
    @admin_required
    def admin_logout():
        session.pop('admin_logged_in', None)
        return redirect(url_for('index'))

    @app.route('/admin/')
    @admin_required
    def admin_index():
        rutas = Ruta.query.order_by(Ruta.creada_en.desc()).all()
        stats = {
            'total_rutas': Ruta.query.count(),
            'total_sesiones': Sesion.query.filter_by(estado='completada').count(),
            'total_usuarios': Usuario.query.count(),
        }
        return render_template('admin/index.html', rutas=rutas, stats=stats)

    @app.route('/admin/nueva', methods=['GET', 'POST'])
    @admin_required
    def admin_nueva_ruta():
        if request.method == 'POST':
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            dificultad = request.form.get('dificultad')
            distancia_km = request.form.get('distancia_km', type=float)
            desnivel_m = request.form.get('desnivel_m', type=int)

            ruta = Ruta(
                nombre=nombre,
                descripcion=descripcion,
                dificultad=dificultad,
                distancia_km=distancia_km,
                desnivel_m=desnivel_m,
            )
            db.session.add(ruta)
            db.session.flush()

            errors = []

            for campo, suffix in [('foto_inicio', 'inicio'), ('foto_fin', 'fin')]:
                foto = request.files.get(campo)
                if foto and foto.filename:
                    path = os.path.join(app.config['UPLOAD_FOLDER'], f'{ruta.id}_{suffix}.jpg')
                    foto.save(path)
                    gps = get_exif_gps(path)
                    if not gps:
                        errors.append(f'La foto de {suffix} no tiene datos GPS en EXIF.')
                        os.remove(path)
                    else:
                        if suffix == 'inicio':
                            ruta.lat_inicio, ruta.lon_inicio = gps
                            ruta.foto_inicio = f'{ruta.id}_{suffix}.jpg'
                        else:
                            ruta.lat_fin, ruta.lon_fin = gps
                            ruta.foto_fin = f'{ruta.id}_{suffix}.jpg'

            # Manual coordinate override
            for field, attr in [
                ('lat_inicio', 'lat_inicio'), ('lon_inicio', 'lon_inicio'),
                ('lat_fin', 'lat_fin'), ('lon_fin', 'lon_fin'),
            ]:
                val = request.form.get(field, type=float)
                if val is not None:
                    setattr(ruta, attr, val)

            if errors:
                db.session.rollback()
                for e in errors:
                    flash(e)
                return render_template('admin/nueva_ruta.html')

            db.session.commit()
            flash(f'Ruta "{nombre}" creada exitosamente.')
            return redirect(url_for('admin_index'))

        return render_template('admin/nueva_ruta.html')

    @app.route('/admin/ruta/<int:ruta_id>/qr')
    @admin_required
    def admin_qr(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        base_url = app.config['BASE_URL']

        def make_qr_b64(url):
            img = qrcode.make(url)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return base64.b64encode(buf.getvalue()).decode()

        qr_inicio = make_qr_b64(f'{base_url}/start/{ruta_id}')
        qr_fin = make_qr_b64(f'{base_url}/end/{ruta_id}')
        return render_template('admin/qr.html', ruta=ruta, qr_inicio=qr_inicio, qr_fin=qr_fin)

    @app.route('/admin/ruta/<int:ruta_id>/toggle', methods=['POST'])
    @admin_required
    def admin_toggle_ruta(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        ruta.activa = not ruta.activa
        db.session.commit()
        return redirect(url_for('admin_index'))

    @app.route('/admin/ruta/<int:ruta_id>/borrar', methods=['POST'])
    @admin_required
    def admin_borrar_ruta(ruta_id):
        ruta = db.get_or_404(Ruta, ruta_id)
        db.session.delete(ruta)
        db.session.commit()
        flash('Ruta eliminada.')
        return redirect(url_for('admin_index'))

    return app


app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(port=5006)
