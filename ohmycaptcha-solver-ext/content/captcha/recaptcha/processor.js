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
                console.log("[OMC:rcpt-proc] onSolved called, answer length:", answer ? answer.length : 0);
                
                // Method 1: Find and set the textarea value(s)
                // Use vanilla JS to avoid jQuery method issues
                let textareas = document.querySelectorAll("textarea[name='g-recaptcha-response']");
                if (!textareas.length) {
                    textareas = document.querySelectorAll("textarea[id*='g-recaptcha-response']");
                }
                if (!textareas.length) {
                    let recaptchaDivs = document.querySelectorAll('iframe[src*="recaptcha"]');
                    for (let i = 0; i < recaptchaDivs.length; i++) {
                        let parent = recaptchaDivs[i].closest("div");
                        if (parent) {
                            textareas = parent.querySelectorAll("textarea");
                            if (textareas.length) break;
                        }
                    }
                }
                
                let found = false;
                for (let i = 0; i < textareas.length; i++) {
                    let ta = textareas[i];
                    ta.value = answer;
                    ta.style.display = "block"; // Make visible for form submit
                    found = true;
                    console.log("[OMC:rcpt-proc] Set textarea:", ta.id || ta.name);
                }
                
                if (!found) {
                    console.warn("[OMC:rcpt-proc] No textarea found, creating fallback");
                    let fallbackTa = document.createElement("textarea");
                    fallbackTa.name = "g-recaptcha-response";
                    fallbackTa.style.display = "none";
                    fallbackTa.value = answer;
                    document.body.appendChild(fallbackTa);
                    console.log("[OMC:rcpt-proc] Created fallback textarea");
                }
                
                // Method 2: Call explicit callback function by name
                let callback = this.getCallback(widget);
                if (callback && typeof window[callback] === 'function') {
                    console.log("[OMC:rcpt-proc] Calling callback:", callback);
                    try { 
                        window[callback](answer); 
                        console.log("[OMC:rcpt-proc] Callback executed successfully");
                    } catch(e) {
                        console.error("[OMC:rcpt-proc] Callback error:", e);
                    }
                }
                
                // Method 3: Trigger reCAPTCHA internal callbacks via ___grecaptcha_cfg
                this._triggerRecaptchaCallback(answer);
                
                // Method 4: Dispatch events so any listeners know the token was set
                this._dispatchTokenEvents(answer);
                
                // Method 5: Try grecaptcha API if available
                if (typeof grecaptcha !== 'undefined') {
                    try {
                        let widgetId = widget.widgetId;
                        if (widgetId && widgetId !== "mockWidgetId") {
                            console.log("[OMC:rcpt-proc] Trying grecaptcha.reset + re-execute for widget:", widgetId);
                            // For invisible recaptcha, this triggers the callback
                            if (widget.version === "v2_invisible" || widget.version === "v3") {
                                // The callback should have been triggered by method 3
                            }
                        }
                    } catch(e) {
                        console.warn("[OMC:rcpt-proc] grecaptcha API error:", e);
                    }
                }
                
                // Method 6: Enable any disabled form submit buttons
                this._enableFormSubmits();
                
                // Method 7: Add a visual indicator that the token was injected
                // (since we can't change the cross-origin iframe's checkbox)
                this._addSolvedIndicator(widget);
                
                console.log("[OMC:rcpt-proc] onSolved complete - token injected, form can now be submitted");
            },

            _addSolvedIndicator: function(widget) {
                // The reCAPTCHA checkbox is inside a cross-origin iframe.
                // We cannot change its visual state. Instead, add a badge
                // next to the widget container to show the token is ready.
                let container = null;
                if (widget.containerId) {
                    container = document.getElementById(widget.containerId);
                }
                if (!container) {
                    container = document.querySelector(".g-recaptcha");
                }
                if (container) {
                    // Remove any existing indicator
                    let existing = container.parentNode.querySelector(".omc-solved-badge");
                    if (existing) existing.remove();
                    
                    let badge = document.createElement("div");
                    badge.className = "omc-solved-badge";
                    badge.style.cssText = "background:#4CAF50;color:white;padding:4px 8px;border-radius:4px;font-size:12px;font-family:sans-serif;margin-top:4px;display:inline-block;font-weight:bold;";
                    badge.textContent = "CAPTCHA SOLVED - Token Ready";
                    container.parentNode.insertBefore(badge, container.nextSibling);
                    
                    // Auto-remove after 10 seconds
                    setTimeout(function() {
                        badge.style.transition = "opacity 1s";
                        badge.style.opacity = "0";
                        setTimeout(function() { if (badge.parentNode) badge.parentNode.removeChild(badge); }, 1000);
                    }, 10000);
                    
                    console.log("[OMC:rcpt-proc] Added solved indicator badge");
                } else {
                    console.log("[OMC:rcpt-proc] No container found for solved indicator");
                }
            },

            _enableFormSubmits: function() {
                // Many sites disable their submit button until reCAPTCHA is solved
                // Re-enable all submit buttons that might have been disabled
                let submitButtons = document.querySelectorAll("input[type='submit'], button[type='submit']");
                for (let i = 0; i < submitButtons.length; i++) {
                    let btn = submitButtons[i];
                    if (btn.disabled) {
                        btn.disabled = false;
                        btn.removeAttribute('disabled');
                        console.log("[OMC:rcpt-proc] Enabled submit button");
                    }
                }
                
                // Also try to find buttons with common CAPTCHA-gated patterns
                let disabledElements = document.querySelectorAll("button[disabled], input[disabled]");
                for (let i = 0; i < disabledElements.length; i++) {
                    let el = disabledElements[i];
                    let text = ((el.value || el.textContent || '')).toLowerCase();
                    if (text.match(/submit|send|post|confirm|verify|login|register|sign/)) {
                        el.disabled = false;
                        el.removeAttribute('disabled');
                    }
                }
            },

            _triggerRecaptchaCallback: function(answer) {
                // Access reCAPTCHA's internal client configuration
                if (!window.___grecaptcha_cfg || !window.___grecaptcha_cfg.clients) {
                    console.log("[OMC:rcpt-proc] ___grecaptcha_cfg not available");
                    return;
                }
                
                let clients = window.___grecaptcha_cfg.clients;
                console.log("[OMC:rcpt-proc] Found", Object.keys(clients).length, "reCAPTCHA clients");
                
                Object.keys(clients).forEach(function(clientId) {
                    let client = clients[clientId];
                    
                    // Try various callback locations in the reCAPTCHA internals
                    let callbacks = [];
                    
                    // Standard callback
                    if (client.callback) {
                        callbacks.push({fn: client.callback, name: "client.callback"});
                    }
                    // l.callback (internal structure)  
                    if (client.l && client.l.callback) {
                        callbacks.push({fn: client.l.callback, name: "client.l.callback"});
                    }
                    // C.L.callback (alternative internal structure)
                    if (client.C && client.C.L && client.C.L.callback) {
                        callbacks.push({fn: client.C.L.callback, name: "client.C.L.callback"});
                    }
                    // Client stored under 'l' key directly
                    if (client.l && client.l.L && client.l.L.callback) {
                        callbacks.push({fn: client.l.L.callback, name: "client.l.L.callback"});
                    }
                    // Yet another variant
                    if (typeof client === 'function') {
                        callbacks.push({fn: client, name: "client function"});
                    }
                    
                    callbacks.forEach(function(cb) {
                        if (typeof cb.fn === 'function') {
                            try {
                                cb.fn(answer);
                                console.log("[OMC:rcpt-proc] Triggered callback:", cb.name);
                            } catch(e) {
                                console.warn("[OMC:rcpt-proc] Callback failed:", cb.name, e.message);
                            }
                        }
                    });
                });
            },

            _dispatchTokenEvents: function(answer) {
                // Dispatch custom events that page scripts might be listening for
                let events = ['input', 'change', 'blur'];
                let textareas = document.querySelectorAll("textarea[name='g-recaptcha-response']");
                
                for (let i = 0; i < textareas.length; i++) {
                    let ta = textareas[i];
                    for (let j = 0; j < events.length; j++) {
                        try {
                            let evt = new Event(events[j], {bubbles: true, cancelable: true});
                            ta.dispatchEvent(evt);
                        } catch(e) {}
                    }
                }
                
                console.log("[OMC:rcpt-proc] Dispatched token events to", textareas.length, "textareas");
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
