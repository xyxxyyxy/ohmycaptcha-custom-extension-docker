document.addEventListener('DOMContentLoaded', function() {
    let apiUrlInput = document.getElementById('apiUrl');
    let apiKeyInput = document.getElementById('apiKey');
    let autoClickInput = document.getElementById('autoClick');
    let saveBtn = document.getElementById('saveBtn');
    let statusDiv = document.getElementById('status');

    // Load saved values
    chrome.storage.local.get('config', function(result) {
        let cfg = result.config || {};
        if (cfg.apiUrl) apiUrlInput.value = cfg.apiUrl;
        if (cfg.apiKey) apiKeyInput.value = cfg.apiKey;
        // Auto-click: true if any autoSolve* setting is enabled
        let autoEnabled = cfg.autoClickEnabled ||
            cfg.autoSolveRecaptchaV2 ||
            cfg.autoSolveInvisibleRecaptchaV2 ||
            cfg.autoSolveRecaptchaV3 ||
            cfg.autoSolveHCaptcha ||
            cfg.autoSolveTurnstile ||
            cfg.autoSolveNormal || false;
        autoClickInput.checked = !!autoEnabled;
    });

    saveBtn.addEventListener('click', async function() {
        let apiUrl = apiUrlInput.value.trim();
        let apiKey = apiKeyInput.value.trim();
        let autoClick = autoClickInput.checked;

        if (!apiUrl) {
            showStatus('API URL is required', 'err');
            return;
        }

        // Build autoSolve flags from the single toggle
        let saveData = {
            apiUrl: apiUrl,
            apiKey: apiKey,
            autoClickEnabled: autoClick,
            autoSolveRecaptchaV2: autoClick,
            autoSolveInvisibleRecaptchaV2: autoClick,
            autoSolveRecaptchaV3: autoClick,
            autoSolveHCaptcha: autoClick,
            autoSolveTurnstile: autoClick,
            autoSolveNormal: autoClick,
        };

        // Save config - merge with existing to avoid overwriting other settings
        chrome.storage.local.get('config', function(result) {
            let existing = result.config || {};
            let merged = Object.assign({}, existing, saveData);
            chrome.storage.local.set({ config: merged });
        });

        // Test connection
        showStatus('Testing...', 'ok');
        try {
            let apiOk = await fetch(apiUrl + '/api/v1/health').then(r => r.ok).catch(() => false);
            if (apiOk) {
                showStatus('OhMyCaptcha OK' + (autoClick ? ' | Auto-click ON' : ' | Auto-click OFF'), 'ok');
            } else {
                showStatus('OhMyCaptcha unreachable', 'err');
            }
        } catch(e) {
            showStatus('Error: ' + e.message, 'err');
        }
    });

    function showStatus(msg, cls) {
        statusDiv.textContent = msg;
        statusDiv.className = 'status ' + cls;
        statusDiv.style.display = 'block';
    }
});
