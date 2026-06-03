(() => {

    let turnstileInstance;
    let interceptorReady = false;
    let nextWidgetId = 0;

    function setupInterceptor() {
        if (interceptorReady) return;
        interceptorReady = true;

        Object.defineProperty(window, "turnstile", {
            configurable: true,
            get: function () {
                return turnstileInstance;
            },
            set: function (e) {
                turnstileInstance = e;
                patchTurnstile(e);
            },
        });

        // If turnstile already exists, patch it immediately
        if (window.turnstile && window.turnstile !== turnstileInstance) {
            turnstileInstance = window.turnstile;
            patchTurnstile(window.turnstile);
        }
    }

    function patchTurnstile(obj) {
        if (!obj) return;

        let originalRenderFunc = obj.render;

        if (originalRenderFunc) {
            obj.render = function (container, opts) {
                createTurnstileWidget(container, opts);
                return originalRenderFunc(container, opts);
            };
        }
    }

    let createTurnstileWidget = function (container, opts) {
        if (!opts) opts = {};

        if (typeof container !== 'string') {
            if (!container) return;
            if (!container.id) {
                container.id = "turnstile-container-" + Date.now();
            }
            container = container.id;
        }

        let widgetInfo = {
            captchaType: "turnstile",
            widgetId: nextWidgetId++,
            inputId: container,
            sitekey: opts.sitekey,
            callback: opts.callback,
        };

        let iter = 0;
        const intId = setInterval(() => {
            if (++iter > 200) clearInterval(intId);
            if (typeof registerCaptchaWidget === 'function') {
                clearInterval(intId);
                registerCaptchaWidget(widgetInfo);
            }
        }, 50);
    };

    // Wait for core helpers before setting up interceptor
    let iter = 0;
    const checkReady = setInterval(() => {
        if (++iter > 200) { clearInterval(checkReady); setupInterceptor(); }
        if (typeof registerCaptchaWidget === 'function') {
            clearInterval(checkReady);
            setupInterceptor();
        }
    }, 50);

})()
