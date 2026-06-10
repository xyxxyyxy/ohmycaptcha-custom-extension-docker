// OhMyCaptcha Solver - Service Worker
// Sends ALL tasks to OhMyCaptcha bridge at :1231
// OhMyCaptcha handles routing (image -> shim, token -> CDP Brave)

const SW_LOG = "[OhMyCaptcha:SW]";

chrome.runtime.onInstalled.addListener(() => {
    console.log(SW_LOG, "Extension installed");
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "solve") {
        handleSolve(request.params, sendResponse);
        return true; // async
    }
    if (request.action === "getConfig") {
        getConfig().then(sendResponse);
        return true;
    }
    if (request.action === "healthCheck") {
        healthCheck(sendResponse);
        return true;
    }
});

async function healthCheck(sendResponse) {
    // Check connectivity to the bridge
    let config = await getConfig();
    let apiUrl = config.apiUrl || "http://localhost:1231";
    
    console.log(SW_LOG, "Health check to:", apiUrl);
    
    try {
        let controller = new AbortController();
        let timeout = setTimeout(() => controller.abort(), 5000);
        let res = await fetch(apiUrl + "/api/v1/health", {
            method: "GET",
            signal: controller.signal
        });
        clearTimeout(timeout);
        
        if (!res.ok) {
            sendResponse({reachable: false, url: apiUrl, error: "HTTP " + res.status});
            return;
        }
        
        let data = await res.json();
        console.log(SW_LOG, "Health check OK:", JSON.stringify(data));
        sendResponse({reachable: true, url: apiUrl, bridgeInfo: data});
    } catch (err) {
        console.error(SW_LOG, "Health check FAILED:", err.message);
        sendResponse({reachable: false, url: apiUrl, error: err.message});
    }
}

async function ensureHostPermission(url) {
    // Chrome MV3: request explicit permission for the bridge URL
    try {
        let urlObj = new URL(url);
        let permission = { origins: [urlObj.origin + "/*"] };
        let hasPermission = await chrome.permissions.contains(permission);
        if (!hasPermission) {
            console.log(SW_LOG, "Requesting permission for:", urlObj.origin);
            let granted = await chrome.permissions.request(permission);
            if (!granted) {
                console.error(SW_LOG, "Permission DENIED for:", urlObj.origin);
                return false;
            }
            console.log(SW_LOG, "Permission GRANTED for:", urlObj.origin);
        }
        return true;
    } catch (e) {
        console.warn(SW_LOG, "Permission check failed:", e.message);
        // Continue anyway - might still work with existing permissions
        return true;
    }
}

async function handleSolve(params, sendResponse) {
    let config = await getConfig();
    let apiUrl = config.apiUrl || "http://localhost:1231";
    let apiKey = config.apiKey || "local";

    console.log(SW_LOG, "=== SOLVE START ===");
    console.log(SW_LOG, "API URL:", apiUrl);
    console.log(SW_LOG, "CAPTCHA type:", params.captchaType, "version:", params.version);

    // Ensure we have permission to access the bridge
    let hasPerm = await ensureHostPermission(apiUrl);
    if (!hasPerm) {
        sendResponse({success: false, error: "Permission denied for " + apiUrl + ". Click the extension icon and allow access."});
        return;
    }

    // Build YesCaptcha task from widget params
    let task = buildTask(params);
    console.log(SW_LOG, "Task:", JSON.stringify(task));

    try {
        // Step 1: createTask
        console.log(SW_LOG, "Step 1: Creating task...");
        let createRes = await fetch(apiUrl + "/createTask", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                clientKey: apiKey,
                task: task
            })
        });
        
        if (!createRes.ok) {
            let errText = await createRes.text();
            console.error(SW_LOG, "createTask HTTP error:", createRes.status, errText);
            sendResponse({success: false, error: "Bridge HTTP " + createRes.status + ": " + errText});
            return;
        }
        
        let createData = await createRes.json();
        console.log(SW_LOG, "createTask response:", JSON.stringify(createData));

        if (createData.errorId !== 0 && createData.errorId !== undefined) {
            console.error(SW_LOG, "createTask API error:", createData.errorDescription);
            sendResponse({success: false, error: createData.errorDescription || "API error"});
            return;
        }

        // If answer returned immediately
        if (createData.status === "ready" && createData.solution) {
            let answer = extractAnswer(createData.solution);
            console.log(SW_LOG, "Immediate answer:", answer.substring(0, 50) + "...");
            sendResponse({success: true, answer: answer});
            return;
        }

        // Step 2: poll getTaskResult
        let taskId = createData.taskId;
        if (!taskId) {
            console.error(SW_LOG, "No taskId in response");
            sendResponse({success: false, error: "No taskId returned"});
            return;
        }
        console.log(SW_LOG, "Step 2: Polling for taskId:", taskId);

        let result = await pollResult(apiUrl, apiKey, taskId);
        console.log(SW_LOG, "=== SOLVE END === result:", result.success ? "SUCCESS" : "FAILED", result.error || "");
        sendResponse(result);

    } catch (err) {
        console.error(SW_LOG, "solve error:", err);
        sendResponse({success: false, error: err.message});
    }
}

async function pollResult(apiUrl, apiKey, taskId) {
    let maxAttempts = 90; // 90 * 2s = 180s max (CAPTCHA solving takes time)
    let delay = 2000;

    for (let i = 0; i < maxAttempts; i++) {
        await sleep(delay);

        let res;
        try {
            res = await fetch(apiUrl + "/getTaskResult", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    clientKey: apiKey,
                    taskId: taskId
                })
            });
        } catch (err) {
            console.error(SW_LOG, "Poll fetch error:", err.message);
            continue;
        }
        
        let data = await res.json();

        if (data.status === "ready" && data.solution) {
            let answer = extractAnswer(data.solution);
            console.log(SW_LOG, "Poll success after", (i+1)*2, "s, answer length:", answer.length);
            return {success: true, answer: answer};
        }
        if (data.errorId !== 0 && data.errorId !== undefined) {
            console.error(SW_LOG, "Poll error after", (i+1)*2, "s:", data.errorDescription);
            return {success: false, error: data.errorDescription || "Task failed"};
        }
        
        // Log progress every 15 polls (30 seconds)
        if ((i + 1) % 15 === 0) {
            console.log(SW_LOG, "Still polling...", (i+1)*2, "s elapsed, status:", data.status);
        }
    }

    console.error(SW_LOG, "Polling timeout after", maxAttempts * 2, "seconds");
    return {success: false, error: "Polling timeout - check server logs"};
}

function buildTask(params) {
    let type = params.captchaType;

    if (type === "normal") {
        return {
            type: "ImageToTextTask",
            body: params.base64 || params.body || "",
            phrase: false
        };
    }

    if (type === "recaptcha") {
        if (params.version === "v3") {
            return {
                type: "RecaptchaV3TaskProxyless",
                websiteURL: params.url,
                websiteKey: params.sitekey,
                minScore: params.score || 0.5,
                pageAction: params.action || ""
            };
        }
        // Explicit image-classification request (e.g. user clicked "solve images")
        if (params.imageClassification) {
            return {
                type: "ReCaptchaV2Classification",
                websiteURL: params.url,
                websiteKey: params.sitekey
            };
        }
        if (params.invisible || params.version === "v2_invisible") {
            return {
                type: "RecaptchaV2TaskProxyless",
                websiteURL: params.url,
                websiteKey: params.sitekey,
                isInvisible: true
            };
        }
        return {
            type: "RecaptchaV2TaskProxyless",
            websiteURL: params.url,
            websiteKey: params.sitekey
        };
    }

    if (type === "hcaptcha") {
        return {
            type: "HCaptchaTaskProxyless",
            websiteURL: params.url,
            websiteKey: params.sitekey
        };
    }

    if (type === "turnstile") {
        return {
            type: "TurnstileTaskProxyless",
            websiteURL: params.url,
            websiteKey: params.sitekey
        };
    }

    return {type: "ImageToTextTask", body: "", phrase: false};
}

function extractAnswer(solution) {
    if (typeof solution === "string") return solution;
    if (solution.text) return solution.text;
    if (solution.gRecaptchaResponse) return solution.gRecaptchaResponse;
    if (solution.token) return solution.token;
    return JSON.stringify(solution);
}

async function getConfig() {
    return new Promise(resolve => {
        chrome.storage.local.get('config', result => {
            resolve(result.config || {});
        });
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
