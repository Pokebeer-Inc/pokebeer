/**
 * System of unified animated toast notifications for Pokebeer.
 * Supports Django messages, JS programmatic toasts, and real-time user notifications.
 */
(function () {
    'use strict';

    const TOAST_DURATION_MS = 4000;
    const POLL_INTERVAL_MS = 25000;

    function getToastContainer() {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'fixed top-4 left-1/2 -translate-x-1/2 z-[100] w-full max-w-md px-4 flex flex-col gap-2 pointer-events-none transition-all duration-300';
            document.body.appendChild(container);
        }
        return container;
    }

    function getTypeStyles(type, tierSlug = null) {
        // Application du design spécifique pour les trophées
        if (tierSlug) {
            switch (tierSlug) {
                case 'bronze': return { bgClass: 'bg-gradient-to-br from-[#CD7F32] to-[#8C5722] border-[#CD7F32]/50 text-white', icon: '' };
                case 'silver': return { bgClass: 'bg-gradient-to-br from-[#F8F8F8] to-[#C0C0C0] border-[#C0C0C0]/50 text-gray-900', icon: '' };
                case 'gold': return { bgClass: 'bg-gradient-to-br from-[#FFF080] to-[#FFD700] border-[#FFD700]/50 text-gray-900', icon: '' };
                case 'platinum': return { bgClass: 'bg-gradient-to-br from-[#FFFFFF] to-[#E5E4E2] border-[#E5E4E2]/50 text-gray-900', icon: '' };
            }
        }
        switch (type) {
            case 'success':
                return {
                    bgClass: 'bg-primary border-primary text-black font-bold',
                    icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>'
                };
            case 'error':
            case 'danger':
                return {
                    bgClass: 'bg-error border-error text-white',
                    icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>'
                };
            case 'warning':
                return {
                    bgClass: 'bg-warning border-warning text-black',
                    icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>'
                };
            case 'info':
            default:
                return {
                    bgClass: 'bg-base-200 border-base-300 text-gray-800',
                    icon: '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>'
                };
        }
    }

    /**
     * Display a floating animated toast message at top of page.
     * @param {Object} options
     * @param {string} options.message - Text or HTML content
     * @param {string} [options.type='info'] - 'success', 'error', 'warning', 'info'
     * @param {number} [options.duration=4000] - Duration in ms before auto-hiding
     * @param {string} [options.url] - Optional link URL when clicked
     * @param {boolean} [options.isHtml=false] - If true, innerHTML is rendered
     */
    function showToast(options) {
        if (!options || !options.message) return;

        const type = options.type || 'info';
        const duration = options.duration || TOAST_DURATION_MS;
        const styles = getTypeStyles(type, options.tierSlug);
        const container = getToastContainer();

        const finalBgClass = options.bgClass || styles.bgClass;
        const finalIcon = options.icon || styles.icon;

        const toast = document.createElement('div');
        toast.className = `pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 rounded-2xl shadow-xl border backdrop-blur-md transition-all duration-300 transform -translate-y-6 opacity-0 ${finalBgClass}`;

        const leftContent = document.createElement('div');
        leftContent.className = 'flex items-center gap-3 flex-1 min-w-0';

        const iconContainer = document.createElement('div');
        iconContainer.className = 'shrink-0 flex items-center justify-center w-6 h-6 [&>svg]:w-full [&>svg]:h-full';
        iconContainer.innerHTML = finalIcon;
        leftContent.appendChild(iconContainer);

        const textElement = options.url ? document.createElement('a') : document.createElement('div');
        textElement.className = `text-sm font-medium leading-snug truncate ${options.url ? 'hover:underline cursor-pointer' : ''}`;
        if (options.url) {
            textElement.href = options.url;
        }

        if (options.isHtml) {
            textElement.innerHTML = options.message;
        } else {
            textElement.textContent = options.message;
        }
        leftContent.appendChild(textElement);
        toast.appendChild(leftContent);

        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'shrink-0 btn btn-xs btn-circle btn-ghost text-white/80 hover:text-white hover:bg-white/20 border-0';
        closeBtn.innerHTML = '✕';
        closeBtn.ariaLabel = 'Fermer';

        const dismiss = () => {
            toast.classList.remove('translate-y-0', 'opacity-100');
            toast.classList.add('-translate-y-6', 'opacity-0');
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        };

        closeBtn.onclick = (e) => {
            e.stopPropagation();
            dismiss();
        };

        toast.appendChild(closeBtn);
        container.appendChild(toast);

        // Animate entrance
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                toast.classList.remove('-translate-y-6', 'opacity-0');
                toast.classList.add('translate-y-0', 'opacity-100');
            });
        });

        // Auto dismiss after duration
        if (duration > 0) {
            setTimeout(dismiss, duration);
        }

        return toast;
    }

    // Expose global function
    window.showToast = showToast;

    // Check for pre-rendered Django flash messages in hidden elements on DOM load
    document.addEventListener('DOMContentLoaded', function () {
        const djangoMessages = document.querySelectorAll('.django-flash-message');
        djangoMessages.forEach((el, index) => {
            const message = el.getAttribute('data-message');
            const type = el.getAttribute('data-type') || 'info';
            if (message) {
                setTimeout(() => {
                    showToast({ message: message, type: type });
                }, index * 200);
            }
            el.remove();
        });

        // Check for unread user notifications periodically if notification polling enabled
        const notifMeta = document.querySelector('meta[name="user-authenticated"]');
        if (notifMeta && notifMeta.content === 'true') {
            fetchMissedNotifications(); // Rattrape les notifs manquées à cause du rechargement
            initRealtimeWebSockets();   // Écoute le direct
        }
    });

    let seenNotificationIds = new Set(JSON.parse(sessionStorage.getItem('toast_seen_notifs') || '[]'));

    // Fonction pour récupérer les ratés au chargement
    function fetchMissedNotifications() {
        fetch('/api/notifications/unread/', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(res => res.ok ? res.json() : null)
        .then(data => {
            if (!data || !data.notifications) return;
            let hasNew = false;
            data.notifications.forEach(notif => {
                if (!seenNotificationIds.has(notif.id)) {
                    seenNotificationIds.add(notif.id);
                    hasNew = true;
                    showToast({
                        message: notif.message,
                        type: notif.toastType || 'info',
                        tierSlug: notif.tier_slug,
                        icon: notif.icon,
                        url: notif.read_url,
                        isHtml: true,
                        duration: 6000
                    });
                }
            });
            if (hasNew) {
                sessionStorage.setItem('toast_seen_notifs', JSON.stringify([...seenNotificationIds]));
            }
        }).catch(() => {});
    }

    // Fonction WebSocket pour le temps réel pur
    function initRealtimeWebSockets() {
        const supabaseUrl = document.querySelector('meta[name="supabase-url"]')?.content;
        const supabaseKey = document.querySelector('meta[name="supabase-anon-key"]')?.content;
        const userId = document.querySelector('meta[name="user-id"]')?.content;

        if (!supabaseUrl || !supabaseKey || !userId) return;

        const supabase = window.supabase.createClient(supabaseUrl, supabaseKey);
        const channel = supabase.channel(`room_user_${userId}`);

        channel.on('broadcast', { event: 'new_notification' }, (event) => {
            const notif = event.payload;

            showToast({
                message: notif.message,
                type: notif.toastType || 'info',
                tierSlug: notif.tier_slug,
                icon: notif.icon,
                url: notif.read_url,
                isHtml: true,
                duration: 6000
            });
            
            const indicators = document.querySelectorAll('.indicator-item');
            indicators.forEach(ind => ind.classList.remove('hidden'));

            // Si la page recharge à cause d'une soumission de formulaire, ce timer est détruit.
            // La notification ne sera donc pas marquée comme "vue" et apparaîtra sur la page suivante !
            setTimeout(() => {
                seenNotificationIds.add(notif.id);
                sessionStorage.setItem('toast_seen_notifs', JSON.stringify([...seenNotificationIds]));
            }, 2500);

        }).subscribe();
    }
})();
