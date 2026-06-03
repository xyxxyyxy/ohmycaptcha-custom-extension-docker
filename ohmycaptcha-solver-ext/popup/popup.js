document.addEventListener('DOMContentLoaded', function() {
    let apiUrlInput = document.getElementById('apiUrl');
    let apiKeyInput = document.getElementById('apiKey');
    let saveBtn = document.getElementById('saveBtn');
    let statusDiv = document.getElementById('status');

    // Load saved values
    chrome.storage.local.get('config', function(result) {
        let cfg = result.config || {};
        if (cfg.apiUrl) apiUrlInput.value = cfg.apiUrl;
        if (cfg.apiKey) apiKeyInput.value = cfg.apiKey;
    });

    saveBtn.addEventListener('click', async function() {
        let apiUrl = apiUrlInput.value.trim();
        let apiKey = apiKeyInput.value.trim();

        if (!apiUrl) {
            showStatus('API URL is required', 'err');
            return;
        }

        // Save config
        chrome.storage.local.set({
            config: {
                apiUrl: apiUrl,
                apiKey: apiKey
            }
        });

        // Test connection
        showStatus('Testing...', 'ok');
        try {
            let apiOk = await fetch(apiUrl + '/api/v1/health').then(r => r.ok).catch(() => false);
            if (apiOk) {
                showStatus('OhMyCaptcha OK', 'ok');
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
