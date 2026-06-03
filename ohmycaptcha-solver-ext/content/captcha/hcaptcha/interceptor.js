(function() {
    "use strict";

    const LOG = "[OMC:hcap-interceptor]";
    console.log(LOG, "Loading hCaptcha interceptor...");

    let hCaptchaInstance = undefined;
    let interceptorReady = false;
    let nextWidgetId = 0;

    function setupInterceptor() {
        if (interceptorReady) {
            console.log(LOG, "Interceptor already set up");
            return;
        }

        console.log(LOG, "Setting up hcaptcha property interceptor...");
        interceptorReady = true;

        try {
            Object.defineProperty(window, "hcaptcha", {
                configurable: true,
                get: function () {
                    return hCaptchaInstance;
                },
                set: function (e) {
                    console.log(LOG, "hcaptcha SET fired");
                    hCaptchaInstance = e;
                    try {
                        patchHCaptcha(e);
                    } catch (err) {
                        console.error(LOG, "Error in hcaptcha setter:", err);
                    }
                },
            });
            console.log(LOG, "Property descriptor installed on window.hcaptcha");
        } catch (err) {
            console.error(LOG, "Failed to install property interceptor:", err);
            return;
        }

        // If hcaptcha already exists
        if (typeof window.hcaptcha !== 'undefined' && window.hcaptcha !== hCaptchaInstance) {
            console.log(LOG, "hcaptcha already exists! Patching immediately...");
            hCaptchaInstance = window.hcaptcha;
            patchHCaptcha(window.hcaptcha);
        } else {
            console.log(LOG, "hcaptcha not yet present. Waiting...");
        }
    }

    function patchHCaptcha(obj) {
        if (!obj) {
            console.warn(LOG, "patchHCaptcha called with null object");
            return;
        }
        console.log(LOG, "Patching hcaptcha object. Has render:", !!obj.render, "Has execute:", !!obj.execute);

        // Intercept render()
        if (obj.render) {
            let originalRenderFunc = obj.render;
            obj.render = function (container, opts) {
                console.log(LOG, "hcaptcha.render() intercepted");
                let widgetInfo = createHCaptchaWidgetInfo(container, opts);
                if (widgetInfo) {
                    let iter = 0;
                    const intId = setInterval(function() {
                        if (++iter > 200) { clearInterval(intId); return; }
                        if (typeof registerCaptchaWidget === 'function') {
                            clearInterval(intId);
                            registerCaptchaWidget(widgetInfo);
                            console.log(LOG, "hCaptcha widget registered from render():", widgetInfo.containerId);
                        }
                    }, 50);
                }
                return originalRenderFunc(container, opts);
            };
            console.log(LOG, "render() patched");
        }

        // Patch getResponse
        if (obj.getResponse) {
            let origGetResponse = obj.getResponse;
            obj.getResponse = function(id) {
                let val = origGetResponse(id);
                if (val && val.length > 20) {
                    let btn = document.querySelector('.captcha-solver[data-captcha-type="hcaptcha"]');
                    if (btn) btn.dataset.response = val;
                }
                return val;
            };
        }

        // Alias grecaptcha.getResponse for compatibility
        try {
            if (window.grecaptcha && !window.grecaptcha.getResponse) {
                window.grecaptcha.getResponse = function() {
                    let ta = document.querySelector('[name=h-captcha-response]');
                    return ta ? ta.value : '';
                };
            }
        } catch(e) {}
    }

    function createHCaptchaWidgetInfo(container, opts) {
        if (!opts) opts = {};

        if (typeof container !== 'string') {
            if (!container) return null;
            if (!container.id) {
                container.id = "hcaptcha-container-" + Date.now();
            }
            container = container.id;
        }

        let callback = opts.callback;
        if (callback !== undefined && typeof callback === "function") {
            let key = "hcaptchaCallback" + Date.now();
            window[key] = callback;
            callback = key;
        }

        return {
            captchaType: "hcaptcha",
            widgetId: nextWidgetId++,
            containerId: container,
            sitekey: opts.sitekey || null,
            callback: callback,
        };
    }

    // Wait for core helpers
    let iter = 0;
    const checkReady = setInterval(function() {
        if (++iter > 200) {
            clearInterval(checkReady);
            console.warn(LOG, "Timeout waiting for registerCaptchaWidget, forcing setup");
            setupInterceptor();
            return;
        }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            console.log(LOG, "registerCaptchaWidget ready, setting up interceptor");
            setupInterceptor();
        }
    }, 50);

})();
