/* Location picker: Places autocomplete search, "use my location", click or drag the pin.
   Used for the customer's delivery location and for a restaurant's own location.
   Markup contract: <form class="loc-picker" data-lat data-lon data-pin data-require>
     .lp-search (autocomplete goes here)  .lp-map  .lp-gps (button)  .lp-nomap (note)  .lp-error
     input[name=lat] input[name=lon] input[name=address] */
(function () {
    var roots = document.querySelectorAll('.loc-picker');
    if (!roots.length) return;

    function fallback(root, why) {
        ['.lp-map', '.lp-search', '.lp-gps'].forEach(function (sel) {
            var el = root.querySelector(sel); if (el) el.hidden = true;
        });
        var note = root.querySelector('.lp-nomap');
        if (note) {
            note.hidden = false;
            if (why === 'auth') note.textContent = 'Google Maps is unavailable. You can continue browsing menus in read-only mode.';
        }
    }

    function init(root, g) {
        var mapEl = root.querySelector('.lp-map');
        var latEl = root.querySelector('input[name=lat]');
        var lonEl = root.querySelector('input[name=lon]');
        var addrEl = root.querySelector('input[name=address]');
        var hasPoint = !!(root.dataset.lat && root.dataset.lon);
        var start = hasPoint ? { lat: +root.dataset.lat, lng: +root.dataset.lon } : { lat: 19.076, lng: 72.8777 };

        var map = new g.maps.Map(mapEl, {
            center: start, zoom: hasPoint ? 16 : 12, mapId: OFMaps.cfg.mapId,
            mapTypeControl: false, streetViewControl: false, fullscreenControl: false, gestureHandling: 'greedy'
        });
        var marker = new g.marker.AdvancedMarkerElement({
            map: map, position: start, gmpDraggable: true, title: 'Drag to fine-tune',
            content: OFMaps.pin(root.dataset.pin || 'home')
        });
        var geocoder = new g.geocoding.Geocoder();

        function set(pos, address, reverse) {
            var p = OFMaps.latLng(pos);
            marker.position = p;
            map.panTo(p);
            latEl.value = p.lat.toFixed(6);
            lonEl.value = p.lng.toFixed(6);
            if (address) { addrEl.value = address; }
            else if (reverse) {
                geocoder.geocode({ location: p }).then(function (res) {
                    if (res.results && res.results[0]) addrEl.value = res.results[0].formatted_address;
                }).catch(function () {});
            }
        }
        if (hasPoint) { latEl.value = root.dataset.lat; lonEl.value = root.dataset.lon; }

        marker.addListener('dragend', function () { set(marker.position, null, true); });
        map.addListener('click', function (ev) { set(ev.latLng, null, true); });

        // Places Autocomplete (new). Event name differs between Maps JS versions, so listen to both.
        var host = root.querySelector('.lp-search');
        if (host && g.places && g.places.PlaceAutocompleteElement) {
            var ac = new g.places.PlaceAutocompleteElement({});
            if (OFMaps.cfg.region) ac.includedRegionCodes = [OFMaps.cfg.region];
            host.appendChild(ac);
            var use = function (place) {
                place.fetchFields({ fields: ['formattedAddress', 'displayName', 'location'] }).then(function () {
                    if (!place.location) return;
                    map.setZoom(16);
                    set(place.location, place.formattedAddress || place.displayName, false);
                });
            };
            ac.addEventListener('gmp-select', function (ev) {
                var pred = ev.placePrediction;
                if (pred) use(pred.toPlace());
            });
            ac.addEventListener('gmp-placeselect', function (ev) { if (ev.place) use(ev.place); });
        }

        var gps = root.querySelector('.lp-gps');
        if (gps) {
            if (!navigator.geolocation) gps.hidden = true;
            gps.addEventListener('click', function () {
                gps.disabled = true;
                navigator.geolocation.getCurrentPosition(function (pos) {
                    gps.disabled = false;
                    map.setZoom(16);
                    set({ lat: pos.coords.latitude, lng: pos.coords.longitude }, null, true);
                }, function () {
                    gps.disabled = false;
                    var e = root.querySelector('.lp-error');
                    if (e) { e.hidden = false; e.textContent = 'Could not read your location. Search for an address or drop the pin instead.'; }
                }, { enableHighAccuracy: true, timeout: 10000 });
            });
        }
    }

    function guard(root) {                                       // customers must choose something
        if (root.dataset.require !== '1') return;
        root.addEventListener('submit', function (ev) {
            if (ev.submitter && ev.submitter.value === 'skip') return;
            var lat = root.querySelector('input[name=lat]').value;
            if (!lat) {
                ev.preventDefault();
                var e = root.querySelector('.lp-error');
                if (e) { e.hidden = false; e.textContent = 'Choose a location on the map, or continue browsing read-only.'; }
            }
        });
    }

    roots.forEach(guard);
    OFMaps.load().then(function (g) { roots.forEach(function (r) { init(r, g); }); })
        .catch(function (err) { roots.forEach(function (r) { fallback(r, err && err.message); }); });
    document.addEventListener('of-maps-auth-failed', function () { roots.forEach(function (r) { fallback(r, 'auth'); }); });
})();
