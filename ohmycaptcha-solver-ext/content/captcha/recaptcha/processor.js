(function() {
    "use strict";

    function register() {
        if (typeof CaptchaProcessors === 'undefined' || !CaptchaProcessors.register) {
            console.log("[OMC:rcpt-proc] Waiting for CaptchaProcessors...");
            setTimeout(register, 100);
            return;
        }

        CaptchaProcessors.register({
            captchaType: "recaptcha",

            canBeProcessed: function(widget, config) {
                if (!config) return false;
                if (widget.version === "v2" && !config.enabledForRecaptchaV2) return false;
                if (widget.version === "v2_invisible" && !config.enabledForInvisibleRecaptchaV2) return false;
                if (widget.version === "v3" && !config.enabledForRecaptchaV3) return false;

                let binded = this.getBindedElements(widget);
                return !!(binded.button || binded.textarea);
            },

            attachButton: function(widget, config, button) {
                let binded = this.getBindedElements(widget);

                if (binded.textarea) {
                    binded.textarea.parent().css({height: "auto"});
                    if (widget.version == "v2" || widget.version == "v2_invisible") {
                        binded.textarea.parent().after(button);
                    } else {
                        let forms = $('form');
                        if (forms.length) {
                            forms.after(button);
                        } else {
                            binded.textarea.after(button);
                        }
                    }
                } else {
                    binded.button.after(button);
                }

                if (
                    (widget.version == "v2" && config.autoSolveRecaptchaV2) ||
                    (widget.version == "v2_invisible" && config.autoSolveInvisibleRecaptchaV2) ||
                    (widget.version == "v3" && config.autoSolveRecaptchaV3)
                ) {
                    button.click();
                }
            },

            onSolved: function(widget, answer) {
                let textarea = this.getBindedElements(widget).textarea;
                if (!textarea) {
                    textarea = this.getForm(widget).find("textarea[name=g-recaptcha-response]");
                }
                if (textarea && textarea.length) {
                    textarea.val(answer);
                }
                // Also try to call the widget's callback if available
                let callback = this.getCallback(widget);
                if (callback && typeof window[callback] === 'function') {
                    try { window[callback](answer); } catch(e) {}
                }
            },

            getForm: function(widget) {
                let binded = this.getBindedElements(widget);
                if (binded.textarea) {
                    return binded.textarea.closest("form");
                }
                return binded.button.closest("form");
            },

            getCallback: function(widget) {
                return widget.callback;
            },

            getBindedElements: function(widget) {
                let result = {button: null, textarea: null};

                if (widget.containerId) {
                    let container = $("#" + widget.containerId);
                    if (container.length) {
                        result.textarea = container.find("textarea[name=g-recaptcha-response]");
                        if (!result.textarea.length) {
                            result.textarea = $("textarea[name=g-recaptcha-response]").first();
                        }
                    }
                }
                if (!result.textarea || !result.textarea.length) {
                    result.textarea = $("textarea[name=g-recaptcha-response]").first();
                }
                if (widget.bindedButtonId) {
                    result.button = $("#" + widget.bindedButtonId);
                }

                return result;
            },

            getParams: function(widget, config) {
                let params = {
                    sitekey: widget.sitekey,
                    url: location.href,
                };
                if (widget.version === "v2_invisible") {
                    params.invisible = 1;
                }
                if (widget.version === "v3") {
                    params.version = "v3";
                    params.score = config.recaptchaV3MinScore;
                }
                return params;
            },
        });

        console.log("[OMC:rcpt-proc] reCAPTCHA processor registered");
    }

    register();
})();
