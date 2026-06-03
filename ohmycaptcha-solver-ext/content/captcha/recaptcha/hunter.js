(function() {
    "use strict";

    const LOG = "[OMC:rcpt-hunter]";

    let foundClientIds = new Set();
    let foundDomIds = new Set();
    let nextWidgetId = 1000;
    let scanCount = 0;

    function findRecaptchaWidgets() {
        scanCount++;

        // Method 1: ___grecaptcha_cfg (original, most detailed)
        if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
            findViaGrecaptchaCfg();
        }

        // Method 2: DOM-based detection (fallback when grecaptcha loads before content script)
        findViaDOM();
    }

    // ── Method 1: Internal Google API ──
    function findViaGrecaptchaCfg() {
        let clients = ___grecaptcha_cfg.clients;
        let clientKeys = Object.keys(clients);

        for (let i = 0; i < clientKeys.length; i++) {
            let clientId = clientKeys[i];
            if (foundClientIds.has(clientId)) continue;

            let client = clients[clientId];
            if (!client) continue;

            let isBadge = false;
            mainLoop: for (let k1 in client) {
                if (typeof client[k1] !== "object") continue;
                for (let k2 in client[k1]) {
                    let el = client[k1][k2];
                    if (el && el.classList && el.classList.contains("grecaptcha-badge")) {
                        isBadge = true;
                        break mainLoop;
                    }
                }
            }

            let widgetId = client.id;
            if (widgetId === undefined) widgetId = clientId;

            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("recaptcha", widgetId)) {
                foundClientIds.add(clientId);
                continue;
            }

            let widgetInfo = extractFromClient(client, widgetId, isBadge);
            if (widgetInfo) {
                foundClientIds.add(clientId);
                if (typeof registerCaptchaWidget === 'function') {
                    registerCaptchaWidget(widgetInfo);
                    console.log(LOG, "Via ___grecaptcha_cfg:", widgetInfo.version, "id=" + widgetId);
                }
            }
        }
    }

    // ── Method 2: DOM-based detection ──
    function findViaDOM() {
        // Look for .g-recaptcha elements with data-sitekey
        let elements = document.querySelectorAll('.g-recaptcha[data-sitekey]');
        elements.forEach(function(el) {
            let containerId = el.id;
            if (!containerId) {
                containerId = "g-recaptcha-" + el.dataset.sitekey;
                el.id = containerId;
            }

            if (foundDomIds.has(containerId)) return;
            if (typeof isCaptchaWidgetRegistered === 'function' &&
                isCaptchaWidgetRegistered("recaptcha", containerId)) return;

            foundDomIds.add(containerId);

            // Determine version
            let version = "v2";
            if (el.dataset.size === "invisible") version = "v2_invisible";
            // Check if there's a badge nearby (v3 indicator)
            let badge = document.querySelector('.grecaptcha-badge');
            if (badge && !el.dataset.size) {
                // Could be v3 - but v3 typically doesn't have a visible checkbox
                // Keep as v2 for the checkbox case
            }

            if (typeof registerCaptchaWidget === 'function') {
                registerCaptchaWidget({
                    captchaType: "recaptcha",
                    widgetId: nextWidgetId++,
                    version: version,
                    sitekey: el.dataset.sitekey,
                    action: el.dataset.action || '',
                    containerId: containerId,
                    callback: el.dataset.callback || null,
                });
                console.log(LOG, "Via DOM .g-recaptcha:", version, "sitekey=" + el.dataset.sitekey);
            }
        });

        // Also look for invisible reCAPTCHA via badge
        let badge = document.querySelector('.grecaptcha-badge');
        if (badge && !badge.dataset.hunterScanned) {
            badge.dataset.hunterScanned = "true";
            // Try to find the associated sitekey from the page
            let scriptTags = document.querySelectorAll('script[src*="recaptcha/api.js"]');
            scriptTags.forEach(function(script) {
                let src = script.src;
                let match = src.match(/render=([^&]+)/);
                if (match) {
                    let sitekey = decodeURIComponent(match[1]);
                    let widgetId = "rcpt-badge-" + sitekey;
                    if (foundDomIds.has(widgetId)) return;
                    foundDomIds.add(widgetId);

                    if (typeof registerCaptchaWidget === 'function') {
                        registerCaptchaWidget({
                            captchaType: "recaptcha",
                            widgetId: nextWidgetId++,
                            version: "v3",
                            sitekey: sitekey,
                            action: '',
                            containerId: badge.id || "grecaptcha-badge",
                        });
                        console.log(LOG, "Via DOM badge (v3): sitekey=" + sitekey);
                    }
                }
            });
        }
    }

    function extractFromClient(client, widgetId, isBadge) {
        let info = {
            captchaType: "recaptcha",
            widgetId: widgetId,
            version: isBadge ? "v3" : "v2",
            sitekey: null,
            action: null,
            s: null,
            callback: null,
            enterprise: !!(window.grecaptcha && window.grecaptcha.enterprise),
            containerId: null,
            bindedButtonId: null,
        };

        // Check for invisible v2
        if (isBadge) {
            for (let k1 in client) {
                let obj = client[k1];
                if (typeof obj !== "object") continue;
                for (let k2 in obj) {
                    if (typeof obj[k2] === "string" && obj[k2] === "fullscreen") {
                        info.version = "v2_invisible";
                    }
                }
            }
        }

        // Look for containerId
        let n1;
        for (let k in client) {
            if (client[k] && client[k].nodeType) {
                if (client[k].id) {
                    info.containerId = client[k].id;
                } else if (client[k].dataset && client[k].dataset.sitekey) {
                    client[k].id = "recaptcha-container-" + Date.now();
                    info.containerId = client[k].id;
                } else if (info.version === 'v2') {
                    if (!n1) { n1 = client[k]; continue; }
                    if (client[k].isSameNode && client[k].isSameNode(n1)) {
                        client[k].id = "recaptcha-container-" + Date.now();
                        info.containerId = client[k].id;
                        break;
                    }
                }
            }
        }

        // Look for sitekey, action, s, callback
        for (let k1 in client) {
            let obj = client[k1];
            if (typeof obj !== "object") continue;
            for (let k2 in obj) {
                if (obj[k2] === null) continue;
                if (typeof obj[k2] !== "object") continue;
                if (obj[k2].sitekey === undefined) continue;
                for (let k3 in obj[k2]) {
                    if (k3 === "sitekey") info.sitekey = obj[k2][k3];
                    if (k3 === "action") info.action = obj[k2][k3];
                    if (k3 === "s") info.s = obj[k2][k3];
                    if (k3 === "callback") info.callback = obj[k2][k3];
                    if (k3 === "bind" && obj[k2][k3]) {
                        if (typeof obj[k2][k3] === "string") {
                            info.bindedButtonId = obj[k2][k3];
                        } else {
                            let button = obj[k2][k3];
                            if (button && button.id === undefined) {
                                button.id = "recaptchaBindedElement" + widgetId;
                            }
                            if (button) info.bindedButtonId = button.id;
                        }
                    }
                }
            }
        }

        if (typeof info.callback === "function") {
            let callbackKey = "reCaptchaWidgetCallback" + widgetId;
            window[callbackKey] = info.callback;
            info.callback = callbackKey;
        }

        return (info.sitekey || info.containerId) ? info : null;
    }

    // Wait for core helpers then start
    let iter = 0;
    const checkReady = setInterval(function() {
        if (++iter > 200) {
            clearInterval(checkReady);
            // Force start anyway - core helpers may already be ready
            console.log(LOG, "Starting scan loop (timeout).");
            findRecaptchaWidgets();
            setInterval(findRecaptchaWidgets, 2000);
            return;
        }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            console.log(LOG, "Ready. Starting reCAPTCHA scan loop (DOM + ___grecaptcha_cfg).");
            findRecaptchaWidgets();
            setInterval(findRecaptchaWidgets, 2000);
        }
    }, 50);

})();
