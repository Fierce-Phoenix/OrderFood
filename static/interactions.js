/* OrderFood UI interactions: toasts, discovery filters, reveal-on-scroll, press feedback.
   Everything here is progressive enhancement -- every control still works as a plain form/link without it. */
(function () {
    'use strict';
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

<<<<<<< HEAD
    /* Flash messages become auto-dismissing toasts. */
    function wireFlashes() {
        var stack = document.querySelector('.flash-stack');
        if (!stack) return;
        stack.querySelectorAll('.flash').forEach(function (el) {
=======
    /* Flash messages become auto-dismissing toasts with an icon per category. */
    function wireFlashes() {
        var stack = document.querySelector('.flash-stack');
        if (!stack) return;
        var icons = { success: 'icon-check', error: 'icon-alert', warning: 'icon-warn' };
        stack.querySelectorAll('.flash').forEach(function (el) {
            var kind = (el.className.match(/flash-(\w+)/) || [])[1] || 'success';
            if (!el.querySelector('svg')) {
                var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.setAttribute('aria-hidden', 'true');
                var use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
                use.setAttribute('href', '#' + (icons[kind] || 'icon-check'));
                svg.appendChild(use);
                el.insertBefore(svg, el.firstChild);
            }
>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
            if (reduceMotion) return;
            setTimeout(function () {
                el.classList.add('leaving');
                el.addEventListener('animationend', function () { el.remove(); }, { once: true });
            }, 5000);
        });
    }

    /* Small "press" feedback on buttons that submit a form -- the page may navigate away
       immediately after, but the user sees their tap registered. */
    function wireButtonPress() {
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('button.btn, a.btn');
            if (!btn || btn.disabled) return;
            btn.classList.add('is-pressed');
            setTimeout(function () { btn.classList.remove('is-pressed'); }, 150);
        });
    }

    /* Reveal-on-scroll for elements marked .reveal (cards, sections). No-op if IO unsupported. */
    function wireReveal() {
        var items = document.querySelectorAll('.reveal');
        if (!items.length) return;
        if (reduceMotion || !('IntersectionObserver' in window)) {
            items.forEach(function (el) { el.classList.add('in-view'); });
            return;
        }
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) { entry.target.classList.add('in-view'); io.unobserve(entry.target); }
            });
        }, { threshold: .08 });
        items.forEach(function (el) { io.observe(el); });
    }

    /* Discovery page: client-side filter chips + sort, over the server-rendered restaurant grid.
       All the data (rating, minutes, open state, cuisine) is already in the markup -- no extra request. */
    function wireDiscovery() {
        var grid = document.querySelector('[data-discovery]');
        if (!grid) return;
        var cards = Array.prototype.slice.call(grid.querySelectorAll('.r-card'));
        var chips = document.querySelectorAll('.chip[data-cuisine]');
        var openChip = document.querySelector('.chip[data-open-only]');
        var sortSelect = document.querySelector('.sort-select');
        var emptyMsg = document.querySelector('[data-discovery-empty]');
        var activeCuisine = 'all', openOnly = false;

        function apply() {
            var visible = 0;
            cards.forEach(function (card) {
                var cuisine = card.getAttribute('data-cuisine');
                var open = card.getAttribute('data-open') === '1';
                var show = (activeCuisine === 'all' || cuisine === activeCuisine) && (!openOnly || open);
                card.style.display = show ? '' : 'none';
                if (show) visible++;
            });
            if (sortSelect) {
                var key = sortSelect.value;
                var sorted = cards.slice().sort(function (a, b) {
                    if (key === 'time') return parseFloat(a.dataset.minutes) - parseFloat(b.dataset.minutes);
                    if (key === 'rating') return parseFloat(b.dataset.rating) - parseFloat(a.dataset.rating);
                    return parseInt(a.dataset.order, 10) - parseInt(b.dataset.order, 10);
                });
                sorted.forEach(function (card) { grid.appendChild(card); });
            }
            if (emptyMsg) emptyMsg.hidden = visible !== 0;
        }

        chips.forEach(function (chip) {
            chip.addEventListener('click', function () {
                chips.forEach(function (c) { c.setAttribute('aria-pressed', 'false'); });
                chip.setAttribute('aria-pressed', 'true');
                activeCuisine = chip.getAttribute('data-cuisine');
                apply();
            });
        });
        if (openChip) {
            openChip.addEventListener('click', function () {
                openOnly = !openOnly;
                openChip.setAttribute('aria-pressed', String(openOnly));
                apply();
            });
        }
        if (sortSelect) sortSelect.addEventListener('change', apply);
        apply();
    }

    /* Restaurant menu page: highlight the category you're scrolled to in the sticky sub-nav. */
    function wireCategoryScrollspy() {
        var nav = document.querySelector('.category-nav');
        if (!nav) return;
        var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
        var sections = links.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); });
        if (!('IntersectionObserver' in window)) return;
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                var idx = sections.indexOf(entry.target);
                if (idx === -1) return;
                links.forEach(function (l) { l.classList.remove('active'); });
                links[idx].classList.add('active');
            });
        }, { rootMargin: '-45% 0px -50% 0px' });
        sections.filter(Boolean).forEach(function (s) { io.observe(s); });
    }

    /* Image fallback: if a curated photo fails to load (offline demo), reveal the tone/icon tile behind it. */
    window.ofImgFallback = function (img) {
        img.style.display = 'none';
        var tone = img.parentElement.querySelector('.tone');
        if (tone) tone.style.display = 'flex';
    };

<<<<<<< HEAD
=======
    /* Login: fills the email/password fields from a demo-account button, nothing else. */
    window.ofFillDemo = function (email, password) {
        var form = document.querySelector('.auth-card form');
        if (!form) return;
        form.email.value = email;
        form.password.value = password;
        form.email.focus();
    };

>>>>>>> 718eed4856796a17f73eb0b6274bd9d7b38df7f5
    document.addEventListener('DOMContentLoaded', function () {
        wireFlashes();
        wireButtonPress();
        wireReveal();
        wireDiscovery();
        wireCategoryScrollspy();
    });
})();
