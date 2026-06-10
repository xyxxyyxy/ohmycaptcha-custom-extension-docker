/*
 * CaptchaProcessors registry
 */
window.CaptchaProcessors = {
    processors: {},

    register: function(processor) {
        this.processors[processor.captchaType] = processor;
        console.log("[OMC:proc] Registered processor for:", processor.captchaType);
    },

    get: function(captchaType) {
        return this.processors[captchaType];
    }
};

/*
 * Helper: send message to service worker
 */
window.sendMsgToSolverCS = function(action) {
    return new Promise(function(resolve) {
        chrome.runtime.sendMessage({action: action}, resolve);
    });
};

/*
 * Main content script
 */
(function() {
    "use strict";

    const LOG = "[OMC:main]";
    console.log(LOG, "script.js loading...");

    let config = null;
    let initialized = false;

    function init() {
        if (initialized) {
            console.log(LOG, "Already initialized");
            return;
        }

        // Wait for jQuery AND core helpers
        if (typeof window.jQuery === 'undefined' || typeof window.$ === 'undefined') {
            console.log(LOG, "Waiting for jQuery...");
            setTimeout(init, 100);
            return;
        }
        if (typeof window.registerCaptchaWidget !== 'function') {
            console.log(LOG, "Waiting for registerCaptchaWidget...");
            setTimeout(init, 100);
            return;
        }

        initialized = true;
        console.log(LOG, "jQuery and registerCaptchaWidget ready. Initializing...");

        Config.getAll().then(function(cfg) {
            config = cfg;
            console.log(LOG, "Config loaded. Plugin enabled:", config.isPluginEnabled);
            console.log(LOG, "Settings:", {
                recaptchaV2: config.enabledForRecaptchaV2,
                recaptchaV3: config.enabledForRecaptchaV3,
                hcaptcha: config.enabledForHCaptcha,
                turnstile: config.enabledForTurnstile,
                normal: config.enabledForNormal
            });

            if (!config.isPluginEnabled) {
                console.log(LOG, "Plugin disabled in config.");
                return;
            }

            console.log(LOG, "Starting widget scanner...");
            scanWidgets();
            setInterval(scanWidgets, 2000);

            // Also use MutationObserver for dynamic CAPTCHA injection
            observeMutations();
        }).catch(function(e) {
            console.error(LOG, "Config error:", e);
        });
    }

    // Observe DOM changes for dynamically injected CAPTCHAs
    function observeMutations() {
        if (!window.MutationObserver) return;

        let observer = new MutationObserver(function(mutations) {
            let shouldScan = false;
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes.length > 0) {
                    for (let i = 0; i < mutation.addedNodes.length; i++) {
                        let node = mutation.addedNodes[i];
                        if (node.nodeType === 1) { // Element
                            let tag = node.tagName;
                            let cls = (node.className && node.className.baseVal !== undefined)
                                ? node.className.baseVal || ''
                                : (node.className || '');
                            // Check for CAPTCHA-related elements
                            if ((typeof cls === 'string' && (
                                cls.includes('g-recaptcha') ||
                                cls.includes('h-captcha') ||
                                cls.includes('cf-turnstile') ||
                                cls.includes('grecaptcha')
                            )) || (tag === 'IFRAME' && node.src && (
                                    node.src.includes('recaptcha') ||
                                    node.src.includes('hcaptcha') ||
                                    node.src.includes('challenges.cloudflare')
                            ))) {
                                shouldScan = true;
                            }
                        }
                    }
                }
            });
            if (shouldScan) {
                console.log(LOG, "MutationObserver detected CAPTCHA-related element, scanning...");
                // Let hunters run first
                setTimeout(scanWidgets, 500);
            }
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });
        console.log(LOG, "MutationObserver started");
    }

    function scanWidgets() {
        // Lazy-create container if needed (document.head may not exist at document_start)
        let widgetsList = document.querySelector('head > captcha-widgets');
        if (!widgetsList) {
            if (document.head) {
                widgetsList = document.createElement("captcha-widgets");
                document.head.appendChild(widgetsList);
            } else {
                return; // DOM not ready yet
            }
        }

        let widgets = widgetsList.querySelectorAll('captcha-widget:not([data-processed])');
        if (widgets.length > 0) {
            console.log(LOG, "Found", widgets.length, "unprocessed widget(s)");
        }

        widgets.forEach(function(widget) {
            widget.dataset.processed = "true";
            processWidget(widget);
        });
    }

    function processWidget(widget) {
        let type = widget.dataset.captchaType;
        let processor = CaptchaProcessors.get(type);

        console.log(LOG, "Processing widget:", type, "id=" + widget.dataset.widgetId);

        if (!processor) {
            console.warn(LOG, "No processor for captcha type:", type);
            return;
        }

        try {
            if (!processor.canBeProcessed(widget.dataset, config)) {
                console.log(LOG, "Processor says cannot process widget:", type, "id=" + widget.dataset.widgetId);
                return;
            }
        } catch (e) {
            console.error(LOG, "canBeProcessed threw for", type, ":", e);
            return;
        }

        console.log(LOG, "Creating solve button for:", type, "id=" + widget.dataset.widgetId);
        let button = createButton(widget.dataset, config);

        try {
            processor.attachButton(widget.dataset, config, button);
            console.log(LOG, "Button attached for:", type, "id=" + widget.dataset.widgetId);
        } catch (e) {
            console.error(LOG, "attachButton threw for", type, ":", e);
            return;
        }

        button.on("click", function(e) {
            e.preventDefault();
            solveWidget(widget.dataset, processor);
        });

        // Auto-solve if configured
        let autoSolve = false;
        if (type === "recaptcha" && widget.dataset.version === "v2" && config.autoSolveRecaptchaV2) autoSolve = true;
        if (type === "recaptcha" && widget.dataset.version === "v2_invisible" && config.autoSolveInvisibleRecaptchaV2) autoSolve = true;
        if (type === "recaptcha" && widget.dataset.version === "v3" && config.autoSolveRecaptchaV3) autoSolve = true;
        if (type === "hcaptcha" && config.autoSolveHCaptcha) autoSolve = true;
        if (type === "turnstile" && config.autoSolveTurnstile) autoSolve = true;
        if (type === "normal" && config.autoSolveNormal) autoSolve = true;

        if (autoSolve) {
            console.log(LOG, "Auto-solving:", type, "id=" + widget.dataset.widgetId);
            button.click();
        }
    }

    function createButton(widget, cfg) {
        let btn = document.createElement("div");
        btn.className = "captcha-solver";
        btn.dataset.captchaType = widget.captchaType;
        btn.dataset.widgetId = widget.widgetId;
        btn.innerText = "\u{1F916} Solve";
        // Styles applied via content/style.css
        return $(btn);
    }

    function solveWidget(widget, processor) {
        let btn = getCaptchaWidgetButton(widget.captchaType, widget.widgetId);
        if (btn) btn.innerText = "Solving...";

        let params = processor.getParams(widget, config);
        params.captchaType = widget.captchaType;
        params.widgetId = widget.widgetId;

        console.log(LOG, "=== SOLVE WIDGET === type:", widget.captchaType, "id:", widget.widgetId);
        console.log(LOG, "Params:", JSON.stringify(params));

        chrome.runtime.sendMessage({
            action: "solve",
            params: params
        }, function(response) {
            console.log(LOG, "=== SOLVE RESPONSE ===", response);
            
            if (chrome.runtime.lastError) {
                console.error(LOG, "Runtime error:", chrome.runtime.lastError.message);
                if (btn) btn.innerText = "Error: " + chrome.runtime.lastError.message.substring(0, 30);
                setTimeout(function() { if (btn) btn.innerText = "\u{1F916} Solve"; }, 5000);
                return;
            }
            
            if (response && response.success) {
                let answer = response.answer;
                console.log(LOG, "Success! Answer length:", answer ? answer.length : 0);
                console.log(LOG, "Answer preview:", answer ? answer.substring(0, 60) : "EMPTY");
                
                try {
                    processor.onSolved(widget, answer);
                    console.log(LOG, "onSolved called successfully");
                    if (btn) btn.innerText = "Solved!";
                } catch (e) {
                    console.error(LOG, "onSolved threw:", e);
                    if (btn) btn.innerText = "Inject failed!";
                }
                setTimeout(function() { if (btn) btn.innerText = "\u{1F916} Solve"; }, 3000);
            } else {
                let err = (response && response.error) ? response.error : "Unknown error (null response)";
                console.error(LOG, "Solve failed:", err);
                if (btn) btn.innerText = "Failed: " + err.substring(0, 30);
                setTimeout(function() { if (btn) btn.innerText = "\u{1F916} Solve"; }, 5000);
            }
        });
    }

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            console.log(LOG, "DOMContentLoaded fired");
            init();
        });
    } else {
        console.log(LOG, "DOM already ready");
        init();
    }

    // Fallback init
    setTimeout(function() {
        if (!initialized) {
            console.warn(LOG, "Forced init after timeout");
            init();
        }
    }, 1000);

})();
