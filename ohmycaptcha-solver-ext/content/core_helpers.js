(function() {
    "use strict";

    const LOG = "[OMC:core]";

    // Define ALL window functions immediately (can't fail)

    let widgetsList = null;

    function ensureContainer() {
        // If we already have it, return it
        if (widgetsList) return widgetsList;
        
        // Try to find existing
        widgetsList = document.querySelector('head > captcha-widgets');
        if (widgetsList) return widgetsList;
        
        // Create if document.head is available (may be null at document_start)
        if (document.head) {
            widgetsList = document.createElement("captcha-widgets");
            document.head.appendChild(widgetsList);
            console.log(LOG, "Created captcha-widgets container in <head>");
            return widgetsList;
        }
        return null;
    }

    window.registerCaptchaWidget = function(widgetInfo) {
        if (!widgetInfo || !widgetInfo.captchaType) {
            return;
        }
        // Lazy-create container on every registration attempt
        let list = ensureContainer();
        if (!list) {
            // document.head not ready yet — this is normal at document_start
            // The hunter will retry on its next interval
            return;
        }
        // Skip duplicates
        let existing = list.querySelector(
            'captcha-widget[data-captcha-type="' + widgetInfo.captchaType + '"][data-widget-id="' + widgetInfo.widgetId + '"]'
        );
        if (existing) return;

        let widget = document.createElement("captcha-widget");
        for (let k in widgetInfo) {
            if (widgetInfo[k] !== null && widgetInfo[k] !== undefined) {
                widget.dataset[k] = widgetInfo[k];
            }
        }
        list.appendChild(widget);
    };

    window.isCaptchaWidgetRegistered = function(captchaType, widgetId) {
        let list = ensureContainer();
        if (!list) return false;
        let widgets = list.children;
        for (let i = 0; i < widgets.length; i++) {
            if (widgets[i].dataset.captchaType !== captchaType) continue;
            if (widgets[i].dataset.widgetId !== widgetId + '') continue;
            return true;
        }
        return false;
    };

    window.resetCaptchaWidget = function(captchaType, widgetId) {
        let list = ensureContainer();
        if (!list) return;
        let widgets = list.children;
        for (let i = 0; i < widgets.length; i++) {
            let wd = widgets[i].dataset;
            if (wd.captchaType != captchaType) continue;
            if (wd.widgetId != widgetId) continue;
            wd.reset = true;
            break;
        }
    };

    window.getCaptchaWidgetButton = function(captchaType, widgetId) {
        return document.querySelector(
            ".captcha-solver[data-captcha-type='" + captchaType + "'][data-widget-id='" + widgetId + "']"
        );
    };

    window.__omc_core_ready__ = true;
    console.log(LOG, "Core helpers ready.");

    // Try initial container creation (likely document.head is null here at document_start)
    ensureContainer();

})();
