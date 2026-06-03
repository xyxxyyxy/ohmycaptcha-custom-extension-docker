(() => {

    let foundClientIds = new Set();

    function findRecaptchaWidgets() {
        if (window.___grecaptcha_cfg === undefined) return;
        if (___grecaptcha_cfg.clients === undefined) return;

        for (let clientId in ___grecaptcha_cfg.clients) {
            if (foundClientIds.has(clientId)) continue;

            let client = ___grecaptcha_cfg.clients[clientId];
            if (!client) continue;

            // Skip badge-only clients
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

            // Try to find the widget ID
            let widgetId = client.id;
            if (widgetId === undefined) {
                widgetId = clientId;
            }

            if (isCaptchaWidgetRegistered("recaptcha", widgetId)) {
                foundClientIds.add(clientId);
                continue;
            }

            let widgetInfo = extractWidgetInfo(client, widgetId, isBadge);
            if (widgetInfo) {
                foundClientIds.add(clientId);
                registerCaptchaWidget(widgetInfo);
            }
        }
    }

    function extractWidgetInfo(client, widgetId, isBadge) {
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
                    if (!n1) {
                        n1 = client[k];
                        continue;
                    }
                    if (client[k].isSameNode && client[k].isSameNode(n1)) {
                        client[k].id = "recaptcha-container-" + Date.now();
                        info.containerId = client[k].id;
                        break;
                    }
                }
            }
        }

        // Look for sitekey, action, s and callback
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

        // Prepare callback
        if (typeof info.callback === "function") {
            let callbackKey = "reCaptchaWidgetCallback" + widgetId;
            window[callbackKey] = info.callback;
            info.callback = callbackKey;
        }

        // Must have a sitekey or container to be valid
        if (!info.sitekey && !info.containerId) return null;

        return info;
    }

    // Wait for core helpers then start scanning
    let iter = 0;
    const checkReady = setInterval(() => {
        if (++iter > 200) { clearInterval(checkReady); }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            findRecaptchaWidgets();
            setInterval(findRecaptchaWidgets, 2000);
        }
    }, 50);

})()
