"""Google Maps Platform integration for OrderFood.

Plug and play: copy `.env.example` to `.env`, paste your key, run the app. Nothing else to install
(this module only uses the Python standard library).

APIs used (enable them in Google Cloud Console for your key):
  * Maps JavaScript API   - maps, markers, live tracking          (browser)
  * Places API (New)      - address search / autocomplete          (browser)
  * Geocoding API         - reverse-geocode a dropped pin          (browser + one-off seeding)
  * Routes API            - travel time/distance + route polyline  (server)

Without a key the app still works in read-only browsing mode. Travel times fall back to a
straight-line estimate when coordinates are available. Nothing here ever raises into a request.
"""

import json
import math
import os
import random
import threading
import time
import urllib.error
import urllib.request

ROUTES_BASE = 'https://routes.googleapis.com'
GEOCODE_URL = 'https://maps.googleapis.com/maps/api/geocode/json'

ETA_TTL = 600            # seconds a restaurant->customer estimate is reused
ROAD_FACTOR = 1.35       # straight-line -> road distance, for the offline fallback
FALLBACK_KMH = 22.0      # average urban speed, for the offline fallback

def load_dotenv(path):
    """Tiny .env reader (KEY=VALUE per line). Real environment variables win."""
    try:
        with open(path, encoding='utf-8') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)
    except OSError:
        pass


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def estimate_leg(a, b):
    """Offline stand-in for a real route: straight line x road factor at city speed."""
    km = haversine_km(a, b) * ROAD_FACTOR
    return {'km': round(km, 1), 'minutes': km / FALLBACK_KMH * 60.0, 'path': [list(a), list(b)],
            'source': 'estimate'}


def decode_polyline(encoded):
    """Decode a Google encoded polyline, rejecting truncated or malformed input."""
    if not isinstance(encoded, str):
        raise ValueError('Encoded polyline must be a string.')

    points, i, lat, lon = [], 0, 0, 0
    while i < len(encoded):
        coordinates = []
        for _axis in (0, 1):
            shift = result = 0
            while True:
                if i >= len(encoded):
                    raise ValueError('Encoded polyline ended mid-coordinate.')
                byte = ord(encoded[i]) - 63
                i += 1
                if byte < 0 or byte > 63:
                    raise ValueError('Encoded polyline contains an invalid character.')
                result |= (byte & 0x1F) << shift
                shift += 5
                if shift > 35:
                    raise ValueError('Encoded polyline coordinate is too large.')
                if byte < 0x20:
                    break
            coordinates.append(~(result >> 1) if result & 1 else result >> 1)
        lat += coordinates[0]
        lon += coordinates[1]
        points.append([lat / 1e5, lon / 1e5])
    return points


def valid_point(lat, lon):
    """Parse and range-check coordinates; returns (lat, lon) floats or None."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon


class MapsError(Exception):
    pass


class GoogleMapsService:
    def __init__(self):
        self.browser_key = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()
        # A browser key restricted by HTTP referrer cannot call web services from the server.
        # Put an unrestricted/IP-restricted key in GOOGLE_MAPS_SERVER_KEY if you lock the browser key down.
        self.server_key = os.environ.get('GOOGLE_MAPS_SERVER_KEY', '').strip() or self.browser_key
        self.map_id = os.environ.get('GOOGLE_MAPS_MAP_ID', '').strip() or 'DEMO_MAP_ID'
        self.region = os.environ.get('GOOGLE_MAPS_REGION', '').strip().lower()
        self.travel_mode = os.environ.get('GOOGLE_TRAVEL_MODE', 'DRIVE').strip().upper()   # or TWO_WHEELER
        self.offline = os.environ.get('ORDERFOOD_MAPS_OFFLINE') == '1'
        self.last_error = None
        self._cache = {}
        self._lock = threading.Lock()
        self._geocode_broken = False

    # ---- status ----------------------------------------------------------------------------
    @property
    def enabled(self):
        return bool(self.server_key) and not self.offline

    def browser_config(self):
        """What the page JavaScript may know. The browser key is public by nature: restrict it."""
        return {'key': '' if self.offline else self.browser_key, 'mapId': self.map_id, 'region': self.region}

    # ---- HTTP ------------------------------------------------------------------------------
    def _call(self, url, payload=None, headers=None):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            try:
                msg = json.loads(exc.read().decode()).get('error', {}).get('message', '')
            except Exception:
                msg = ''
            raise MapsError(f'HTTP {exc.code}: {msg or exc.reason}')
        except Exception as exc:                                  # timeout, DNS, bad JSON ...
            raise MapsError(str(exc))

    def _routes_headers(self, field_mask):
        return {'X-Goog-Api-Key': self.server_key, 'X-Goog-FieldMask': field_mask}

    @staticmethod
    def _waypoint(p):
        return {'location': {'latLng': {'latitude': p[0], 'longitude': p[1]}}}

    @staticmethod
    def _key(p):
        return (round(p[0], 4), round(p[1], 4))

    def _cache_get(self, key, ttl):
        hit = self._cache.get(key)
        return hit[1] if hit and time.time() - hit[0] < ttl else None

    def _cache_put(self, key, value):
        with self._lock:
            if len(self._cache) > 3000:
                self._cache.clear()
            self._cache[key] = (time.time(), value)

    # ---- travel time: many restaurants -> one customer -------------------------------------
    def deliveries_eta(self, origins, dest):
        """origins: {id: (lat, lon)} (restaurants). dest: (lat, lon) (customer).
        Returns {id: {'km', 'minutes' (travel only), 'source': 'google'|'estimate'}}.
        One Routes API call covers every uncached restaurant."""
        out, missing = {}, {}
        for rid, o in origins.items():
            cached = self._cache_get(('m', self._key(o), self._key(dest)), ETA_TTL)
            if cached:
                out[rid] = cached
            else:
                missing[rid] = o
        if missing:
            fresh = {}
            if self.enabled:
                try:
                    fresh = self._matrix(missing, dest)
                    self.last_error = None
                except MapsError as exc:
                    self.last_error = str(exc)
            for rid, o in missing.items():
                result = fresh.get(rid) or estimate_leg(o, dest)
                out[rid] = {k: result[k] for k in ('km', 'minutes', 'source')}
                if result['source'] == 'google':                # never cache fallback numbers
                    self._cache_put(('m', self._key(o), self._key(dest)), out[rid])
        return out

    def _matrix(self, missing, dest):
        ids = list(missing)
        results = {}
        for start in range(0, len(ids), 100):                    # API limit is 625 elements per call
            chunk = ids[start:start + 100]
            body = {'origins': [{'waypoint': self._waypoint(missing[i])} for i in chunk],
                    'destinations': [{'waypoint': self._waypoint(dest)}],
                    'travelMode': self.travel_mode}
            rows = self._call(f'{ROUTES_BASE}/distanceMatrix/v2:computeRouteMatrix', body, self._routes_headers(
                'originIndex,destinationIndex,duration,distanceMeters,status,condition'))
            for el in rows if isinstance(rows, list) else []:
                if not isinstance(el, dict) or el.get('status') or el.get('condition') != 'ROUTE_EXISTS':
                    continue                                     # no route / error -> estimate for that one
                try:
                    origin_index = int(el['originIndex'])
                    distance_m = float(el['distanceMeters'])
                    duration_seconds = float(str(el['duration']).rstrip('s'))
                except (KeyError, TypeError, ValueError):
                    continue                                     # malformed element -> estimate for that one
                if (origin_index < 0 or origin_index >= len(chunk) or
                        not math.isfinite(distance_m) or distance_m < 0 or
                        not math.isfinite(duration_seconds) or duration_seconds < 0):
                    continue
                results[chunk[origin_index]] = {
                    'km': round(distance_m / 1000, 1),
                    'minutes': duration_seconds / 60.0, 'source': 'google'}
        return results

    # ---- one route (ETA + path for the map) ------------------------------------------------
    def route(self, origin, dest, with_path=False, ttl=30):
        """{'km', 'minutes', 'path': [[lat, lon], ...] | None, 'source'}. Never raises."""
        key = ('r', self._key(origin), self._key(dest), with_path)
        cached = self._cache_get(key, ttl)
        if cached:
            return cached
        result = None
        if self.enabled:
            mask = 'routes.duration,routes.distanceMeters' + (',routes.polyline.encodedPolyline' if with_path else '')
            body = {'origin': self._waypoint(origin), 'destination': self._waypoint(dest),
                    'travelMode': self.travel_mode, 'polylineQuality': 'OVERVIEW'}
            try:
                data = self._call(f'{ROUTES_BASE}/directions/v2:computeRoutes', body, self._routes_headers(mask))
                r = data['routes'][0]
                result = {'km': round(r.get('distanceMeters', 0) / 1000, 1),
                          'minutes': float(str(r['duration']).rstrip('s')) / 60.0, 'source': 'google',
                          'path': decode_polyline(r['polyline']['encodedPolyline']) if with_path else None}
                self.last_error = None
            except (MapsError, KeyError, IndexError, TypeError, ValueError) as exc:
                self.last_error = str(exc)
        if result is None:
            result = estimate_leg(origin, dest)
            if not with_path:
                result['path'] = None
            return result                                        # fallback is cheap: don't cache it
        self._cache_put(key, result)
        return result

    # ---- seeding helpers -------------------------------------------------------------------
    @staticmethod
    def random_spot(rng=None):
        """A plausible point for demo data: (label, lat, lon)."""
        rng = rng or random
        lat, lon = 19.076, 72.8777
        return 'Mumbai', round(lat + rng.uniform(-0.025, 0.025), 6), round(lon + rng.uniform(-0.025, 0.025), 6)

    def reverse_geocode(self, lat, lon):
        """Best-effort pretty address for a seeded point. Gives up after the first failure."""
        if not self.enabled or self._geocode_broken:
            return None
        try:
            data = self._call(f'{GEOCODE_URL}?latlng={lat},{lon}&key={self.server_key}')
            if data.get('status') == 'OK' and data.get('results'):
                return data['results'][0]['formatted_address'][:200]
            raise MapsError(data.get('error_message') or data.get('status', 'no result'))
        except MapsError as exc:
            self._geocode_broken = True
            self.last_error = str(exc)
            return None

    @staticmethod
    def maps_url(lat, lon):
        return f'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

    @staticmethod
    def directions_url(origin, dest):
        o = f'&origin={origin[0]},{origin[1]}' if origin else ''
        return f'https://www.google.com/maps/dir/?api=1{o}&destination={dest[0]},{dest[1]}&travelmode=driving'
