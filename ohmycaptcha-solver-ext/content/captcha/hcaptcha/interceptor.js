(() => {

    let hCaptchaInstance;
    let interceptorReady = false;
    let nextWidgetId = 0;

    function setupInterceptor() {
        if (interceptorReady) return;
        interceptorReady = true;

        Object.defineProperty(window, "hcaptcha", {
            configurable: true,
            get: function () {
                return hCaptchaInstance;
            },
            set: function (e) {
                hCaptchaInstance = e;
                patchHCaptcha(e);
            },
        });

        // If hcaptcha already exists, patch it immediately
        if (window.hcaptcha && window.hcaptcha !== hCaptchaInstance) {
            hCaptchaInstance = window.hcaptcha;
            patchHCaptcha(window.hcaptcha);
        }
    }

    function patchHCaptcha(obj) {
        if (!obj) return;

        let originalRenderFunc = obj.render;

        if (originalRenderFunc) {
            obj.render = function (container, opts) {
                createHCaptchaWidget(container, opts);
                return originalRenderFunc(container, opts);
            };
        }

        // Patch getResponse if available
        if (obj.getResponse) {
            let origGetResponse = obj.getResponse;
            obj.getResponse = function(id) {
                let val = origGetResponse(id);
                if (val && val.length > 20) {
                    // Token found — notify any waiting buttons
                    let btn = document.querySelector('.captcha-solver[data-captcha-type="hcaptcha"]');
                    if (btn) btn.dataset.response = val;
                }
                return val;
            };
        }

        // Alias grecaptcha.getResponse for compatibility
        if (window.grecaptcha && !window.grecaptcha.getResponse) {
            window.grecaptcha.getResponse = function() {
                let ta = document.querySelector('[name=h-captcha-response]');
                return ta ? ta.value : '';
            };
        }
    }

    let createHCaptchaWidget = function (container, opts) {
        if (!opts) opts = {};

        if (typeof container !== 'string') {
            if (!container) return;
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

        let widgetInfo = {
            captchaType: "hcaptcha",
            widgetId: nextWidgetId++,
            containerId: container,
            sitekey: opts.sitekey || null,
            callback: callback,
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
