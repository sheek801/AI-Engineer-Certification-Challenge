/**
 * MacroMind: Hide the chat composer when the Dashboard profile is active.
 *
 * Chainlit doesn't expose the active profile as a DOM attribute, so we
 * use a MutationObserver to watch for profile-related UI changes and
 * toggle a body class that CSS can target.
 */
(function () {
  "use strict";

  let currentMode = null;

  function detectAndApply() {
    // Strategy: The Chainlit profile selector renders the active profile
    // name as text inside a button or similar control.  We look for the
    // profile names we defined ("Chat" / "Dashboard") in clickable
    // elements near the top of the page.  The active profile is shown
    // in the header area.
    //
    // We also check if the page contains our dashboard markdown heading
    // as a fallback signal.

    let isDashboard = false;

    // Method 1: Look for the profile selector — it's typically a
    // button/div in the header that shows the current profile name.
    // Chainlit renders it with a specific aria pattern.
    const headerEls = document.querySelectorAll(
      'header button, header [role="button"], nav button, nav [role="button"]'
    );
    for (const el of headerEls) {
      const text = (el.textContent || "").trim();
      if (text === "Dashboard") {
        isDashboard = true;
        break;
      }
    }

    // Method 2: Check all buttons (Chainlit sometimes renders
    // the profile selector outside a semantic header).
    if (!isDashboard) {
      const allBtns = document.querySelectorAll('button');
      for (const btn of allBtns) {
        // The active profile button typically has an icon + name.
        // We look for a button whose ONLY text content is "Dashboard"
        // (to avoid matching our "Switch to Chat" starter).
        const spans = btn.querySelectorAll('span, p, div');
        for (const s of spans) {
          if (s.textContent.trim() === "Dashboard" && btn.closest('[class*="profile"], [class*="header"], [class*="select"]')) {
            isDashboard = true;
            break;
          }
        }
        if (isDashboard) break;
      }
    }

    // Apply / remove the class
    const newMode = isDashboard ? "dashboard" : "chat";
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

  const observer = new MutationObserver(detectAndApply);
  observer.observe(document.body, { childList: true, subtree: true });

  // Belt-and-suspenders: also poll every second in case mutations miss it.
  setInterval(detectAndApply, 1000);
})();
