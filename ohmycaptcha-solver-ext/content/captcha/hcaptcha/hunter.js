(function() {
    "use strict";

    const LOG = "[OMC:hcap-hunter]";
    console.log(LOG, "Loading hCaptcha hunter...");

    let foundContainers = new Set();
    let nextWidgetId = 1000;
    let scanCount = 0;

    function findHCaptchaWidgets() {
        scanCount++;
        let newFound = 0;

        // Method 1: Look for h-captcha-response textarea
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

            if (foundContainers.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            foundContainers.add(containerId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "hcaptcha",
                    widgetId: nextWidgetId++,
                    containerId: containerId,
                    sitekey: sitekey,
                    callback: container.dataset.callback || null,
                });
                console.log(LOG, "Method 1 (textarea): Found widget", containerId, "sitekey:", sitekey);
                newFound++;
            }
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

            if (foundContainers.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            foundContainers.add(containerId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "hcaptcha",
                    widgetId: nextWidgetId++,
                    containerId: containerId,
                    sitekey: sitekey,
                    callback: null,
                });
                console.log(LOG, "Method 2 (iframe): Found widget", containerId, "sitekey:", sitekey);
                newFound++;
            }
        });

        // Method 3: Look for elements with data-sitekey
        let candidates = document.querySelectorAll('[data-sitekey]');
        candidates.forEach(function(el) {
            // Skip reCAPTCHA widgets
            if (el.closest('.g-recaptcha, #recaptcha, .recaptcha')) return;

            let containerId = el.id;
            if (!containerId) {
                containerId = "hcaptcha-el-" + Date.now() + "-" + Math.random().toString(36).substr(2, 5);
                el.id = containerId;
            }

            if (foundContainers.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("hcaptcha", containerId)) return;

            let sitekey = el.dataset.sitekey;
            // Verify: must have hcaptcha iframe inside or nearby
            let hasHcaptcha = el.querySelector('iframe[src*="hcaptcha.com"]') !== null ||
                              el.closest('iframe[src*="hcaptcha.com"]') !== null;
            if (!hasHcaptcha) {
                // Check siblings
                let parent = el.parentElement;
                if (parent && parent.querySelector('iframe[src*="hcaptcha.com"]')) {
                    hasHcaptcha = true;
                }
            }
            if (!hasHcaptcha) return;

            foundContainers.add(containerId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "hcaptcha",
                    widgetId: nextWidgetId++,
                    containerId: containerId,
                    sitekey: sitekey,
                    callback: el.dataset.callback || null,
                });
                console.log(LOG, "Method 3 (data-sitekey): Found widget", containerId, "sitekey:", sitekey);
                newFound++;
            }
        });

        if (newFound > 0) {
            console.log(LOG, "Scan #" + scanCount + ": Found", newFound, "new hCaptcha widget(s)");
        } else if (scanCount <= 3) {
            console.log(LOG, "Scan #" + scanCount + ": No hCaptcha widgets found yet");
        }
    }

    // Wait for core helpers, then start scanning
    let iter = 0;
    const checkReady = setInterval(function() {
        if (++iter > 200) {
            clearInterval(checkReady);
            console.warn(LOG, "Timeout waiting for registerCaptchaWidget");
        }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            console.log(LOG, "Ready. Starting hCaptcha scan loop.");
            findHCaptchaWidgets();
            setInterval(findHCaptchaWidgets, 2000);
        }
    }, 50);

})();
