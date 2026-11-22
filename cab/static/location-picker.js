(() => {
  const picker = document.querySelector('#pin-picker');
  if (!picker || !window.L) return;
  picker.hidden = false;
  const form = picker.closest('form');
  const names = {pickup: 'Pickup', drop: 'Destination'};
  const places = JSON.parse(document.querySelector('#known-places').textContent);
  const status = document.querySelector('#pin-status');
  const markers = {};
  let active = 'pickup';

  const map = L.map('booking-map', {
    scrollWheelZoom: false,
    zoomControl: true,
    maxBounds: [[5, 67], [39, 99]],
    maxBoundsViscosity: 1,
    minZoom: 5
  }).setView([12.974, 77.594], 12);
  const tileMessage = document.querySelector('#tile-message');
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    referrerPolicy: 'strict-origin-when-cross-origin',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
  }).addTo(map);
  tiles.on('tileerror', () => { tileMessage.hidden = false; });
  tiles.on('load', () => {
    tileMessage.hidden = Boolean(picker.querySelector('.leaflet-tile-loaded'));
  });
  // Keep the crosshair at the viewport centre while the map pans beneath it.
  const crosshair = document.createElement('span');
  crosshair.className = 'pin-crosshair';
  crosshair.setAttribute('aria-hidden', 'true');
  map.getContainer().append(crosshair);

  function choose(key) {
    active = key;
    picker.querySelectorAll('[data-endpoint]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.endpoint === key));
    });
    status.textContent = 'Tap the map to set your ' + names[key].toLowerCase() + ', or pan and use the map centre.';
  }
  function showMarker(key, point) {
    if (markers[key]) {
      markers[key].setLatLng(point);
      return;
    }
    const marker = L.marker(point, {
      draggable: true,
      title: names[key],
      alt: names[key],
      icon: L.divIcon({className: 'trip-pin ' + key, html: key === 'pickup' ? 'P' : 'D', iconSize: [32,32], iconAnchor: [16,32]})
    }).addTo(map);
    marker.on('dragend', () => selectPoint(key, marker.getLatLng(), false));
    markers[key] = marker;
  }
  function selectPoint(key, point, advance = true) {
    if (point.lat < 6 || point.lat > 38 || point.lng < 68 || point.lng > 98) {
      status.textContent = 'Choose a point within the Indian service region.';
      syncMarkers(false);
      return;
    }
    form.elements[key].value = 'Map pin (' + point.lat.toFixed(5) + ', ' + point.lng.toFixed(5) + ')';
    showMarker(key, point);
    const other = key === 'pickup' ? 'drop' : 'pickup';
    if (advance && !form.elements[other].value) choose(other);
    else status.textContent = names[key] + ' selected. Drag its pin to adjust the location.';
  }
  function syncMarkers(frame) {
    const points = [];
    Object.keys(names).forEach(key => {
      const value = form.elements[key].value.trim();
      const pin = /^Map pin \((-?\d+\.\d+), (-?\d+\.\d+)\)$/.exec(value);
      const known = Object.hasOwn(places, value) && places[value];
      const point = known ? [known[1], known[0]] : pin && [+pin[1], +pin[2]];
      if (point) {
        showMarker(key, point);
        points.push(point);
      } else if (markers[key]) {
        markers[key].remove();
        delete markers[key];
      }
    });
    if (frame && points.length) map.fitBounds(points, {padding:[35,35], maxZoom:15});
  }
  picker.querySelectorAll('[data-endpoint]').forEach(button => {
    button.onclick = () => choose(button.dataset.endpoint);
  });
  map.on('click', event => selectPoint(active, event.latlng));
  document.querySelector('#pin-center').onclick = () => selectPoint(active, map.getCenter());
  picker.addEventListener('toggle', () => { if (picker.open) map.invalidateSize(); });
  for (const key of Object.keys(names)) {
    form.elements[key].addEventListener('focus', () => choose(key));
    form.elements[key].addEventListener('input', () => syncMarkers(false));
    form.elements[key].addEventListener('change', () => syncMarkers(true));
  }
  form.addEventListener('landmarks-changed', () => syncMarkers(true));
  window.addEventListener('pageshow', () => syncMarkers(true));
})();
