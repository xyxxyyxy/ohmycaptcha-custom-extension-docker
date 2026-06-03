(function() {
    "use strict";

    function register() {
        if (typeof CaptchaProcessors === 'undefined' || !CaptchaProcessors.register) {
            console.log("[OMC:hcap-proc] Waiting for CaptchaProcessors...");
            setTimeout(register, 100);
            return;
        }

        CaptchaProcessors.register({
            captchaType: "hcaptcha",

            canBeProcessed: function(widget, config) {
                if (!config) return false;
                if (!config.enabledForHCaptcha) return false;
                if (!("#" + widget.containerId).length) return false;
                if (!widget.sitekey) return false;
                return true;
            },

            attachButton: function(widget, config, button) {
                let container = $("#" + widget.containerId);
                let iframe = container.find('iframe');
                if (iframe.length) {
                    button.css({ width: iframe.outerWidth() + "px" });
                }
                container.append(button);

                if (config.autoSolveHCaptcha) button.click();
            },

            getParams: function(widget, config) {
                return {
                    url: location.href,
                    sitekey: widget.sitekey,
                };
            },

            onSolved: function(widget, answer) {
                let container = $("#" + widget.containerId);
                container.find("textarea").val(answer);
                container.find("iframe").attr("data-hcaptcha-response", answer);

                // Trigger callback if available
                let callback = widget.callback;
                if (callback && typeof window[callback] === 'function') {
                    try { window[callback](answer); } catch(e) {}
                }
            },

            getForm: function(widget) {
                return $("#" + widget.containerId).closest("form");
            },

            getCallback: function(widget) {
                return widget.callback;
            },
        });

        console.log("[OMC:hcap-proc] hCaptcha processor registered");
    }

    register();
})();
