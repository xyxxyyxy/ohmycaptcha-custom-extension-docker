(() => {

    let foundWidgets = new Set();
    let nextWidgetId = 100;

    function findTurnstileWidgets() {
        // Method 1: Look for input with name cf-turnstile-response
        let inputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
        inputs.forEach(function(input) {
            let sitekey = input.getAttribute('data-sitekey') ||
                          input.closest('[data-sitekey]')?.getAttribute('data-sitekey');
            if (!sitekey) return;

            let inputId = input.id;
            if (!inputId) {
                inputId = "turnstile-input-" + sitekey;
                input.id = inputId;
            }

            if (foundWidgets.has(inputId)) return;
            if (isCaptchaWidgetRegistered("turnstile", inputId)) return;

            foundWidgets.add(inputId);

            registerCaptchaWidget({
                captchaType: "turnstile",
                widgetId: nextWidgetId++,
                sitekey: sitekey,
                inputId: inputId,
            });
        });

        // Method 2: Look for iframe with turnstile/challenges
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
            if (isCaptchaWidgetRegistered("turnstile", containerId)) return;

            foundWidgets.add(containerId);

            registerCaptchaWidget({
                captchaType: "turnstile",
                widgetId: nextWidgetId++,
                sitekey: sitekey,
                inputId: containerId,
            });
        });

        // Method 3: Look for elements with class cf-turnstile
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
            if (isCaptchaWidgetRegistered("turnstile", containerId)) return;

            foundWidgets.add(containerId);

            registerCaptchaWidget({
                captchaType: "turnstile",
                widgetId: nextWidgetId++,
                sitekey: sitekey,
                inputId: containerId,
            });
        });
    }

    // Wait for core helpers, then start scanning
    let iter = 0;
    const checkReady = setInterval(() => {
        if (++iter > 200) { clearInterval(checkReady); }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            findTurnstileWidgets();
            setInterval(findTurnstileWidgets, 2000);
        }
    }, 50);

})()
