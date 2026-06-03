(() => {

    let recaptchaInstance;
    let interceptorReady = false;

    function setupInterceptor() {
        if (interceptorReady) return;
        interceptorReady = true;

        Object.defineProperty(window, "grecaptcha", {
            configurable: true,
            get: function () {
                return recaptchaInstance;
            },
            set: function (e) {
                recaptchaInstance = e;
                manageRecaptchaObj(e);
                manageEnterpriseObj(e);
            },
        });

        // If grecaptcha already exists, process it immediately
        if (window.grecaptcha && window.grecaptcha !== recaptchaInstance) {
            recaptchaInstance = window.grecaptcha;
            manageRecaptchaObj(window.grecaptcha);
            manageEnterpriseObj(window.grecaptcha);
        }
    }

    let manageRecaptchaObj = function (obj) {
        if (window.___grecaptcha_cfg === undefined) return;
        let originalExecuteFunc;
        let originalResetFunc;

        if (obj.execute) originalExecuteFunc = obj.execute;
        if (obj.reset) originalResetFunc = obj.reset;

        Object.defineProperty(obj, "execute", {
            configurable: true,
            get: function () {
                return function (sitekey, options) {
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

        // Also intercept render() to catch V2 widgets
        let originalRenderFunc = obj.render;
        if (originalRenderFunc) {
            obj.render = function(container, opts) {
                let widgetId = originalRenderFunc(container, opts);
                // Let the hunter pick this up via ___grecaptcha_cfg.clients
                return widgetId;
            };
        }
    };

    let manageEnterpriseObj = function (obj) {
        if (window.___grecaptcha_cfg === undefined) return;
        let originalEnterpriseObj;

        Object.defineProperty(obj, "enterprise", {
            configurable: true,
            get: function () {
                return originalEnterpriseObj;
            },
            set: function (ent) {
                originalEnterpriseObj = ent;

                let originalExecuteFunc;
                let originalResetFunc;

                Object.defineProperty(ent, "execute", {
                    configurable: true,
                    get: function () {
                        return function (sitekey, options) {
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

                                let widgetId = addWidgetInfo(sitekey, options, "1");

                                return waitForResult(widgetId);
                            });
                        };
                    },
                    set: function (e) {
                        originalExecuteFunc = e;
                    },
                });

                Object.defineProperty(ent, "reset", {
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
            },
        });
    };

    let addWidgetInfo = function (sitekey, options, enterprise) {
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
            s: null,
            enterprise: enterprise ? true : false,
            callback: callback,
            containerId: badge ? badge.id : null,
        };

        registerCaptchaWidget(widgetInfo);

        return widgetId;
    };

    let waitForResult = function (widgetId) {
        return new Promise(function (resolve, reject) {
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
        if (!config.blackListDomain) return false;
        let m = config.blackListDomain.split('\n').filter(function (entry) {
            return entry && url.includes(entry);
        });
        return m.length > 0;
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
