(() => {

 let turnstileInstance;

 Object.defineProperty(window, "turnstile", {
 configurable: true,
 get: function () {
 return turnstileInstance;
 },
 set: function (e) {
 turnstileInstance = e;

 let originalRenderFunc = e.render;

 e.render = function (container, opts) {
 createTurnstileWidget(container, opts);
 return originalRenderFunc(container, opts);
 };
 },
 });

 let createTurnstileWidget = function (container, opts) {
 if (typeof container !== 'string') {
 if (!container.id) {
 container.id = "turnstile-container-" + Date.now();
 }
 container = container.id;
 }

 let widgetInfo = {
 captchaType: "turnstile",
 widgetId: container,
 sitekey: opts.sitekey,
 callback: opts.callback,
 };

 let iter = 0;
 const intId = setInterval(() => {
 if (++iter > 200) clearInterval(intId);
 if (window.registerCaptchaWidget) {
 clearInterval(intId);
 registerCaptchaWidget(widgetInfo);
 }
 }, 500)
 }

})()