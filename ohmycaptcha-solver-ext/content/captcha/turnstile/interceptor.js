(function() {
    "use strict";

    const LOG = "[OMC:turn-interceptor]";
    console.log(LOG, "Loading Turnstile interceptor...");

    let turnstileInstance = undefined;
    let interceptorReady = false;
    let nextWidgetId = 0;

    function setupInterceptor() {
        if (interceptorReady) {
            console.log(LOG, "Interceptor already set up");
            return;
        }

        console.log(LOG, "Setting up turnstile property interceptor...");
        interceptorReady = true;

        try {
            Object.defineProperty(window, "turnstile", {
                configurable: true,
                get: function () {
                    return turnstileInstance;
                },
                set: function (e) {
                    console.log(LOG, "turnstile SET fired");
                    turnstileInstance = e;
                    try {
                        patchTurnstile(e);
                    } catch (err) {
                        console.error(LOG, "Error in turnstile setter:", err);
                    }
                },
            });
            console.log(LOG, "Property descriptor installed on window.turnstile");
        } catch (err) {
            console.error(LOG, "Failed to install property interceptor:", err);
            return;
        }

        // If turnstile already exists
        if (typeof window.turnstile !== 'undefined' && window.turnstile !== turnstileInstance) {
            console.log(LOG, "turnstile already exists! Patching immediately...");
            turnstileInstance = window.turnstile;
            patchTurnstile(window.turnstile);
        } else {
            console.log(LOG, "turnstile not yet present. Waiting...");
        }
    }

    function patchTurnstile(obj) {
        if (!obj) {
            console.warn(LOG, "patchTurnstile called with null");
            return;
        }
        console.log(LOG, "Patching turnstile object. Has render:", !!obj.render);

        if (obj.render) {
            let originalRenderFunc = obj.render;
            obj.render = function (container, opts) {
                console.log(LOG, "turnstile.render() intercepted");
                let widgetInfo = createTurnstileWidgetInfo(container, opts);
                if (widgetInfo) {
                    let iter = 0;
                    const intId = setInterval(function() {
                        if (++iter > 200) { clearInterval(intId); return; }
                        if (typeof registerCaptchaWidget === 'function') {
                            clearInterval(intId);
                            registerCaptchaWidget(widgetInfo);
                            console.log(LOG, "Turnstile widget registered from render():", widgetInfo.inputId);
                        }
                    }, 50);
                }
                return originalRenderFunc(container, opts);
            };
            console.log(LOG, "render() patched");
        }
    }

    function createTurnstileWidgetInfo(container, opts) {
        if (!opts) opts = {};

        if (typeof container !== 'string') {
            if (!container) return null;
            if (!container.id) {
                container.id = "turnstile-container-" + Date.now();
            }
            container = container.id;
        }

        return {
            captchaType: "turnstile",
            widgetId: nextWidgetId++,
            inputId: container,
            sitekey: opts.sitekey,
            callback: opts.callback,
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
