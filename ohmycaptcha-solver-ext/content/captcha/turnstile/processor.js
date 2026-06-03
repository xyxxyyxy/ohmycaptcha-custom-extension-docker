CaptchaProcessors.register({

 captchaType: "turnstile",

 canBeProcessed: function(widget, config) {
 if (!config.enabledForTurnstile) return false;
 return true;
 },

 attachButton: function(widget, config, button) {
 let input = $("#" + widget.inputId);
 input.after(button);
 if (config.autoSolveTurnstile) button.click();
 },

 getParams: function(widget, config) {
 return {
 url: location.href,
 sitekey: widget.sitekey,
 };
 },

 onSolved: function(widget, answer) {
 let input = document.getElementById(widget.inputId);
 if (input) input.value = answer;
 },

 getForm: function(widget) {
 return $("#" + widget.inputId).closest("form");
 },

 getCallback: function(widget) {
 return null;
 },

});