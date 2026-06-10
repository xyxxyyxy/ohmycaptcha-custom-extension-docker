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
                console.log("[OMC:hcap-proc] onSolved called, answer length:", answer ? answer.length : 0);
                
                // Method 1: Find and set ALL h-captcha-response textareas
                let textareas = document.querySelectorAll('textarea[name="h-captcha-response"]');
                if (!textareas.length) {
                    textareas = document.querySelectorAll('textarea[id*="h-captcha-response"]');
                }
                if (!textareas.length) {
                    // Try within the widget container
                    let container = document.getElementById(widget.containerId);
                    if (container) {
                        textareas = container.querySelectorAll("textarea");
                    }
                }
                
                let found = false;
                for (let i = 0; i < textareas.length; i++) {
                    let ta = textareas[i];
                    ta.value = answer;
                    ta.style.display = "none"; // Keep hidden
                    found = true;
                    console.log("[OMC:hcap-proc] Set textarea:", ta.id || ta.name);
                    
                    // Dispatch events
                    ['input', 'change', 'blur'].forEach(function(eventName) {
                        try {
                            let evt = new Event(eventName, {bubbles: true});
                            ta.dispatchEvent(evt);
                        } catch(e) {}
                    });
                }
                
                if (!found) {
                    console.warn("[OMC:hcap-proc] No textarea found, creating fallback");
                    let fallbackTa = document.createElement("textarea");
                    fallbackTa.name = "h-captcha-response";
                    fallbackTa.style.display = "none";
                    fallbackTa.value = answer;
                    document.body.appendChild(fallbackTa);
                    console.log("[OMC:hcap-proc] Created fallback textarea");
                }
                
                // Method 2: Try to call hCaptcha's internal API
                try {
                    if (window.hcaptcha) {
                        console.log("[OMC:hcap-proc] Calling window.hcaptcha.setResponse");
                        if (typeof window.hcaptcha.setResponse === 'function') {
                            window.hcaptcha.setResponse(answer);
                        }
                    }
                } catch(e) {
                    console.warn("[OMC:hcap-proc] hcaptcha API error:", e.message);
                }
                
                // Method 3: Try data-callback via widget ID
                if (widget.widgetId && widget.widgetId !== "mockWidgetId") {
                    try {
                        if (window.hcaptcha && typeof window.hcaptcha.getResponse === 'function') {
                            console.log("[OMC:hcap-proc] Trying hcaptcha.getResponse for widget:", widget.widgetId);
                        }
                    } catch(e) {}
                }
                
                // Method 4: Trigger callback if registered
                let callback = widget.callback;
                if (callback && typeof window[callback] === 'function') {
                    console.log("[OMC:hcap-proc] Calling callback:", callback);
                    try { 
                        window[callback](answer); 
                        console.log("[OMC:hcap-proc] Callback executed");
                    } catch(e) {
                        console.error("[OMC:hcap-proc] Callback error:", e);
                    }
                }
                
                // Method 5: Enable disabled submit buttons
                let submitButtons = document.querySelectorAll("input[type='submit'], button[type='submit']");
                for (let i = 0; i < submitButtons.length; i++) {
                    if (submitButtons[i].disabled) {
                        submitButtons[i].disabled = false;
                        submitButtons[i].removeAttribute('disabled');
                        console.log("[OMC:hcap-proc] Enabled submit button");
                    }
                }
                
                // Method 6: Add visual indicator
                this._addSolvedIndicator(widget);
                
                console.log("[OMC:hcap-proc] onSolved complete");
            },

            _addSolvedIndicator: function(widget) {
                let container = document.getElementById(widget.containerId);
                if (container) {
                    let existing = container.querySelector(".omc-solved-badge");
                    if (existing) existing.remove();
                    
                    let badge = document.createElement("div");
                    badge.className = "omc-solved-badge";
                    badge.style.cssText = "background:#4CAF50;color:white;padding:4px 8px;border-radius:4px;font-size:12px;font-family:sans-serif;margin-top:4px;display:inline-block;font-weight:bold;";
                    badge.textContent = "hCAPTCHA SOLVED - Token Ready";
                    container.appendChild(badge);
                    
                    setTimeout(function() {
                        badge.style.transition = "opacity 1s";
                        badge.style.opacity = "0";
                        setTimeout(function() { if (badge.parentNode) badge.parentNode.removeChild(badge); }, 1000);
                    }, 10000);
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
