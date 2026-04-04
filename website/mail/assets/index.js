(function() {
    'use strict';

    const body = document.body;
    const data = body ? body.dataset : {};
    const toBool = (val) => val === '1' || val === 'true' || val === true;

    // Contact section auto-focus
    const shouldFocusContact = toBool(data.focusContact);
    const isContactHash = window.location.hash === '#contact';
    if (shouldFocusContact || isContactHash) {
        const html = document.documentElement;
        const prevScrollBehavior = html.style.scrollBehavior;
        html.style.scrollBehavior = 'auto';
        const contactSection = document.getElementById('contact');
        if (contactSection) {
            contactSection.scrollIntoView({ block: 'start' });
        }
        html.style.scrollBehavior = prevScrollBehavior || '';
    }

    // Mobile menu toggle (used by nav button)
    window.toggleMenu = function() {
        const navLinks = document.getElementById('navLinks');
        if (navLinks) {
            navLinks.classList.toggle('active');
        }
    };

    // Back-to-top visibility
    const backToTop = document.getElementById('backToTop');
    if (backToTop) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 400) {
                backToTop.classList.add('visible');
            } else {
                backToTop.classList.remove('visible');
            }
        }, { passive: true });
    }

    // Promo countdown
    const promoEnd = data.promoEnd ? parseInt(data.promoEnd, 10) : NaN;
    if (toBool(data.promoActive) && !Number.isNaN(promoEnd)) {
        const updateCountdown = () => {
            const now = Date.now();
            const diff = promoEnd - now;
            if (diff <= 0) {
                const countdown = document.getElementById('countdown');
                if (countdown) countdown.innerHTML = '<span class="time-box">終了</span>';
                return;
            }
            const days = Math.floor(diff / (1000 * 60 * 60 * 24));
            const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const daysEl = document.getElementById('days');
            const hoursEl = document.getElementById('hours');
            const minsEl = document.getElementById('mins');
            if (daysEl) daysEl.textContent = days + '日';
            if (hoursEl) hoursEl.textContent = hours + '時間';
            if (minsEl) minsEl.textContent = mins + '分';
        };
        updateCountdown();
        setInterval(updateCountdown, 60000);
    }

    // Contact email reveal + copy
    if (toBool(data.contactEmailRevealed)) {
        const user = data.contactEmailUser || '';
        const domain = data.contactEmailDomain || '';
        const email = user && domain ? `${user}@${domain}` : '';
        if (email) {
            const span = document.querySelector('[data-user]');
            if (span) {
                span.textContent = email;
            }
            const mailto = document.getElementById('mailto-link');
            if (mailto) {
                mailto.href = 'mailto:' + email;
            }
            const mailForm = document.getElementById('contact-mailto-form');
            if (mailForm) {
                mailForm.action = 'mailto:' + email;
            }
            const copyBtn = document.getElementById('copy-email');
            if (copyBtn && typeof navigator.clipboard !== 'undefined') {
                copyBtn.addEventListener('click', () => {
                    if (copyBtn.disabled) return;
                    if (typeof setButtonLoading === 'function') {
                        setButtonLoading(copyBtn, copyBtn.dataset.loadingText || 'コピー中...');
                    }
                    navigator.clipboard.writeText(email).then(() => {
                        copyBtn.innerHTML = '✓ コピーしました';
                        setTimeout(() => typeof resetButton === 'function' && resetButton(copyBtn), 1800);
                    }).catch(() => {
                        copyBtn.textContent = 'コピー失敗';
                        setTimeout(() => typeof resetButton === 'function' && resetButton(copyBtn), 1500);
                    });
                });
            }
        }
    }

    // GA CTA click events
    document.querySelectorAll('.btn-primary, .btn-outline').forEach(btn => {
        btn.addEventListener('click', function() {
            if (typeof gtag !== 'undefined') {
                gtag('event', 'click', {
                    event_category: 'CTA',
                    event_label: this.textContent.trim()
                });
            }
        });
    });

    // Auto-close mobile menu on scroll
    window.addEventListener('scroll', () => {
        const navLinks = document.getElementById('navLinks');
        if (navLinks && navLinks.classList.contains('active')) {
            navLinks.classList.remove('active');
        }
    }, { passive: true });

    // Order form GA tracking
    const orderForm = document.getElementById('orderForm');
    if (orderForm) {
        const planKey = orderForm.dataset.planKey || '';
        orderForm.addEventListener('submit', () => {
            if (typeof gtag !== 'undefined' && planKey) {
                gtag('event', 'form_submit', {
                    event_category: 'Order',
                    event_label: planKey
                });
            }
        });
    }
})();
