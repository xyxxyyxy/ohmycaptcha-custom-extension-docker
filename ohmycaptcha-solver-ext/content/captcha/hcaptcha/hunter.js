(() => {

    let foundWidgets = new Set();
    let nextWidgetId = 100; // Start high to avoid collision with interceptor

    function findHCaptchaWidgets() {
        // Method 1: Look for h-capcha-response textarea
        let textareas = document.querySelectorAll('textarea[name="h-captcha-response"]');
        textareas.forEach(function(textarea) {
            let container = textarea.closest('.h-captcha, [data-sitekey], .hcaptcha');
            if (!container) container = textarea.parentElement;
            if (!container) return;

            let sitekey = container.dataset.sitekey || container.getAttribute('data-sitekey');
            let containerId = container.id;
            if (!containerId) {
                containerId = "hcaptcha-container-" + Date.now() + "-" + Math.random().toString(36).substr(2, 5);
                container.id = containerId;
            }

            // Skip if already registered
            if (foundWidgets.has(containerId)) return;
            if (isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            foundWidgets.add(containerId);

            registerCaptchaWidget({
                captchaType: "hcaptcha",
                widgetId: nextWidgetId++,
                containerId: containerId,
                sitekey: sitekey,
                callback: container.dataset.callback || null,
            });
        });

        // Method 2: Look for iframe with hcaptcha.com
        let iframes = document.querySelectorAll('iframe[src*="hcaptcha.com"]');
        iframes.forEach(function(iframe) {
            let container = iframe.closest('.h-captcha, [data-sitekey], .hcaptcha');
            if (!container) container = iframe.parentElement;
            if (!container) return;

            let sitekey = container.dataset.sitekey;
            let containerId = container.id;
            if (!containerId) {
                containerId = "hcaptcha-iframe-" + Date.now() + "-" + Math.random().toString(36).substr(2, 5);
                container.id = containerId;
            }

            if (foundWidgets.has(containerId)) return;
            if (isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            foundWidgets.add(containerId);

            registerCaptchaWidget({
                captchaType: "hcaptcha",
                widgetId: nextWidgetId++,
                containerId: containerId,
                sitekey: sitekey,
                callback: null,
            });
        });

        // Method 3: Look for elements with data-sitekey that look like hCaptcha
        let candidates = document.querySelectorAll('[data-sitekey]');
        candidates.forEach(function(el) {
            // Skip if inside a reCAPTCHA widget
            if (el.closest('.g-recaptcha, .recaptcha')) return;

            let containerId = el.id;
            if (!containerId) {
                containerId = "hcaptcha-el-" + Date.now() + "-" + Math.random().toString(36).substr(2, 5);
                el.id = containerId;
            }

            if (foundWidgets.has(containerId)) return;
            if (isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            // Must have an iframe from hcaptcha.com to be sure
            let hcaptchaIframe = el.querySelector('iframe[src*="hcaptcha.com"]');
            if (!hcaptchaIframe && !el.closest('iframe[src*="hcaptcha.com"]')) return;

            foundWidgets.add(containerId);

            registerCaptchaWidget({
                captchaType: "hcaptcha",
                widgetId: nextWidgetId++,
                containerId: containerId,
                sitekey: el.dataset.sitekey,
                callback: el.dataset.callback || null,
            });
        });
    }

    // Wait for core helpers, then start scanning
    let iter = 0;
    const checkReady = setInterval(() => {
        if (++iter > 200) { clearInterval(checkReady); }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            findHCaptchaWidgets();
            setInterval(findHCaptchaWidgets, 2000);
        }
    }, 50);

})()
