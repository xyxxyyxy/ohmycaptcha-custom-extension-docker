/*
 * CaptchaProcessors registry
 */
window.CaptchaProcessors = {
    processors: {},

    register: function(processor) {
        this.processors[processor.captchaType] = processor;
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
 * Main content script - waits for jQuery then initializes
 */
(function() {
    "use strict";

    let config = null;
    let initialized = false;

    function init() {
        if (initialized) return;
        initialized = true;

        Config.getAll().then(function(cfg) {
            config = cfg;
            if (!config.isPluginEnabled) return;
            scanWidgets();
            setInterval(scanWidgets, 2000);
        }).catch(function(e) {
            console.error("[OhMyCaptcha] Config error:", e);
        });
    }

    function scanWidgets() {
        let widgetsList = document.querySelector('head > captcha-widgets');
        if (!widgetsList) return;

        let newWidgets = widgetsList.querySelectorAll('captcha-widget:not([data-processed])');
        newWidgets.forEach(function(widget) {
            widget.dataset.processed = "true";
            processWidget(widget);
        });
    }

    function processWidget(widget) {
        let type = widget.dataset.captchaType;
        let processor = CaptchaProcessors.get(type);
        if (!processor) return;

        if (!processor.canBeProcessed(widget.dataset, config)) return;

        let button = createButton(widget.dataset, config);
        processor.attachButton(widget.dataset, config, button);

        button.on("click", function(e) {
            e.preventDefault();
            solveWidget(widget.dataset, processor);
        });
    }

    function createButton(widget, config) {
        let btn = document.createElement("div");
        btn.className = "captcha-solver";
        btn.dataset.captchaType = widget.captchaType;
        btn.dataset.widgetId = widget.widgetId;
        btn.innerText = "\u{1F916} Solve";
        return $(btn);
    }

    function solveWidget(widget, processor) {
        let btn = getCaptchaWidgetButton(widget.captchaType, widget.widgetId);
        if (btn) btn.innerText = "Solving...";

        let params = processor.getParams(widget, config);
        params.captchaType = widget.captchaType;
        params.widgetId = widget.widgetId;

        chrome.runtime.sendMessage({
            action: "solve",
            params: params
        }, function(response) {
            if (response && response.success) {
                processor.onSolved(widget, response.answer);
                if (btn) btn.innerText = "Solved!";
                setTimeout(() => { if (btn) btn.innerText = "\u{1F916} Solve"; }, 3000);
            } else {
                if (btn) btn.innerText = "Failed";
                setTimeout(() => { if (btn) btn.innerText = "\u{1F916} Solve"; }, 3000);
            }
        });
    }

    // Wait for jQuery then init
    function waitForJQuery() {
        if (typeof window.jQuery !== 'undefined' && typeof window.$ !== 'undefined') {
            init();
        } else {
            setTimeout(waitForJQuery, 50);
        }
    }

    // Start waiting
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', waitForJQuery);
    } else {
        waitForJQuery();
    }

})();
