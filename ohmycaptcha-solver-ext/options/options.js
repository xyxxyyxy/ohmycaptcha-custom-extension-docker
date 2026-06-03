document.addEventListener('DOMContentLoaded', function() {
    let fields = ['apiUrl', 'apiKey', 'autoSolveRecaptchaV2', 'autoSolveHCaptcha'];

    chrome.storage.local.get('config', function(result) {
        let cfg = result.config || {};
        fields.forEach(function(key) {
            let el = document.getElementById(key);
            if (!el) return;
            if (el.type === 'checkbox') {
                el.checked = !!cfg[key];
            } else {
                el.value = cfg[key] !== undefined ? cfg[key] : el.value;
            }
        });
    });

    document.getElementById('saveBtn').addEventListener('click', function() {
        let newConfig = {};
        fields.forEach(function(key) {
            let el = document.getElementById(key);
            if (!el) return;
            newConfig[key] = el.type === 'checkbox' ? el.checked : el.value;
        });
        chrome.storage.local.set({config: newConfig}, function() {
            document.getElementById('savedMsg').style.display = 'inline';
            setTimeout(function() {
                document.getElementById('savedMsg').style.display = 'none';
            }, 2000);
        });
    });
});
