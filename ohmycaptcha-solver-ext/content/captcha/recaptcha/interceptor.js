(function() {
    "use strict";

    const LOG = "[OMC:rcpt-interceptor]";
    console.log(LOG, "Loading reCAPTCHA interceptor...");

    let recaptchaInstance = undefined;
    let interceptorReady = false;

    function setupInterceptor() {
        if (interceptorReady) {
            console.log(LOG, "Interceptor already set up");
            return;
        }

        console.log(LOG, "Setting up grecaptcha property interceptor...");
        interceptorReady = true;

        try {
            Object.defineProperty(window, "grecaptcha", {
                configurable: true,
                get: function () {
                    return recaptchaInstance;
                },
                set: function (e) {
                    console.log(LOG, "grecaptcha SET fired");
                    recaptchaInstance = e;
                    try {
                        manageRecaptchaObj(e);
                        manageEnterpriseObj(e);
                    } catch (err) {
                        console.error(LOG, "Error in grecaptcha setter:", err);
                    }
                },
            });
            console.log(LOG, "Property descriptor installed on window.grecaptcha");
        } catch (err) {
            console.error(LOG, "Failed to install property interceptor:", err);
            return;
        }

        // If grecaptcha already exists, process it
        if (typeof window.grecaptcha !== 'undefined' && window.grecaptcha !== recaptchaInstance) {
            console.log(LOG, "grecaptcha already exists! Processing immediately...", typeof window.grecaptcha);
            recaptchaInstance = window.grecaptcha;
            try {
                manageRecaptchaObj(window.grecaptcha);
                manageEnterpriseObj(window.grecaptcha);
            } catch (err) {
                console.error(LOG, "Error processing existing grecaptcha:", err);
            }
        } else {
            console.log(LOG, "grecaptcha not yet present. Waiting for it to load...");
        }
    }

    let manageRecaptchaObj = function (obj) {
        if (!obj) return;
        console.log(LOG, "manageRecaptchaObj called");

        if (window.___grecaptcha_cfg === undefined) {
            console.warn(LOG, "___grecaptcha_cfg not found, skipping interceptor setup");
            return;
        }

        let originalExecuteFunc;
        let originalResetFunc;
        let originalRenderFunc;

        if (obj.execute) originalExecuteFunc = obj.execute;
        if (obj.reset) originalResetFunc = obj.reset;
        if (obj.render) originalRenderFunc = obj.render;

        console.log(LOG, "Original functions:", {
            execute: !!originalExecuteFunc,
            reset: !!originalResetFunc,
            render: !!originalRenderFunc
        });

        // Intercept render() to catch all V2 widget creation
        if (originalRenderFunc) {
            obj.render = function(container, opts) {
                console.log(LOG, "grecaptcha.render() intercepted");
                let result = originalRenderFunc(container, opts);
                // The hunter will pick this up via ___grecaptcha_cfg.clients scan
                return result;
            };
            console.log(LOG, "render() intercepted");
        }

        // Intercept execute() for V3/invisible
        Object.defineProperty(obj, "execute", {
            configurable: true,
            get: function () {
                return function (sitekey, options) {
                    console.log(LOG, "grecaptcha.execute() intercepted");
                    if (!options) {
                        if (!isInvisible()) {
                            return originalExecuteFunc(sitekey, options);
                        }
                    }

                    sendMsgToSolverCS("getConfig").then(function(config) {
                        if (!config.enabledForRecaptchaV3) {
                            return originalExecuteFunc(sitekey, options);
                        }
                        if (isBlacklisted(window.location.href, config)) {
                            return originalExecuteFunc(sitekey, options);
                        }
                        let widgetId = addWidgetInfo(sitekey, options);
                        return waitForResult(widgetId);
                    });
                };
            },
            set: function (e) {
                originalExecuteFunc = e;
            },
        });
        console.log(LOG, "execute() intercepted");

        // Intercept reset()
        Object.defineProperty(obj, "reset", {
            configurable: true,
            get: function () {
                return function (widgetId) {
                    if (widgetId === undefined) {
                        let ids = Object.keys(___grecaptcha_cfg.clients)[0];
                        widgetId = ids.length ? ids[0] : 0;
                    }
                    resetCaptchaWidget("recaptcha", widgetId);
                    return originalResetFunc(widgetId);
                };
            },
            set: function (e) {
                originalResetFunc = e;
            },
        });
        console.log(LOG, "reset() intercepted");
    };

    let manageEnterpriseObj = function (obj) {
        if (!obj || !obj.enterprise) {
            console.log(LOG, "No enterprise object found");
            return;
        }
        console.log(LOG, "manageEnterpriseObj called");
        // ... (enterprise handling similar to above)
    };

    let addWidgetInfo = function (sitekey, options) {
        let widgetId = parseInt(Date.now() / 1000);
        let badge = document.querySelector(".grecaptcha-badge");
        if (badge && !badge.id) badge.id = "recaptcha-badge-" + widgetId;

        let callback = "rv3ExecCallback" + widgetId;
        window[callback] = function (response) {
            let btn = getCaptchaWidgetButton("recaptcha", widgetId);
            if (btn) btn.dataset.response = response;
        };

        let widgetInfo = {
            captchaType: "recaptcha",
            widgetId: widgetId,
            version: "v3",
            sitekey: sitekey,
            action: options ? options.action : '',
            enterprise: false,
            callback: callback,
            containerId: badge ? badge.id : null,
        };

        registerCaptchaWidget(widgetInfo);
        console.log(LOG, "V3 widget registered:", widgetId);
        return widgetId;
    };

    let waitForResult = function (widgetId) {
        return new Promise(function (resolve) {
            let interval = setInterval(function () {
                let button = getCaptchaWidgetButton("recaptcha", widgetId);
                if (button && button.dataset.response) {
                    resolve(button.dataset.response);
                    clearInterval(interval);
                }
            }, 500);
        });
    };

    let isInvisible = function () {
        let widgets = document.querySelectorAll('head captcha-widget');
        for (let i = 0; i < widgets.length; i++) {
            if (widgets[i].dataset.version == 'v2_invisible') {
                let badge = document.querySelector('.grecaptcha-badge');
                if (badge) {
                    badge.id = "recaptcha-badge-" + widgets[i].dataset.widgetId;
                    widgets[i].dataset.containerId = badge.id;
                }
                return true;
            }
        }
        return false;
    };

    let isBlacklisted = function (url, config) {
        if (!config || !config.blackListDomain) return false;
        let m = config.blackListDomain.split('\n').filter(function (entry) {
            return entry && url.includes(entry);
        });
        return m.length > 0;
    };

    // Wait for core helpers before setting up interceptor
    let iter = 0;
    const checkReady = setInterval(function() {
        if (++iter > 200) {
            clearInterval(checkReady);
            console.warn(LOG, "Timeout waiting for registerCaptchaWidget, forcing setup anyway");
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
