// Pluie de confettis et d'étoiles aux couleurs de Pokebeer, sans bibliothèque ni requête réseau.
// Rien n'est animé si l'appareil demande moins de mouvement (la page garde ses décorations fixes).
(function () {
    // L'adresse garde le « #step-6 » de l'assistant après la redirection : on l'enlève
    if (location.hash.indexOf('#step-') === 0) history.replaceState(null, '', location.pathname + location.search);
    const canvas = document.getElementById('confetti');
    if (!canvas) return;
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const context = canvas.getContext('2d');
    const COLORS = ['#f1c40f', '#eca054', '#b87e44', '#cd1904', '#333333', '#f7f3f0'];
    const GRAVITY = 0.16;
    let particles = [];
    let frame = null;

    function resize() {
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(window.innerWidth * ratio);
        canvas.height = Math.floor(window.innerHeight * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function burst(originX, originY, count, spread) {
        for (let index = 0; index < count; index += 1) {
            const angle = (-Math.PI / 2) + (Math.random() - 0.5) * spread;
            const speed = 6 + Math.random() * 9;
            particles.push({
                x: originX, y: originY, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
                size: 6 + Math.random() * 7, rotation: Math.random() * Math.PI * 2, spin: (Math.random() - 0.5) * 0.35,
                color: COLORS[Math.floor(Math.random() * COLORS.length)], shape: ['rect', 'circle', 'star'][Math.floor(Math.random() * 3)], life: 0,
            });
        }
    }

    function drawStar(size) {
        context.beginPath();
        for (let point = 0; point < 10; point += 1) {
            const radius = point % 2 === 0 ? size : size / 2.3;
            const angle = (Math.PI / 5) * point - Math.PI / 2;
            context.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
        }
        context.closePath();
        context.fill();
    }

    function tick() {
        context.clearRect(0, 0, window.innerWidth, window.innerHeight);
        particles = particles.filter(p => p.y < window.innerHeight + 40 && p.life < 260);
        particles.forEach(p => {
            p.life += 1;
            p.vy += GRAVITY;
            p.vx *= 0.99;
            p.x += p.vx;
            p.y += p.vy;
            p.rotation += p.spin;
            context.save();
            context.translate(p.x, p.y);
            context.rotate(p.rotation);
            context.globalAlpha = Math.max(0, 1 - p.life / 260);
            context.fillStyle = p.color;
            if (p.shape === 'rect') context.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
            else if (p.shape === 'circle') { context.beginPath(); context.arc(0, 0, p.size / 2.4, 0, Math.PI * 2); context.fill(); }
            else drawStar(p.size / 1.6);
            context.restore();
        });
        frame = particles.length ? requestAnimationFrame(tick) : null;
    }

    function party() {
        if (reduced) return;
        resize();
        const width = window.innerWidth;
        const height = window.innerHeight;
        burst(width / 2, height * 0.55, 90, Math.PI * 0.9);
        setTimeout(() => { burst(width * 0.1, height * 0.8, 60, Math.PI * 0.5); burst(width * 0.9, height * 0.8, 60, Math.PI * 0.5); }, 350);
        setTimeout(() => burst(width / 2, height * 0.45, 70, Math.PI * 1.2), 900);
        if (!frame) frame = requestAnimationFrame(tick);
    }

    window.addEventListener('resize', resize);
    const again = document.getElementById('celebrate-again');
    if (again) again.addEventListener('click', party);
    party();
})();
