/* Login-page hero only. A single, restrained 3D scene -- a plate with a few orbiting
   ingredients -- auto-rotating in the brand palette. Skips itself (leaving the CSS
   gradient fallback visible) on reduced motion, small screens, or missing WebGL/Three. */
(function () {
    'use strict';
    var canvas = document.getElementById('hero-canvas');
    if (!canvas) return;

    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var tooSmall = window.innerWidth < 760;
    if (reduceMotion || tooSmall || typeof THREE === 'undefined') return;

    var ctx;
    try { ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl'); } catch (e) { ctx = null; }
    if (!ctx) return;

    var host = canvas.parentElement;
    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(0, 2.4, 6.2);
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xf3e9d2, 0.75));
    var key = new THREE.DirectionalLight(0xffe2bf, 1.1);
    key.position.set(4, 6, 4);
    scene.add(key);
    var rim = new THREE.DirectionalLight(0xc1572c, 0.4);
    rim.position.set(-5, 2, -3);
    scene.add(rim);

    var group = new THREE.Group();
    scene.add(group);

    var plate = new THREE.Mesh(
        new THREE.TorusGeometry(2.1, 0.22, 24, 64),
        new THREE.MeshStandardMaterial({ color: 0x475a3b, metalness: 0.15, roughness: 0.55 })
    );
    plate.rotation.x = Math.PI / 2;
    group.add(plate);

    var disc = new THREE.Mesh(
        new THREE.CylinderGeometry(1.75, 1.85, 0.14, 48),
        new THREE.MeshStandardMaterial({ color: 0xf6f1e6, roughness: 0.75 })
    );
    group.add(disc);

    var ingredientColors = [0xc1572c, 0xe3b94a, 0x6b7f54, 0x9c431f];
    var ingredients = [];
    for (var i = 0; i < 6; i++) {
        var geo = i % 2 === 0
            ? new THREE.IcosahedronGeometry(0.26, 0)
            : new THREE.SphereGeometry(0.22, 16, 16);
        var mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
            color: ingredientColors[i % ingredientColors.length], roughness: 0.4, metalness: 0.08
        }));
        var radius = 1.05 + (i % 3) * 0.28;
        var angle = (i / 6) * Math.PI * 2;
        mesh.position.set(Math.cos(angle) * radius, 0.3 + (i % 2) * 0.12, Math.sin(angle) * radius);
        mesh.userData = { angle: angle, radius: radius, speed: 0.15 + i * 0.015, bob: i };
        group.add(mesh);
        ingredients.push(mesh);
    }

    function resize() {
        var w = host.clientWidth, h = host.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }
    resize();
    window.addEventListener('resize', resize);

    var clock = new THREE.Clock();
    var frame;
    function tick() {
        var t = clock.getElapsedTime();
        group.rotation.y = t * 0.18;
        ingredients.forEach(function (m) {
            m.position.y = 0.3 + Math.sin(t * 0.8 + m.userData.bob) * 0.08;
        });
        renderer.render(scene, camera);
        frame = requestAnimationFrame(tick);
    }
    tick();

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) { cancelAnimationFrame(frame); } else { tick(); }
    });
})();
