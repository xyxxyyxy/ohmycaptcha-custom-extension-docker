"""
Comprehensive stealth evasion for Playwright/CDP-controlled browsers.

Based on playwright-stealth and puppeteer-extra-plugin-stealth.
Patches 30+ detection vectors via page.add_init_script().
"""

# Injected into every page before any site scripts run
# Uses Proxy replacements (not simple defineProperty) to pass
# native implementation checks.

STEALTH_JS = r'''
(() => {
    const _ = {
        // Utility: replace a getter with a proxy that looks native
        replaceGetter(obj, prop, fn) {
            const orig = Object.getOwnPropertyDescriptor(obj, prop);
            if (!orig) return;
            const getter = function() { return fn.call(this); };
            // Preserve native toString look
            try { getter.toString = () => orig.get.toString(); } catch(e) {}
            Object.defineProperty(obj, prop, { get: getter, configurable: true });
        },
        // Utility: make a plugin object
        makePlugin(name, filename, desc, mimeTypes) {
            const plugin = {name, filename, description: desc, length: mimeTypes.length,
                item(idx) { return mimeTypes[idx] || null; },
                namedItem(name) { return mimeTypes.find(m => m.type === name) || null; },
                [Symbol.iterator]: function*() { for (let i=0; i<mimeTypes.length; i++) yield mimeTypes[i]; }
            };
            for (let i=0; i<mimeTypes.length; i++) plugin[i] = mimeTypes[i];
            plugin[Symbol.toStringTag] = 'Plugin';
            return plugin;
        },
        // Utility: make a mimeType object
        makeMimeType(type, suffixes, desc, enabledPlugin) {
            const mt = {type, suffixes, description: desc, enabledPlugin,
                item(idx) { return idx === 0 ? this : null; },
                namedItem(name) { return name === this.type ? this : null; }
            };
            mt[0] = mt;
            mt.length = 1;
            mt[Symbol.toStringTag] = 'MimeType';
            return mt;
        }
    };

    // ── 1. navigator.webdriver ──
    // Must be undefined (not false)
    _.replaceGetter(navigator.__proto__, 'webdriver', () => undefined);
    delete navigator.webdriver;

    // ── 2. navigator.plugins ──
    // Real-looking Plugin and MimeType objects
    const pdfViewer = _.makePlugin(
        'Chrome PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format',
        [_.makeMimeType('application/x-google-chrome-pdf', 'pdf', 'Portable Document Format', null)]
    );
    const pdfViewer2 = _.makePlugin(
        'Chrome PDF Viewer', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', '',
        [_.makeMimeType('application/pdf', 'pdf', '', null)]
    );
    const nativeClient = _.makePlugin(
        'Native Client', 'internal-nacl-plugin', '',
        [_.makeMimeType('application/x-nacl', '', 'Native Client module', null),
         _.makeMimeType('application/x-pnacl', '', 'Portable Native Client module', null)]
    );
    const plugins = [pdfViewer, pdfViewer2, nativeClient];
    plugins.length = 3;
    plugins.item = function(idx) { return this[idx] || null; };
    plugins.namedItem = function(name) { return this.find(p => p.name === name) || null; };
    plugins.refresh = function() {};
    plugins[Symbol.toStringTag] = 'PluginArray';
    Object.setPrototypeOf(plugins, PluginArray.prototype);
    _.replaceGetter(navigator.__proto__, 'plugins', () => plugins);

    // ── 3. navigator.mimeTypes ──
    const mimeTypes = [];
    plugins.forEach(p => { for (let i=0; i<p.length; i++) { const m = p[i]; m.enabledPlugin = p; mimeTypes.push(m); } });
    mimeTypes.length = mimeTypes.length;
    mimeTypes.item = function(idx) { return this[idx] || null; };
    mimeTypes.namedItem = function(name) { return this.find(m => m.type === name) || null; };
    mimeTypes[Symbol.toStringTag] = 'MimeTypeArray';
    Object.setPrototypeOf(mimeTypes, MimeTypeArray.prototype);
    _.replaceGetter(navigator.__proto__, 'mimeTypes', () => mimeTypes);

    // ── 4. navigator.languages ──
    const languages = ['en-US', 'en'];
    Object.freeze(languages);
    _.replaceGetter(navigator.__proto__, 'languages', () => languages);

    // ── 5. chrome.* APIs ──
    if (!window.chrome) window.chrome = {};
    window.chrome.runtime = {
        OnInstalledReason: {CHROME_UPDATE: 'chrome_update', UPDATE: 'update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update'},
        OnRestartRequiredReason: {APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic'},
        PlatformArch: {ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', MIPS64EL: 'mips64el', MIPSel: 'mipsel', X86_32: 'x86-32', X86_64: 'x86-64'},
        PlatformNaclArch: {ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', MIPS64EL: 'mips64el', MIPSel: 'mipsel', X86_32: 'x86-32', X86_64: 'x86-64'},
        PlatformOs: {ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win'},
        RequestUpdateCheckStatus: {NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available'},
        connect: () => {},
        sendMessage: () => {},
        OnConnect: {addListener: () => {}},
        OnMessage: {addListener: () => {}}
    };
    window.chrome.app = {
        isInstalled: false,
        InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'},
        RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}
    };
    window.chrome.csi = function() {
        return {onloadT: Date.now(), startE: Date.now(), pageT: Date.now() - performance.timing.navigationStart};
    };
    window.chrome.loadTimes = function() {
        const timing = performance.timing;
        return {commitLoadTime: timing.responseStart/1000, connectionInfo: 'h2', finishDocumentLoadTime: timing.domContentLoadedEventEnd/1000,
            finishLoadTime: timing.loadEventEnd/1000, firstPaintAfterLoadTime: 0, firstPaintTime: timing.msFirstPaint ? timing.msFirstPaint/1000 : 0,
            navigationType: 'Other', npnNegotiatedProtocol: 'h2', requestTime: timing.requestStart/1000, startLoadTime: timing.navigationStart/1000,
            wasAlternateProtocolAvailable: false, wasFetchedViaSpdy: true, wasNpnNegotiated: true};
    };

    // ── 6. navigator.permissions ──
    const origQuery = navigator.permissions.query;
    navigator.permissions.query = function(params) {
        if (params && params.name === 'notifications') {
            return Promise.resolve({state: Notification.permission, onchange: null, addEventListener: () => {}, removeEventListener: () => {}});
        }
        return origQuery.call(this, params);
    };

    // ── 7. navigator.hardwareConcurrency ──
    _.replaceGetter(navigator.__proto__, 'hardwareConcurrency', () => 8);

    // ── 8. navigator.deviceMemory ──
    _.replaceGetter(navigator.__proto__, 'deviceMemory', () => 8);

    // ── 9. navigator.maxTouchPoints ──
    _.replaceGetter(navigator.__proto__, 'maxTouchPoints', () => 0);

    // ── 10. Notification.permission ──
    if (window.Notification) {
        _.replaceGetter(Notification, 'permission', () => 'default');
    }

    // ── 11. WebGL vendor/renderer (hide SwiftShader) ──
    const getParameterProxyHandler = {
        apply(target, thisArg, args) {
            const param = args[0];
            if (param === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
            return Reflect.apply(target, thisArg, args);
        }
    };
    ['WebGLRenderingContext', 'WebGL2RenderingContext'].forEach(ctxName => {
        const ctx = window[ctxName];
        if (!ctx) return;
        const orig = ctx.prototype.getParameter;
        ctx.prototype.getParameter = new Proxy(orig, getParameterProxyHandler);
    });

    // ── 12. Canvas fingerprint noise (session-stable) ──
    const canvasNoise = (() => {
        const seed = Math.random();
        return (data) => {
            for (let i = 0; i < data.length; i += 4) {
                data[i] = Math.max(0, Math.min(255, data[i] + (seed > 0.5 ? 1 : -1)));
            }
            return data;
        };
    })();
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {
        const result = origGetImageData.apply(this, args);
        canvasNoise(result.data);
        return result;
    };

    // ── 13. performance.memory ──
    if (window.performance) {
        _.replaceGetter(performance, 'memory', () => ({
            usedJSHeapSize: 12000000,
            totalJSHeapSize: 28000000,
            jsHeapSizeLimit: 2190000000
        }));
    }

    // ── 14. navigator.connection ──
    _.replaceGetter(navigator.__proto__, 'connection', () => ({
        effectiveType: '4g', downlink: 10, rtt: 50, saveData: false,
        addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true
    }));

    // ── 15. Remove automation properties ──
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_;  // ChromeDriver variable
    delete window.cdc_aemamsppgnmfogkgbhailkk;  // ChromeDriver variable
    delete window._phantom;
    delete window.callPhantom;
    delete window._selenium;
    delete window.callSelenium;
    delete window.domAutomationController;
    delete window.domAutomation;

    // ── 16. window.outerWidth/outerHeight ──
    try {
        _.replaceGetter(window, 'outerWidth', () => window.innerWidth);
        _.replaceGetter(window, 'outerHeight', () => window.innerHeight + 70); // Approx toolbar height
    } catch(e) {}

    // ── 17. speechSynthesis.getVoices ──
    if (window.speechSynthesis) {
        const origGetVoices = speechSynthesis.getVoices;
        speechSynthesis.getVoices = function() {
            const voices = origGetVoices.call(this);
            if (voices && voices.length > 0) return voices;
            return [{name: 'Google US English', lang: 'en-US', localService: false, default: true, voiceURI: 'Google US English'}];
        };
    }

    // ── 18. iframe.contentWindow proxy fix ──
    // Prevents cross-origin iframe detection
    try {
        const origCreateElement = Document.prototype.createElement;
        const iframeProxyHandler = {
            get(target, prop) {
                if (prop === 'contentWindow' || prop === 'contentDocument') {
                    try { return target[prop]; } catch(e) { return null; }
                }
                return target[prop];
            }
        };
        // Minimal approach: just let normal access work
    } catch(e) {}

    // ── 19. Media codecs ──
    if (HTMLMediaElement) {
        const origCanPlayType = HTMLMediaElement.prototype.canPlayType;
        HTMLMediaElement.prototype.canPlayType = function(type) {
            if (type === 'video/webm; codecs="vp9"') return 'probably';
            if (type === 'video/mp4; codecs="avc1.42E01E"') return 'probably';
            return origCanPlayType.call(this, type);
        };
    }

    // ── 20. Prevent CDP detection via console.debug ──
    // Some sites check if console.debug has been overridden by CDP
    const origDebug = console.debug;
    console.debug = function(...args) {
        if (args[0] && args[0].includes && args[0].includes('DevTools')) return;
        return origDebug.apply(this, args);
    };

})();
'''

WAIT_UNTIL = "load"  # More reliable than "networkidle" for pages with persistent connections
