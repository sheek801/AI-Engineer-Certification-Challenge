/**
 * MacroMind UI Controller
 *
 * Two concerns:
 *   1. Dashboard mode — hide composer when dashboard charts are visible
 *   2. Onboarding overlay — show a full-screen form for new users
 *      (detected by "MACROMIND_ONBOARDING_START" anywhere in page HTML)
 */
(function () {
  "use strict";

  var dashboardActive = false;
  var onboardingShown = false;
  var onboardingCompleted = false;
  var bootGuardActive = true;
  var sidebarNavInjected = false;
  var floatDashInjected = false;

  /* ── Dashboard detection ────────────────────────────────────────── */
  function dashboardInDom() {
    return document.body.innerHTML.indexOf("MacroMind Dashboard") !== -1;
  }

  /* ── Onboarding detection ───────────────────────────────────────── */
  // Use innerHTML search — works regardless of Chainlit's CSS class names
  function onboardingNeeded() {
    if (onboardingCompleted) return false;
    return document.body.innerHTML.indexOf("MACROMIND_ONBOARDING_START") !== -1;
  }

  /* ── Hide the marker message ────────────────────────────────────── */
  function hideOnboardingMarker() {
    hideTextMarkerSafely("MACROMIND_ONBOARDING_START");
  }

  function hideTextMarkerSafely(markerText) {
    try {
      var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      var node;
      while ((node = walker.nextNode())) {
        var text = (node.textContent || "").trim();
        if (!text || text.indexOf(markerText) === -1) continue;

        var parent = node.parentElement;
        var target = null;
        if (parent && parent.closest) {
          target =
            parent.closest('[data-testid="message"]') ||
            parent.closest('[data-testid="step"]') ||
            parent.closest(".message") ||
            parent.closest(".step") ||
            parent.closest('[class*="message"]') ||
            parent.closest('[class*="step"]') ||
            parent.closest("li");
        }

        // Hide only message-level elements, never large layout wrappers.
        if (target && target !== document.body && target.offsetHeight < 320) {
          target.style.setProperty("display", "none", "important");
          continue;
        }

        // Fallback: clear marker text only.
        node.textContent = node.textContent.replace(markerText, "").trim();
      }
    } catch (e) {}
  }

  /* ── Hide the __ONBOARDING__: payload the user "sends" ──────────── */
  function watchAndHidePayload() {
    var obs = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var nodes = mutations[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          var node = nodes[j];
          if (node.nodeType !== 1) continue;
          if ((node.textContent || "").indexOf("__ONBOARDING__:") !== -1) {
            hidePayloadNodeSafely(node);
            obs.disconnect();
            return;
          }
        }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
    // Self-cleanup after 8 seconds
    setTimeout(function () { obs.disconnect(); }, 8000);
  }

  function hidePayloadNodeSafely(node) {
    // Only hide message-level elements. Never hide large layout containers.
    var selectors = [
      '[data-testid="message"]',
      '[data-testid="step"]',
      '.step',
      '.message',
      '[class*="message"]',
      '[class*="step"]',
      'li'
    ];
    var target = null;
    for (var i = 0; i < selectors.length; i++) {
      if (node.closest) {
        target = node.closest(selectors[i]);
      }
      if (target) break;
    }

    if (target && target !== document.body && target.offsetHeight < 300) {
      target.style.setProperty("display", "none", "important");
      return;
    }

    // Fallback: scrub payload text only, do not hide parent layout.
    try {
      scrubPayloadText(node);
    } catch (e) {}
  }

  function scrubPayloadText(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var current;
    while ((current = walker.nextNode())) {
      if ((current.textContent || "").indexOf("__ONBOARDING__:") !== -1) {
        current.textContent = "";
      }
    }
  }

  /* ── Inject onboarding overlay ──────────────────────────────────── */
  function injectOnboarding() {
    if (document.getElementById("mm-onboarding")) return;

    var el = document.createElement("div");
    el.id = "mm-onboarding";

    el.innerHTML = [
      '<div class="mm-ob-inner">',
      '  <div class="mm-ob-emoji">🥗</div>',
      '  <h1 class="mm-ob-title">Welcome to MacroMind</h1>',
      '  <p class="mm-ob-sub">Let\'s set up your profile to get started.</p>',
      '  <form id="mm-ob-form" class="mm-ob-form">',
      '    <div class="mm-ob-row">',
      '      <label>Units</label>',
      '      <select id="mm-ob-units">',
      '        <option value="imperial" selected>Imperial (lbs, in)</option>',
      '        <option value="metric">Metric (kg, cm)</option>',
      '      </select>',
      '    </div>',
      '    <div class="mm-ob-row">',
      '      <label id="mm-ob-weight-label">Weight (lbs)</label>',
      '      <input type="number" id="mm-ob-weight" placeholder="e.g. 185" required />',
      '    </div>',
      '    <div class="mm-ob-row">',
      '      <label id="mm-ob-height-label">Height (inches)</label>',
      '      <input type="number" id="mm-ob-height" placeholder="e.g. 70 (5\'10&quot; = 70)" required />',
      '    </div>',
      '    <div class="mm-ob-row">',
      '      <label>Age</label>',
      '      <input type="number" id="mm-ob-age" placeholder="e.g. 28" required />',
      '    </div>',
      '    <div class="mm-ob-row">',
      '      <label>Biological Sex</label>',
      '      <select id="mm-ob-sex">',
      '        <option value="male" selected>Male</option>',
      '        <option value="female">Female</option>',
      '      </select>',
      '    </div>',
      '    <div class="mm-ob-row mm-ob-full">',
      '      <label>Activity Level</label>',
      '      <select id="mm-ob-activity">',
      '        <option value="sedentary">Sedentary (desk job)</option>',
      '        <option value="light">Light (1-3 days/week)</option>',
      '        <option value="moderate" selected>Moderate (3-5 days/week)</option>',
      '        <option value="active">Active (6-7 days/week)</option>',
      '        <option value="very active">Very Active (intense daily)</option>',
      '      </select>',
      '    </div>',
      '    <div class="mm-ob-row mm-ob-full">',
      '      <label>Coaching Style</label>',
      '      <select id="mm-ob-tone">',
      '        <option value="supportive">Supportive</option>',
      '        <option value="balanced" selected>Balanced</option>',
      '        <option value="tough love">Tough Love</option>',
      '      </select>',
      '    </div>',
      '    <div class="mm-ob-divider mm-ob-full"><span>Goals (optional)</span></div>',
      '    <div class="mm-ob-row">',
      '      <label id="mm-ob-target-weight-label">Target Weight (lbs)</label>',
      '      <input type="number" id="mm-ob-target-weight" placeholder="e.g. 170" />',
      '    </div>',
      '    <div class="mm-ob-row">',
      '      <label>Target Date</label>',
      '      <input type="date" id="mm-ob-target-date" />',
      '    </div>',
      '    <button type="submit" class="mm-ob-btn mm-ob-full" id="mm-ob-submit">Save &amp; Start →</button>',
      '  </form>',
      '</div>'
    ].join("\n");

    document.body.appendChild(el);

    // Units toggle — update labels
    var unitsSelect = document.getElementById("mm-ob-units");
    unitsSelect.addEventListener("change", function () {
      var imp = unitsSelect.value === "imperial";
      document.getElementById("mm-ob-weight-label").textContent =
        imp ? "Weight (lbs)" : "Weight (kg)";
      document.getElementById("mm-ob-height-label").textContent =
        imp ? "Height (inches)" : "Height (cm)";
      document.getElementById("mm-ob-weight").placeholder =
        imp ? "e.g. 185" : "e.g. 84";
      document.getElementById("mm-ob-height").placeholder =
        imp ? 'e.g. 70 (5\'10" = 70)' : "e.g. 178";
      document.getElementById("mm-ob-target-weight-label").textContent =
        imp ? "Target Weight (lbs)" : "Target Weight (kg)";
      document.getElementById("mm-ob-target-weight").placeholder =
        imp ? "e.g. 170" : "e.g. 77";
    });

    // Form submission
    document.getElementById("mm-ob-form").addEventListener("submit", function (e) {
      e.preventDefault();
      submitOnboarding();
    });
  }

  function submitOnboarding() {
    var submitBtn = document.getElementById("mm-ob-submit");
    var payload = {
      units:         document.getElementById("mm-ob-units").value,
      weight:        document.getElementById("mm-ob-weight").value,
      height:        document.getElementById("mm-ob-height").value,
      age:           document.getElementById("mm-ob-age").value,
      sex:           document.getElementById("mm-ob-sex").value,
      activity:      document.getElementById("mm-ob-activity").value,
      tone:          document.getElementById("mm-ob-tone").value,
      target_weight: document.getElementById("mm-ob-target-weight").value || "",
      target_date:   document.getElementById("mm-ob-target-date").value || "",
    };

    if (!payload.units || !payload.weight || !payload.height || !payload.age || !payload.sex || !payload.activity) {
      alert("Please fill in all required fields.");
      return;
    }
    if ((payload.target_weight && !payload.target_date) || (!payload.target_weight && payload.target_date)) {
      alert("Please provide both target weight and target date, or leave both blank.");
      return;
    }

    var sent = sendOnboardingPayload(payload);
    if (!sent) {
      alert("Could not submit onboarding yet. Please wait one second and try again.");
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Saving profile...";
    }
    onboardingCompleted = true;
    watchAndHidePayload();
    removeOnboarding();
  }

  function sendOnboardingPayload(payload) {
    var message = "__ONBOARDING__:" + JSON.stringify(payload);
    var chatInput =
      document.getElementById("chat-input") ||
      document.querySelector('#chat-input textarea') ||
      document.querySelector('textarea#chat-input') ||
      document.querySelector('textarea[placeholder*="message" i]') ||
      document.querySelector('textarea[aria-label*="message" i]') ||
      document.querySelector('textarea');
    if (!chatInput) return false;

    try {
      if ("value" in chatInput) {
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype,
          "value"
        ).set;
        nativeInputValueSetter.call(chatInput, message);
        chatInput.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (chatInput.isContentEditable) {
        chatInput.textContent = message;
        chatInput.dispatchEvent(new Event("input", { bubbles: true }));
      } else {
        return false;
      }
    } catch (e) {
      return false;
    }

    setTimeout(function () {
      var sendBtn =
        document.querySelector('button[data-testid="send-button"]') ||
        document.querySelector('button[aria-label*="send" i]') ||
        document.querySelector('button[type="submit"]');
      if (sendBtn) {
        sendBtn.click();
        return;
      }
      chatInput.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          code: "Enter",
          bubbles: true
        })
      );
    }, 80);

    return true;
  }

  function removeOnboarding() {
    // 1. Hide the marker message BEFORE removing onboarding-mode
    hideOnboardingMarker();
    // 2. Remove overlay element
    var el = document.getElementById("mm-onboarding");
    if (el) el.remove();
    // 3. Remove body classes
    document.body.classList.remove("onboarding-mode");
    onboardingShown = false;
    // 4. Double-check marker is hidden after React may re-render
    setTimeout(hideOnboardingMarker, 400);
    setTimeout(hideOnboardingMarker, 1000);
  }

  /* ── Main state machine ─────────────────────────────────────────── */
  function applyState() {
    injectSidebarModeNav();
    injectFloatingDashboard();

    // ── Dashboard detection ──
    var isDash = dashboardInDom();
    if (isDash) {
      if (!dashboardActive) {
        dashboardActive = true;
        document.body.classList.add("dashboard-mode");
      }
      releaseBootGuard();
      return;
    }
    if (dashboardActive) {
      dashboardActive = false;
      document.body.classList.remove("dashboard-mode");
    }

    // ── Onboarding detection ──
    if (!onboardingCompleted && onboardingNeeded() && !onboardingShown) {
      onboardingShown = true;
      // Add body class IMMEDIATELY so CSS hides all message steps
      document.body.classList.add("onboarding-mode");
      releaseBootGuard();
      // Hide the text marker
      hideOnboardingMarker();
      // Inject the overlay form
      injectOnboarding();
      return;
    }

    // If chat starts rendering and onboarding marker is not present, release boot guard.
    if (!onboardingNeeded() && chatHasRendered()) {
      releaseBootGuard();
    }

    updateSidebarModeNavState();
  }

  function injectFloatingDashboard() {
    if (floatDashInjected) return;
    if (document.getElementById("mm-float-dashboard")) return;

    // Keep this visible even if Chainlit sidebar DOM isn't available.
    var btn = document.createElement("button");
    btn.id = "mm-float-dashboard";
    btn.type = "button";
    btn.textContent = "Dashboard";
    btn.className = "mm-float-dashboard-btn";

    btn.addEventListener("click", function () {
      // Render dashboard inline as a message; do not switch profiles.
      sendSilentMessage("__DASHBOARD__");
    });

    document.body.appendChild(btn);
    floatDashInjected = true;
  }

  function injectSidebarModeNav() {
    if (sidebarNavInjected || document.getElementById("mm-mode-nav")) return;
    var sidebar = document.querySelector('[data-testid="sidebar"]') || document.querySelector("aside");
    if (!sidebar) return;

    var host =
      sidebar.querySelector('[data-testid="sidebar-content"]') ||
      sidebar.querySelector(".flex.flex-col") ||
      sidebar;
    if (!host) return;

    var nav = document.createElement("div");
    nav.id = "mm-mode-nav";
    nav.innerHTML = [
      '<div class="mm-mode-title">Workspace</div>',
      '<button type="button" class="mm-mode-btn" data-mm-profile="Chat">Chat</button>',
      '<button type="button" class="mm-mode-btn" data-mm-profile="Dashboard">Dashboard</button>'
    ].join("");
    host.prepend(nav);
    document.body.classList.add("mm-sidebar-nav-ready");

    var btns = nav.querySelectorAll(".mm-mode-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function (e) {
        var target = e.currentTarget.getAttribute("data-mm-profile");
        if (target === "Dashboard") {
          sendSilentMessage("__DASHBOARD__");
        }
        // Chat button does nothing — user is already in chat
      });
    }

    sidebarNavInjected = true;
    updateSidebarModeNavState();
  }

  function updateSidebarModeNavState() {
    var nav = document.getElementById("mm-mode-nav");
    if (!nav) return;
    var current = getCurrentProfileName();
    var btns = nav.querySelectorAll(".mm-mode-btn");
    for (var i = 0; i < btns.length; i++) {
      var active = btns[i].getAttribute("data-mm-profile") === current;
      btns[i].classList.toggle("active", !!active);
    }
  }

  function getCurrentProfileName() {
    if (dashboardActive) return "Dashboard";
    return "Chat";
  }

  function sendSilentMessage(text) {
    var chatInput =
      document.getElementById("chat-input") ||
      document.querySelector("textarea#chat-input") ||
      document.querySelector('textarea[placeholder*="message" i]') ||
      document.querySelector("textarea");
    if (!chatInput) return;
    try {
      var setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value"
      ).set;
      setter.call(chatInput, text);
      chatInput.dispatchEvent(new Event("input", { bubbles: true }));
    } catch (e) { return; }
    setTimeout(function () {
      var sendBtn =
        document.querySelector('button[data-testid="send-button"]') ||
        document.querySelector('button[aria-label*="send" i]') ||
        document.querySelector('button[type="submit"]');
      if (sendBtn) { sendBtn.click(); return; }
      chatInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    }, 60);
  }

  function chatHasRendered() {
    return (
      document.querySelector('[data-testid="message"]') ||
      document.querySelector('[data-testid="step"]') ||
      document.querySelector("#chat-input") ||
      document.querySelector("#message-composer")
    );
  }

  function releaseBootGuard() {
    if (!bootGuardActive) return;
    bootGuardActive = false;
    document.body.classList.remove("mm-booting");
  }

  /* ── Init ────────────────────────────────────────────────────────── */
  function startPolling() {
    document.body.classList.add("mm-booting");
    // Run immediately, then cascade checks for the first 2 seconds
    applyState();
    setTimeout(applyState, 50);
    setTimeout(applyState, 150);
    setTimeout(applyState, 350);
    setTimeout(applyState, 700);
    setTimeout(applyState, 1200);
    setTimeout(applyState, 2000);
    // Safety release for returning users so the app never stays hidden.
    setTimeout(releaseBootGuard, 1800);
  }

  function startObserver() {
    if (!document.body) return;
    var observer = new MutationObserver(applyState);
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      startObserver();
      startPolling();
    });
  } else {
    // DOM already ready
    startObserver();
    startPolling();
  }

  // Steady-state poll (every 1.5s) to catch any edge cases
  setInterval(applyState, 1500);
})();
