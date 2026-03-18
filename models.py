from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    foto_url = db.Column(db.String(300))
    proveedor = db.Column(db.String(20))  # google / facebook
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    sesiones = db.relationship('Sesion', backref='usuario', lazy=True)
    tiempos = db.relationship('Tiempo', backref='usuario', lazy=True)


class Ruta(db.Model):
    __tablename__ = 'rutas'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    dificultad = db.Column(db.String(20))  # facil / intermedio / dificil
    distancia_km = db.Column(db.Float)
    desnivel_m = db.Column(db.Integer)

    lat_inicio = db.Column(db.Float)
    lon_inicio = db.Column(db.Float)
    lat_fin = db.Column(db.Float)
    lon_fin = db.Column(db.Float)

    foto_inicio = db.Column(db.String(200))
    foto_fin = db.Column(db.String(200))

    activa = db.Column(db.Boolean, default=True)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)

    sesiones = db.relationship('Sesion', backref='ruta', lazy=True)
    tiempos = db.relationship('Tiempo', backref='ruta', lazy=True)


class Sesion(db.Model):
    __tablename__ = 'sesiones'

    id = db.Column(db.Integer, primary_key=True)
    ruta_id = db.Column(db.Integer, db.ForeignKey('rutas.id'), nullable=False)
    token = db.Column(db.String(36), unique=True, nullable=False)

    lat_inicio_real = db.Column(db.Float)
    lon_inicio_real = db.Column(db.Float)
    gps_valido = db.Column(db.Boolean, default=False)

    iniciada_en = db.Column(db.DateTime, default=datetime.utcnow)
    completada_en = db.Column(db.DateTime)
    tiempo_segundos = db.Column(db.Integer)

    estado = db.Column(db.String(20), default='iniciada')  # iniciada/completada/expirada/invalida

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    iniciales_anonimo = db.Column(db.String(3), nullable=True)


class Tiempo(db.Model):
    __tablename__ = 'tiempos'

    id = db.Column(db.Integer, primary_key=True)
    sesion_id = db.Column(db.Integer, db.ForeignKey('sesiones.id'), nullable=False)
    ruta_id = db.Column(db.Integer, db.ForeignKey('rutas.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    iniciales_anonimo = db.Column(db.String(3), nullable=True)

    tiempo_segundos = db.Column(db.Integer, nullable=False)
    gps_valido = db.Column(db.Boolean, default=False)
    registrado_en = db.Column(db.DateTime, default=datetime.utcnow)

    sesion = db.relationship('Sesion', backref='tiempo_registrado')
