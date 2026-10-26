/* OrderFood accessibility tools: contrast, text size, text-to-speech, magnifier, voice input. */
var body = document.getElementById('main-body');
function store(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

/* High contrast and text size are remembered between pages */
function toggleContrast() {
    var on = body.classList.toggle('high-contrast');
    document.getElementById('contrast-btn').classList.toggle('active', on);
    store('of_contrast', on ? '1' : '0');
}
var textSize = parseInt(load('of_size') || '0', 10) || 0;
function applySize() { document.documentElement.style.fontSize = (100 + textSize * 12) + '%'; }
function changeTextSize(d) { textSize = Math.max(-1, Math.min(4, textSize + d)); applySize(); store('of_size', textSize); }
if (load('of_contrast') === '1') {
    body.classList.add('high-contrast');
    document.getElementById('contrast-btn').classList.add('active');
}
applySize();

/* Text to speech: start / pause / resume */
var utterance = null, reading = false;
function handleTTS() {
    var btn = document.getElementById('tts-btn');
    if (!('speechSynthesis' in window)) { btn.textContent = 'Speech not supported'; return; }
    if (reading) { window.speechSynthesis.pause(); reading = false; btn.textContent = 'Resume reading'; return; }
    if (window.speechSynthesis.paused) { window.speechSynthesis.resume(); reading = true; btn.textContent = 'Pause reading'; return; }
    var content = document.getElementById('content');
    utterance = new SpeechSynthesisUtterance(content.innerText);
    utterance.onend = function () { reading = false; btn.textContent = 'Read page aloud'; content.style.outline = 'none'; };
    utterance.onboundary = function () { content.style.outline = '3px solid #e8a317'; };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    reading = true;
    btn.textContent = 'Pause reading';
}
window.addEventListener('beforeunload', function () {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
});

/* Magnifier: shows the text under the pointer in large type */
var magOn = false, glass = document.getElementById('magnifier-glass');
function moveGlass(e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    var text = el ? (el.getAttribute('aria-label') || el.innerText || el.value || '') : '';
    text = text.trim().slice(0, 140);
    if (!text || el === glass) { glass.style.display = 'none'; return; }
    glass.textContent = text;
    glass.style.display = 'block';
    var x = Math.min(e.clientX + 18, window.innerWidth - glass.offsetWidth - 10);
    var y = Math.min(e.clientY + 18, window.innerHeight - glass.offsetHeight - 10);
    glass.style.left = Math.max(5, x) + 'px';
    glass.style.top = Math.max(5, y) + 'px';
}
function toggleMagnifier() {
    magOn = !magOn;
    document.getElementById('mag-btn').classList.toggle('active', magOn);
    if (magOn) { document.addEventListener('mousemove', moveGlass); }
    else { document.removeEventListener('mousemove', moveGlass); glass.style.display = 'none'; }
}

/* Speech to text: fills the text box that was focused last */
var lastField = null;
document.addEventListener('focusin', function (e) {
    if (e.target.matches('input[type=text], input[type=email], textarea')) lastField = e.target;
});
function startVoiceInput() {
    var btn = document.getElementById('stt-btn');
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { btn.textContent = 'Voice input not supported'; return; }
    if (!lastField) {
        btn.textContent = 'Click a text box first';
        setTimeout(function () { btn.textContent = 'Voice input'; }, 2000);
        return;
    }
    var rec = new SR();
    rec.lang = 'en-IN';
    btn.classList.add('active');
    btn.textContent = 'Listening...';
    rec.onresult = function (e) { lastField.value = (lastField.value + ' ' + e.results[0][0].transcript).trim(); };
    rec.onend = function () { btn.classList.remove('active'); btn.textContent = 'Voice input'; };
    rec.onerror = rec.onend;
    rec.start();
}
