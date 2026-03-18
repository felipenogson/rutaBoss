// RutaBoss main.js

// ── GPS utilities ──────────────────────────────────────────────────────────
function getGPS() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Geolocalización no disponible en este dispositivo.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      err => reject(new Error('No se pudo obtener tu ubicación: ' + err.message)),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  });
}

// ── Start screen ──────────────────────────────────────────────────────────
function initStartScreen(rutaId) {
  const btn = document.getElementById('btn-iniciar');
  const gpsStatus = document.getElementById('gps-status');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    gpsStatus.className = 'gps-status gps-waiting';
    gpsStatus.textContent = 'Obteniendo GPS…';

    try {
      const { lat, lon } = await getGPS();
      gpsStatus.textContent = `GPS obtenido: ${lat.toFixed(5)}, ${lon.toFixed(5)}`;

      const resp = await fetch(`/start/${rutaId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lon }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        gpsStatus.className = 'gps-status gps-fail';
        gpsStatus.textContent = data.error || 'Error al iniciar.';
        btn.disabled = false;
        return;
      }

      if (!data.gps_valido) {
        gpsStatus.className = 'gps-status gps-fail';
        gpsStatus.textContent = `Estás a ${data.distancia}m del punto de inicio. Máximo 10m.`;
        btn.disabled = false;
        return;
      }

      gpsStatus.className = 'gps-status gps-ok';
      gpsStatus.textContent = '¡GPS válido! Cronómetro iniciado.';

      // Start timer
      const startTime = Date.now();
      startLiveTimer(startTime);

    } catch (err) {
      gpsStatus.className = 'gps-status gps-fail';
      gpsStatus.textContent = err.message;
      btn.disabled = false;
    }
  });
}

// ── End screen ────────────────────────────────────────────────────────────
function initEndScreen(rutaId) {
  const btn = document.getElementById('btn-terminar');
  const gpsStatus = document.getElementById('gps-status');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    gpsStatus.className = 'gps-status gps-waiting';
    gpsStatus.textContent = 'Obteniendo GPS…';

    try {
      const { lat, lon } = await getGPS();
      const resp = await fetch(`/end/${rutaId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lon }),
      });
      const data = await resp.json();

      if (!resp.ok) {
        gpsStatus.className = 'gps-status gps-fail';
        gpsStatus.textContent = data.error || 'Error al terminar.';
        btn.disabled = false;
        return;
      }

      gpsStatus.className = 'gps-status gps-ok';
      gpsStatus.textContent = '¡Llegada registrada!';
      setTimeout(() => { window.location.href = data.redirect; }, 800);

    } catch (err) {
      gpsStatus.className = 'gps-status gps-fail';
      gpsStatus.textContent = err.message;
      btn.disabled = false;
    }
  });
}

// ── Live timer ────────────────────────────────────────────────────────────
function startLiveTimer(startMs) {
  const el = document.getElementById('live-timer');
  if (!el) return;
  function tick() {
    const elapsed = Math.floor((Date.now() - startMs) / 1000);
    const h = Math.floor(elapsed / 3600);
    const m = Math.floor((elapsed % 3600) / 60);
    const s = elapsed % 60;
    el.textContent = h
      ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
      : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    requestAnimationFrame(tick);
  }
  tick();
}

// ── Leaflet map ───────────────────────────────────────────────────────────
function initMap(latInicio, lonInicio, latFin, lonFin) {
  if (!window.L) return;
  const map = L.map('map');

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(map);

  const startIcon = L.divIcon({
    html: '<div style="background:#4de87a;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px #4de87a;"></div>',
    iconSize: [14, 14], iconAnchor: [7, 7],
  });
  const endIcon = L.divIcon({
    html: '<div style="background:#e84d6a;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px #e84d6a;"></div>',
    iconSize: [14, 14], iconAnchor: [7, 7],
  });

  L.marker([latInicio, lonInicio], { icon: startIcon }).addTo(map).bindPopup('Inicio');
  L.marker([latFin, lonFin], { icon: endIcon }).addTo(map).bindPopup('Fin');

  // Fit bounds
  const bounds = L.latLngBounds([[latInicio, lonInicio], [latFin, lonFin]]);
  map.fitBounds(bounds, { padding: [40, 40] });

  // Fetch OSRM route
  const url = `https://router.project-osrm.org/route/v1/cycling/${lonInicio},${latInicio};${lonFin},${latFin}?overview=full&geometries=geojson`;
  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.routes && data.routes[0]) {
        L.geoJSON(data.routes[0].geometry, {
          style: { color: '#4dd9e8', weight: 3, opacity: 0.85 }
        }).addTo(map);
      }
    })
    .catch(() => {
      // Draw straight line fallback
      L.polyline([[latInicio, lonInicio], [latFin, lonFin]], {
        color: '#4dd9e8', weight: 3, dashArray: '6 4'
      }).addTo(map);
    });
}

// ── Initials input uppercase ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const initialsInput = document.getElementById('initials-input');
  if (initialsInput) {
    initialsInput.addEventListener('input', () => {
      initialsInput.value = initialsInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    });
  }
});
