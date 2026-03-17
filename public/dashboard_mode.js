/**
 * MacroMind: Hide the chat composer when the Dashboard profile is active.
 *
 * Two detection strategies:
 *   1. Content-based: look for "MacroMind Dashboard" in rendered messages.
 *   2. Profile selector: scan buttons for the active "Dashboard" profile name.
 *
 * Toggles a body class that CSS targets to hide the composer.
 */
(function () {
  "use strict";

  var currentMode = null;

  function detectAndApply() {
    var isDashboard = false;

    // Method 1 (primary): Check rendered message content for dashboard heading.
    // render_dashboard() always produces "MacroMind Dashboard".
    var allEls = document.querySelectorAll(
      '[class*="message"], [class*="step"], [class*="markdown"], h2'
    );
    for (var i = 0; i < allEls.length; i++) {
      if (allEls[i].textContent.indexOf("MacroMind Dashboard") !== -1) {
        isDashboard = true;
        break;
      }
    }

    // Method 2 (fallback): Look for profile selector button showing "Dashboard".
    if (!isDashboard) {
      var buttons = document.querySelectorAll("button, [role='button']");
      for (var j = 0; j < buttons.length; j++) {
        var el = buttons[j];
        var text = (el.textContent || "").trim();
        if (
          text === "Dashboard" &&
          el.closest(
            "[class*='profile'], [class*='select'], [class*='header']"
          )
        ) {
          isDashboard = true;
          break;
        }
      }
    }

    // Apply / remove the class
    var newMode = isDashboard ? "dashboard" : "chat";
    if (newMode !== currentMode) {
      currentMode = newMode;
      if (isDashboard) {
        document.body.classList.add("dashboard-mode");
      } else {
        document.body.classList.remove("dashboard-mode");
      }
    }
  }

  // Run immediately, then observe DOM mutations for profile switches.
  detectAndApply();

  var observer = new MutationObserver(detectAndApply);
  observer.observe(document.body, { childList: true, subtree: true });

  // Belt-and-suspenders: also poll every second.
  setInterval(detectAndApply, 1000);
})();
