(function () {
    if (window.AppButtons && window.AppButtons.__initialized) return;

    function setButtonLoading(btn, loadingText) {
        if (!btn || btn.disabled) return;
        if (!btn.dataset.originalText) {
            btn.dataset.originalText = btn.innerHTML;
        }
        btn.classList.add('is-loading');
        btn.disabled = true;
        btn.setAttribute('aria-busy', 'true');
        btn.innerHTML = loadingText || '送信中...';
    }

    function resetButton(btn) {
        if (!btn) return;
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
        btn.classList.remove('is-loading');
        if (btn.dataset.originalText) {
            btn.innerHTML = btn.dataset.originalText;
        }
    }

    function bindFormGuard(selector = 'form') {
        document.querySelectorAll(selector).forEach(form => {
            form.addEventListener('submit', function (e) {
                const submitBtn = form.querySelector('button[type="submit"]');
                if (!submitBtn) return;
                if (submitBtn.disabled) {
                    e.preventDefault();
                    return;
                }
                const loadingText = submitBtn.dataset.loadingText || '送信中...';
                setButtonLoading(submitBtn, loadingText);
            });
        });
    }

    window.AppButtons = {
        setButtonLoading,
        resetButton,
        bindFormGuard,
        __initialized: true
    };
    window.setButtonLoading = setButtonLoading;
    window.resetButton = resetButton;

    document.addEventListener('DOMContentLoaded', () => bindFormGuard());
})();
