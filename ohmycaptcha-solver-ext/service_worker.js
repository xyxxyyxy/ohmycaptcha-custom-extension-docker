// OhMyCaptcha Solver - Service Worker
// Sends ALL tasks to OhMyCaptcha bridge at :1231
// OhMyCaptcha handles routing (image -> shim, token -> CDP Brave)

chrome.runtime.onInstalled.addListener(() => {
    console.log("[OhMyCaptcha] Extension installed");
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
});

async function handleSolve(params, sendResponse) {
    let config = await getConfig();
    let apiUrl = config.apiUrl || "http://localhost:1231";
    let apiKey = config.apiKey || "local";

    // Build YesCaptcha task from widget params
    let task = buildTask(params);

    try {
        // Step 1: createTask
        let createRes = await fetch(apiUrl + "/createTask", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                clientKey: apiKey,
                task: task
            })
        });
        let createData = await createRes.json();

        if (createData.errorId !== 0 && createData.errorId !== undefined) {
            sendResponse({success: false, error: createData.errorDescription || "API error"});
            return;
        }

        // If answer returned immediately
        if (createData.status === "ready" && createData.solution) {
            sendResponse({success: true, answer: extractAnswer(createData.solution)});
            return;
        }

        // Step 2: poll getTaskResult
        let taskId = createData.taskId;
        if (!taskId) {
            sendResponse({success: false, error: "No taskId returned"});
            return;
        }

        let result = await pollResult(apiUrl, apiKey, taskId);
        sendResponse(result);

    } catch (err) {
        console.error("[OhMyCaptcha] solve error:", err);
        sendResponse({success: false, error: err.message});
    }
}

async function pollResult(apiUrl, apiKey, taskId) {
    let maxAttempts = 60;
    let delay = 2000;

    for (let i = 0; i < maxAttempts; i++) {
        await sleep(delay);

        let res = await fetch(apiUrl + "/getTaskResult", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                clientKey: apiKey,
                taskId: taskId
            })
        });
        let data = await res.json();

        if (data.status === "ready" && data.solution) {
            return {success: true, answer: extractAnswer(data.solution)};
        }
        if (data.errorId !== 0 && data.errorId !== undefined) {
            return {success: false, error: data.errorDescription || "Task failed"};
        }
    }

    return {success: false, error: "Polling timeout"};
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
