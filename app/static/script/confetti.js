// Pluie de confettis et d'étoiles aux couleurs de Pokebeer, sans bibliothèque ni requête réseau, partagée par les pages de félicitations
// (celebration.js) et le tirage du jour (daily_draw.js). Rien n'est animé si l'appareil demande moins de mouvement.
// Usage : Pokebeer.confetti.attach(canvas) puis .burst(x, y, nombre, ouverture) ou .party().
(function (Pokebeer) {
    const COLORS = ['#f1c40f', '#eca054', '#b87e44', '#cd1904', '#333333', '#f7f3f0'];
    const GRAVITY = 0.16;
    const SHAPES = ['rect', 'circle', 'star'];
    const reduced = () => Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    let canvas = null;
    let context = null;
    let particles = [];
    let frame = null;

    function resize() {
        if (!canvas) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.floor(window.innerWidth * ratio);
        canvas.height = Math.floor(window.innerHeight * ratio);
        context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    function attach(element) {
        if (canvas === element) return;
        canvas = element;
        context = canvas.getContext('2d');
        resize();
        window.addEventListener('resize', resize);
    }

    // `colors` : palette de la rafale (celle du site par défaut) ; la rareté d'une carte du tirage en impose une
    function burst(originX, originY, count, spread, colors = COLORS) {
        if (!canvas || reduced()) return;
        for (let index = 0; index < count; index += 1) {
            const angle = (-Math.PI / 2) + (Math.random() - 0.5) * spread;
            const speed = 6 + Math.random() * 9;
            particles.push({
                x: originX, y: originY, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
                size: 6 + Math.random() * 7, rotation: Math.random() * Math.PI * 2, spin: (Math.random() - 0.5) * 0.35,
                color: colors[Math.floor(Math.random() * colors.length)], shape: SHAPES[Math.floor(Math.random() * SHAPES.length)], life: 0,
            });
        }
        if (!frame) frame = requestAnimationFrame(tick);
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

    // Grande fête de la page de félicitations : trois rafales successives
    function party() {
        const width = window.innerWidth;
        const height = window.innerHeight;
        burst(width / 2, height * 0.55, 90, Math.PI * 0.9);
        setTimeout(() => { burst(width * 0.1, height * 0.8, 60, Math.PI * 0.5); burst(width * 0.9, height * 0.8, 60, Math.PI * 0.5); }, 350);
        setTimeout(() => burst(width / 2, height * 0.45, 70, Math.PI * 1.2), 900);
    }

    Pokebeer.confetti = { attach, burst, party, reduced };
})(window.Pokebeer = window.Pokebeer || {});
