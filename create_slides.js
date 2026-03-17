const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// Icon imports
const {
  FaUtensils, FaBrain, FaChartLine, FaDatabase,
  FaSearch, FaUser, FaClipboardList, FaFire,
  FaCheckCircle, FaTimes, FaCamera, FaBullseye,
  FaGoogle, FaEnvelope, FaMobileAlt, FaRobot,
  FaArrowRight, FaStar, FaLock
} = require("react-icons/fa");

// ── Icon utility ──────────────────────────────────────────────────────
function renderIconSvg(IconComponent, color = "#000000", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// ── Color Palette: Warm Nutrition Theme ──────────────────────────────
// Primary: Deep navy for authority and trust
// Secondary: Warm orange for energy and nutrition
// Accent: Fresh green for health
const COLORS = {
  navy: "1B2A4A",
  darkNavy: "0F1B33",
  orange: "FF6B35",
  orangeLight: "FF8C5A",
  green: "2ECC71",
  greenDark: "27AE60",
  white: "FFFFFF",
  offWhite: "F8F9FA",
  lightGray: "E9ECEF",
  medGray: "6C757D",
  darkText: "212529",
  subtleText: "495057",
};

const makeShadow = () => ({
  type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.12
});

async function main() {
  let pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "Risheek Somu";
  pres.title = "MacroMind - AI Nutrition Intelligence";

  // Pre-render icons
  const iconUtensils = await iconToBase64Png(FaUtensils, "#FFFFFF");
  const iconBrain = await iconToBase64Png(FaBrain, "#FF6B35");
  const iconChart = await iconToBase64Png(FaChartLine, "#FFFFFF");
  const iconDatabase = await iconToBase64Png(FaDatabase, "#FFFFFF");
  const iconSearch = await iconToBase64Png(FaSearch, "#FF6B35");
  const iconUser = await iconToBase64Png(FaUser, "#FF6B35");
  const iconClipboard = await iconToBase64Png(FaClipboardList, "#FF6B35");
  const iconFire = await iconToBase64Png(FaFire, "#FF6B35");
  const iconCheck = await iconToBase64Png(FaCheckCircle, "#2ECC71");
  const iconX = await iconToBase64Png(FaTimes, "#E74C3C");
  const iconCamera = await iconToBase64Png(FaCamera, "#FF6B35");
  const iconBullseye = await iconToBase64Png(FaBullseye, "#FF6B35");
  const iconGoogle = await iconToBase64Png(FaGoogle, "#FF6B35");
  const iconEnvelope = await iconToBase64Png(FaEnvelope, "#FF6B35");
  const iconMobile = await iconToBase64Png(FaMobileAlt, "#FF6B35");
  const iconRobot = await iconToBase64Png(FaRobot, "#FFFFFF");
  const iconArrow = await iconToBase64Png(FaArrowRight, "#FF6B35");
  const iconStar = await iconToBase64Png(FaStar, "#FF6B35");
  const iconLock = await iconToBase64Png(FaLock, "#FFFFFF");

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 1: TITLE / HOOK
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.darkNavy };

    // Subtle top accent bar
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 10, h: 0.06, fill: { color: COLORS.orange }
    });

    // Robot icon top-center
    slide.addImage({ data: iconRobot, x: 4.65, y: 0.7, w: 0.7, h: 0.7 });

    // Title
    slide.addText("MacroMind", {
      x: 0.5, y: 1.5, w: 9, h: 0.9,
      fontSize: 48, fontFace: "Georgia", bold: true,
      color: COLORS.white, align: "center", margin: 0
    });

    // Subtitle
    slide.addText("An AI nutritionist that remembers you.", {
      x: 0.5, y: 2.4, w: 9, h: 0.6,
      fontSize: 22, fontFace: "Calibri",
      color: COLORS.orangeLight, align: "center", italic: true, margin: 0
    });

    // Hook quote
    slide.addText([
      { text: '"You downloaded the app. You tracked for a week.', options: { breakLine: true } },
      { text: 'Then life happened."', options: {} }
    ], {
      x: 1.5, y: 3.4, w: 7, h: 0.9,
      fontSize: 16, fontFace: "Calibri",
      color: COLORS.medGray, align: "center"
    });

    // Bottom bar with author
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 5.0, w: 10, h: 0.625, fill: { color: COLORS.navy }
    });
    slide.addText("Risheek Somu  |  AI Engineering Bootcamp (AIE9)  |  Demo Day 2025", {
      x: 0.5, y: 5.05, w: 9, h: 0.5,
      fontSize: 12, fontFace: "Calibri",
      color: COLORS.medGray, align: "center"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 2: THE PROBLEM
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.offWhite };

    // Title
    slide.addText("Nutrition Tools Are Broken", {
      x: 0.6, y: 0.3, w: 8.8, h: 0.7,
      fontSize: 36, fontFace: "Georgia", bold: true,
      color: COLORS.darkNavy, align: "left", margin: 0
    });

    // Problem cards — 3 columns
    const problems = [
      { title: "MyFitnessPal", desc: "Backward-looking logging.\nYou track what you already ate.\nNo intelligence. No strategy.", yIcon: 1.35 },
      { title: "ChatGPT", desc: "Smart, but forgets everything.\nEvery conversation resets.\nNo tracking, no persistence.", yIcon: 1.35 },
      { title: "Rigid Meal Plans", desc: "Break when real life happens.\nOne missed day = start over.\nDoesn't adapt to you.", yIcon: 1.35 },
    ];

    const cardW = 2.7;
    const gap = 0.35;
    const startX = 0.6;
    problems.forEach((p, i) => {
      const cx = startX + i * (cardW + gap);
      // Card background
      slide.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: 1.2, w: cardW, h: 2.2,
        fill: { color: COLORS.white }, shadow: makeShadow()
      });
      // Red X icon
      slide.addImage({ data: iconX, x: cx + 1.1, y: 1.35, w: 0.45, h: 0.45 });
      // Card title
      slide.addText(p.title, {
        x: cx + 0.15, y: 1.85, w: cardW - 0.3, h: 0.4,
        fontSize: 16, fontFace: "Calibri", bold: true,
        color: COLORS.darkNavy, align: "center", margin: 0
      });
      // Card desc
      slide.addText(p.desc, {
        x: cx + 0.15, y: 2.25, w: cardW - 0.3, h: 1.0,
        fontSize: 12, fontFace: "Calibri",
        color: COLORS.subtleText, align: "center", margin: 0
      });
    });

    // Stat callout
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 3.7, w: 8.8, h: 1.1,
      fill: { color: COLORS.darkNavy }
    });
    slide.addText([
      { text: "23M+ ", options: { fontSize: 32, bold: true, color: COLORS.orange } },
      { text: "Americans actively trying to lose weight. ", options: { fontSize: 18, color: COLORS.white } },
      { text: "Most quit within 2 weeks.", options: { fontSize: 18, color: COLORS.medGray, italic: true } },
    ], {
      x: 0.8, y: 3.8, w: 8.4, h: 0.9,
      fontFace: "Calibri", valign: "middle", align: "center"
    });

    // Bottom caption
    slide.addText("The gap: no tool is conversational, persistent, AND intelligent.", {
      x: 0.6, y: 5.0, w: 8.8, h: 0.4,
      fontSize: 13, fontFace: "Calibri", italic: true,
      color: COLORS.medGray, align: "center"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 3: THE SOLUTION
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.darkNavy };

    // Orange accent bar at top
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 10, h: 0.06, fill: { color: COLORS.orange }
    });

    slide.addText("MacroMind: The Solution", {
      x: 0.6, y: 0.3, w: 8.8, h: 0.7,
      fontSize: 36, fontFace: "Georgia", bold: true,
      color: COLORS.white, align: "left", margin: 0
    });

    slide.addText("An AI nutritionist that remembers you.", {
      x: 0.6, y: 0.95, w: 8.8, h: 0.4,
      fontSize: 18, fontFace: "Calibri", italic: true,
      color: COLORS.orangeLight, align: "left", margin: 0
    });

    // Feature grid — 2 columns, 2 rows
    const features = [
      { icon: iconBrain, title: "Conversational", desc: "Just text what you ate. No forms, no barcode scanning, no friction." },
      { icon: iconLock, title: "Persistent Memory", desc: "Knows your profile, history, and goals across every session." },
      { icon: iconDatabase, title: "7 Specialized Tools", desc: "USDA data, web search, meal logging, TDEE calc, recipes, progress analysis." },
      { icon: iconChart, title: "Visual Dashboard", desc: "Interactive charts for calories, macros, streaks, and weekly trends." },
    ];

    const fCardW = 4.2;
    const fCardH = 1.4;
    features.forEach((f, i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const fx = 0.6 + col * (fCardW + 0.4);
      const fy = 1.6 + row * (fCardH + 0.3);

      // Card bg
      slide.addShape(pres.shapes.RECTANGLE, {
        x: fx, y: fy, w: fCardW, h: fCardH,
        fill: { color: COLORS.navy }
      });

      // Icon in orange circle
      slide.addShape(pres.shapes.OVAL, {
        x: fx + 0.2, y: fy + 0.35, w: 0.7, h: 0.7,
        fill: { color: COLORS.orange }
      });
      slide.addImage({ data: f.icon, x: fx + 0.35, y: fy + 0.5, w: 0.4, h: 0.4 });

      // Title
      slide.addText(f.title, {
        x: fx + 1.1, y: fy + 0.15, w: fCardW - 1.3, h: 0.4,
        fontSize: 16, fontFace: "Calibri", bold: true,
        color: COLORS.white, align: "left", margin: 0
      });

      // Desc
      slide.addText(f.desc, {
        x: fx + 1.1, y: fy + 0.55, w: fCardW - 1.3, h: 0.7,
        fontSize: 12, fontFace: "Calibri",
        color: COLORS.medGray, align: "left", margin: 0
      });
    });

    // Bottom callout
    slide.addText("Built with LangGraph + GPT-4o-mini + SQLite + Chainlit", {
      x: 0.6, y: 5.0, w: 8.8, h: 0.4,
      fontSize: 12, fontFace: "Calibri",
      color: COLORS.medGray, align: "center"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 4: HOW IT WORKS
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.offWhite };

    slide.addText("How It Works", {
      x: 0.6, y: 0.3, w: 8.8, h: 0.7,
      fontSize: 36, fontFace: "Georgia", bold: true,
      color: COLORS.darkNavy, align: "left", margin: 0
    });

    // Flow: User → Agent → Tools → Response
    const steps = [
      { label: "User Texts", sub: '"I had chicken\nsalad for lunch"', color: COLORS.navy },
      { label: "Agent Reasons", sub: "Picks the right\ntool automatically", color: COLORS.orange },
      { label: "Tools Execute", sub: "Logs meal, looks\nup macros, updates", color: COLORS.greenDark },
      { label: "Smart Response", sub: "Personalized reply\nwith your stats", color: COLORS.navy },
    ];

    const stepW = 2.0;
    const stepH = 1.8;
    const stepGap = 0.35;
    const stepsStartX = 0.6;
    const stepsY = 1.2;

    steps.forEach((s, i) => {
      const sx = stepsStartX + i * (stepW + stepGap);

      // Step circle
      slide.addShape(pres.shapes.OVAL, {
        x: sx + 0.65, y: stepsY, w: 0.7, h: 0.7,
        fill: { color: s.color }
      });
      slide.addText(String(i + 1), {
        x: sx + 0.65, y: stepsY, w: 0.7, h: 0.7,
        fontSize: 22, fontFace: "Calibri", bold: true,
        color: COLORS.white, align: "center", valign: "middle", margin: 0
      });

      // Arrow (except last)
      if (i < steps.length - 1) {
        slide.addImage({
          data: iconArrow,
          x: sx + stepW + 0.04, y: stepsY + 0.15, w: 0.3, h: 0.3
        });
      }

      // Label
      slide.addText(s.label, {
        x: sx, y: stepsY + 0.85, w: stepW, h: 0.35,
        fontSize: 15, fontFace: "Calibri", bold: true,
        color: COLORS.darkNavy, align: "center", margin: 0
      });

      // Sub text
      slide.addText(s.sub, {
        x: sx, y: stepsY + 1.2, w: stepW, h: 0.6,
        fontSize: 11, fontFace: "Calibri",
        color: COLORS.subtleText, align: "center", margin: 0
      });
    });

    // Tools grid below
    slide.addText("7 Specialized Agent Tools", {
      x: 0.6, y: 3.3, w: 8.8, h: 0.45,
      fontSize: 18, fontFace: "Calibri", bold: true,
      color: COLORS.darkNavy, align: "center", margin: 0
    });

    // Pre-render tool icons in white
    const iconSearchW = await iconToBase64Png(FaSearch, "#FFFFFF");
    const iconClipboardW = await iconToBase64Png(FaClipboardList, "#FFFFFF");
    const iconUserW = await iconToBase64Png(FaUser, "#FFFFFF");
    const iconChartW = await iconToBase64Png(FaChartLine, "#FFFFFF");
    const iconStarW = await iconToBase64Png(FaStar, "#FFFFFF");
    const iconDatabaseW = await iconToBase64Png(FaDatabase, "#FFFFFF");

    const tools = [
      { icon: iconSearchW, name: "Nutrition\nKnowledge" },
      { icon: iconSearchW, name: "Web\nSearch" },
      { icon: iconClipboardW, name: "Meal\nLogging" },
      { icon: iconUserW, name: "Profile &\nTDEE" },
      { icon: iconChartW, name: "Daily\nSummary" },
      { icon: iconStarW, name: "Progress\nAnalysis" },
      { icon: iconDatabaseW, name: "USDA\nLookup" },
    ];

    const toolW = 1.15;
    const toolGap = 0.17;
    const toolStartX = (10 - (tools.length * toolW + (tools.length - 1) * toolGap)) / 2;
    for (let i = 0; i < tools.length; i++) {
      const t = tools[i];
      const tx = toolStartX + i * (toolW + toolGap);
      const ty = 3.85;

      // Icon circle
      slide.addShape(pres.shapes.OVAL, {
        x: tx + (toolW - 0.55) / 2, y: ty, w: 0.55, h: 0.55,
        fill: { color: COLORS.orange }
      });
      slide.addImage({
        data: t.icon,
        x: tx + (toolW - 0.35) / 2, y: ty + 0.1, w: 0.35, h: 0.35
      });

      // Name
      slide.addText(t.name, {
        x: tx, y: ty + 0.6, w: toolW, h: 0.55,
        fontSize: 10, fontFace: "Calibri",
        color: COLORS.subtleText, align: "center", margin: 0
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 5: LIVE DEMO
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.darkNavy };

    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 10, h: 0.06, fill: { color: COLORS.orange }
    });

    slide.addText("Live Demo", {
      x: 0.6, y: 0.8, w: 8.8, h: 0.8,
      fontSize: 44, fontFace: "Georgia", bold: true,
      color: COLORS.white, align: "center", margin: 0
    });

    slide.addText('"Let me show you."', {
      x: 0.6, y: 1.6, w: 8.8, h: 0.5,
      fontSize: 20, fontFace: "Calibri", italic: true,
      color: COLORS.orangeLight, align: "center", margin: 0
    });

    // Demo flow steps
    const demoSteps = [
      "Login with password auth",
      "Set up user profile (weight, height, age, activity)",
      "Calculate TDEE (daily calorie target)",
      "Log a meal using natural language",
      "View daily summary with remaining calories",
      "Switch to Dashboard — see Plotly charts",
      "Refresh page — data persists across sessions",
    ];

    const stepStartY = 2.4;
    demoSteps.forEach((step, i) => {
      const sy = stepStartY + i * 0.4;
      slide.addShape(pres.shapes.OVAL, {
        x: 2.2, y: sy + 0.05, w: 0.25, h: 0.25,
        fill: { color: COLORS.orange }
      });
      slide.addText(String(i + 1), {
        x: 2.2, y: sy + 0.05, w: 0.25, h: 0.25,
        fontSize: 10, fontFace: "Calibri", bold: true,
        color: COLORS.white, align: "center", valign: "middle", margin: 0
      });
      slide.addText(step, {
        x: 2.6, y: sy, w: 5.5, h: 0.35,
        fontSize: 14, fontFace: "Calibri",
        color: COLORS.white, align: "left", valign: "middle", margin: 0
      });
    });

    // Time callout
    slide.addText("~90 seconds", {
      x: 3.5, y: 5.1, w: 3, h: 0.35,
      fontSize: 14, fontFace: "Calibri", bold: true,
      color: COLORS.medGray, align: "center"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 6: COMPETITIVE LANDSCAPE
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.offWhite };

    slide.addText("Competitive Landscape", {
      x: 0.6, y: 0.3, w: 8.8, h: 0.7,
      fontSize: 36, fontFace: "Georgia", bold: true,
      color: COLORS.darkNavy, align: "left", margin: 0
    });

    // Table
    const headerRow = [
      { text: "Feature", options: { fill: { color: COLORS.darkNavy }, color: COLORS.white, bold: true, fontSize: 13, fontFace: "Calibri", align: "left" } },
      { text: "MyFitnessPal\n($80/yr)", options: { fill: { color: COLORS.darkNavy }, color: COLORS.white, bold: true, fontSize: 13, fontFace: "Calibri", align: "center" } },
      { text: "ChatGPT", options: { fill: { color: COLORS.darkNavy }, color: COLORS.white, bold: true, fontSize: 13, fontFace: "Calibri", align: "center" } },
      { text: "Noom\n($200/yr)", options: { fill: { color: COLORS.darkNavy }, color: COLORS.white, bold: true, fontSize: 13, fontFace: "Calibri", align: "center" } },
      { text: "MacroMind", options: { fill: { color: COLORS.orange }, color: COLORS.white, bold: true, fontSize: 13, fontFace: "Calibri", align: "center" } },
    ];

    const makeRow = (feature, mfp, gpt, noom, mm) => [
      { text: feature, options: { fontSize: 12, fontFace: "Calibri", align: "left", color: COLORS.darkText } },
      { text: mfp, options: { fontSize: 12, fontFace: "Calibri", align: "center", color: mfp === "Yes" ? "27AE60" : "E74C3C" } },
      { text: gpt, options: { fontSize: 12, fontFace: "Calibri", align: "center", color: gpt === "Yes" ? "27AE60" : "E74C3C" } },
      { text: noom, options: { fontSize: 12, fontFace: "Calibri", align: "center", color: noom === "Yes" ? "27AE60" : "E74C3C" } },
      { text: mm, options: { fontSize: 12, fontFace: "Calibri", align: "center", color: "27AE60", bold: true } },
    ];

    const tableRows = [
      headerRow,
      makeRow("Conversational AI", "No", "Yes", "No", "Yes"),
      makeRow("Persistent Memory", "Yes", "No", "Yes", "Yes"),
      makeRow("Calorie Tracking", "Yes", "No", "Yes", "Yes"),
      makeRow("Macro Breakdown", "Yes", "No", "No", "Yes"),
      makeRow("Personalized TDEE", "No", "No", "No", "Yes"),
      makeRow("Science-Backed RAG", "No", "No", "No", "Yes"),
      makeRow("USDA Data Access", "No", "No", "No", "Yes"),
      makeRow("Visual Dashboard", "Yes", "No", "Yes", "Yes"),
    ];

    slide.addTable(tableRows, {
      x: 0.6, y: 1.15, w: 8.8,
      colW: [2.2, 1.5, 1.5, 1.5, 1.5],
      border: { pt: 0.5, color: COLORS.lightGray },
      rowH: 0.38,
      autoPage: false,
    });

    // Bottom callout
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y: 4.5, w: 8.8, h: 0.8,
      fill: { color: COLORS.darkNavy }
    });
    slide.addText("MacroMind is the only tool that combines conversational AI + persistent memory + science-backed nutrition intelligence.", {
      x: 0.8, y: 4.55, w: 8.4, h: 0.7,
      fontSize: 14, fontFace: "Calibri", bold: true,
      color: COLORS.white, align: "center", valign: "middle"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 7: WHAT'S NEXT
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.offWhite };

    slide.addText("What's Next", {
      x: 0.6, y: 0.3, w: 8.8, h: 0.7,
      fontSize: 36, fontFace: "Georgia", bold: true,
      color: COLORS.darkNavy, align: "left", margin: 0
    });

    const nextItems = [
      { icon: FaGoogle, title: "Google OAuth", desc: "Multi-user authentication for broader access" },
      { icon: FaCamera, title: "Photo Meal Logging", desc: "Snap a picture of your plate, auto-detect food and log macros" },
      { icon: FaBullseye, title: "Goal-Aware Coaching", desc: '"You\'ll hit 165 lbs by June at this rate" — proactive suggestions' },
      { icon: FaEnvelope, title: "Weekly Reports", desc: "Automated trend analysis and actionable insights via email" },
      { icon: FaMobileAlt, title: "Mobile-First PWA", desc: "Progressive web app for on-the-go nutrition tracking" },
    ];

    for (let i = 0; i < nextItems.length; i++) {
      const item = nextItems[i];
      const iy = 1.2 + i * 0.82;

      // Card background
      slide.addShape(pres.shapes.RECTANGLE, {
        x: 0.6, y: iy, w: 8.8, h: 0.7,
        fill: { color: COLORS.white }, shadow: makeShadow()
      });

      // Orange left accent
      slide.addShape(pres.shapes.RECTANGLE, {
        x: 0.6, y: iy, w: 0.07, h: 0.7,
        fill: { color: COLORS.orange }
      });

      // Icon
      const itemIcon = await iconToBase64Png(item.icon, "#FF6B35");
      slide.addImage({ data: itemIcon, x: 0.9, y: iy + 0.15, w: 0.4, h: 0.4 });

      // Title
      slide.addText(item.title, {
        x: 1.5, y: iy + 0.05, w: 3, h: 0.35,
        fontSize: 15, fontFace: "Calibri", bold: true,
        color: COLORS.darkNavy, align: "left", margin: 0
      });

      // Desc
      slide.addText(item.desc, {
        x: 1.5, y: iy + 0.35, w: 7.5, h: 0.3,
        fontSize: 12, fontFace: "Calibri",
        color: COLORS.subtleText, align: "left", margin: 0
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  // SLIDE 8: THANK YOU / CTA
  // ═══════════════════════════════════════════════════════════════════
  {
    let slide = pres.addSlide();
    slide.background = { color: COLORS.darkNavy };

    slide.addShape(pres.shapes.RECTANGLE, {
      x: 0, y: 0, w: 10, h: 0.06, fill: { color: COLORS.orange }
    });

    slide.addText("Try It Right Now", {
      x: 0.6, y: 0.8, w: 8.8, h: 0.8,
      fontSize: 44, fontFace: "Georgia", bold: true,
      color: COLORS.white, align: "center", margin: 0
    });

    // URL box
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 1.5, y: 2.0, w: 7, h: 0.7,
      fill: { color: COLORS.navy }
    });
    slide.addText("strong-caring-production-50e7.up.railway.app", {
      x: 1.5, y: 2.05, w: 7, h: 0.6,
      fontSize: 18, fontFace: "Consolas",
      color: COLORS.orange, align: "center", valign: "middle",
      hyperlink: { url: "https://strong-caring-production-50e7.up.railway.app" }
    });

    // Password
    slide.addText([
      { text: "Password: ", options: { color: COLORS.medGray } },
      { text: "macromind", options: { color: COLORS.orange, bold: true } },
    ], {
      x: 1.5, y: 2.85, w: 7, h: 0.5,
      fontSize: 18, fontFace: "Calibri", align: "center"
    });

    // Tech stack summary
    slide.addText("Built with LangGraph  |  GPT-4o-mini  |  SQLite  |  Chainlit  |  Railway", {
      x: 0.6, y: 3.7, w: 8.8, h: 0.4,
      fontSize: 13, fontFace: "Calibri",
      color: COLORS.medGray, align: "center"
    });

    // Thank you
    slide.addText("Thank you!", {
      x: 0.6, y: 4.3, w: 8.8, h: 0.6,
      fontSize: 28, fontFace: "Georgia",
      color: COLORS.white, align: "center"
    });

    // Author
    slide.addText("Risheek Somu  |  AI Engineering Bootcamp (AIE9)", {
      x: 0.6, y: 5.0, w: 8.8, h: 0.4,
      fontSize: 12, fontFace: "Calibri",
      color: COLORS.medGray, align: "center"
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  // Write file
  // ═══════════════════════════════════════════════════════════════════
  await pres.writeFile({ fileName: "MacroMind_Demo.pptx" });
  console.log("Created MacroMind_Demo.pptx successfully!");
}

main().catch(console.error);
