(function() {
    "use strict";

    const LOG = "[OMC:turn-hunter]";
    console.log(LOG, "Loading Turnstile hunter...");

    let foundWidgets = new Set();
    let nextWidgetId = 1000;
    let scanCount = 0;

    function findTurnstileWidgets() {
        scanCount++;
        let newFound = 0;

        // Method 1: Look for input with name cf-turnstile-response
        let inputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
        inputs.forEach(function(input) {
            let sitekey = input.getAttribute('data-sitekey');
            if (!sitekey) {
                let parent = input.closest('[data-sitekey]');
                if (parent) sitekey = parent.getAttribute('data-sitekey');
            }
            if (!sitekey) return;

            let inputId = input.id;
            if (!inputId) {
                inputId = "turnstile-input-" + sitekey;
                input.id = inputId;
            }

            if (foundWidgets.has(inputId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("turnstile", inputId)) return;

            foundWidgets.add(inputId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "turnstile",
                    widgetId: nextWidgetId++,
                    sitekey: sitekey,
                    inputId: inputId,
                });
                console.log(LOG, "Method 1 (input): Found widget", inputId);
                newFound++;
            }
        });

        // Method 2: Look for Cloudflare challenge iframe
        let iframes = document.querySelectorAll('iframe[src*="challenges.cloudflare"], iframe[src*="turnstile"]');
        iframes.forEach(function(iframe) {
            let container = iframe.closest('.cf-turnstile, [data-sitekey]');
            if (!container) container = iframe.parentElement;
            if (!container) return;

            let sitekey = container.getAttribute('data-sitekey');
            if (!sitekey) return;

            let containerId = container.id;
            if (!containerId) {
                containerId = "turnstile-container-" + sitekey;
                container.id = containerId;
            }

            if (foundWidgets.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("turnstile", containerId)) return;

            foundWidgets.add(containerId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "turnstile",
                    widgetId: nextWidgetId++,
                    sitekey: sitekey,
                    inputId: containerId,
                });
                console.log(LOG, "Method 2 (iframe): Found widget", containerId);
                newFound++;
            }
        });

        // Method 3: Look for .cf-turnstile elements
        let cfEls = document.querySelectorAll('.cf-turnstile');
        cfEls.forEach(function(el) {
            let sitekey = el.getAttribute('data-sitekey');
            if (!sitekey) return;

            let containerId = el.id;
            if (!containerId) {
                containerId = "turnstile-cf-" + sitekey;
                el.id = containerId;
            }

            if (foundWidgets.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("turnstile", containerId)) return;

            foundWidgets.add(containerId);

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "turnstile",
                    widgetId: nextWidgetId++,
                    sitekey: sitekey,
                    inputId: containerId,
                });
                console.log(LOG, "Method 3 (.cf-turnstile): Found widget", containerId);
                newFound++;
            }
        });

        if (newFound > 0) {
            console.log(LOG, "Scan #" + scanCount + ": Found", newFound, "new Turnstile widget(s)");
        } else if (scanCount <= 3) {
            console.log(LOG, "Scan #" + scanCount + ": No Turnstile widgets found yet");
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
            console.log(LOG, "Ready. Starting Turnstile scan loop.");
            findTurnstileWidgets();
            setInterval(findTurnstileWidgets, 2000);
        }
    }, 50);

})();
