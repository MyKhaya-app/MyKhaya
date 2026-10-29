// Rendered-geometry layout inspector shared by the responsive audit
// (scripts/responsive-audit.mjs) and the form layout harness
// (scripts/form-layout-harness.mjs).
//
// `inspectLayoutInPage` is passed to Playwright's page.evaluate, so it must
// stay self-contained: no imports and no references to module scope.
//
// It measures real bounding boxes. Document scroll width alone is not enough:
// .bottom-sheet clips (overflow: hidden) and .sheet-content scrolls
// (overflow-y: auto, which computes overflow-x to auto as well), so a control
// that overflows its card inside a sheet never widens the document. Every
// check below therefore compares an element with its own container.

/**
 * @param {{
 *   rootSelector?: string | null,
 *   checkReachability?: boolean,
 *   overlay?: { right: number, top: number } | null,
 *   intendedScrollers?: string[],
 *   visibleHeight?: number | null,
 *   acceptedOverflow?: string[],
 * }} options `overlay` is a system overlay zone in the top-right corner
 *   (CSS px from the right and top edges). `visibleHeight` is the usable
 *   height when a software keyboard covers the bottom of the viewport.
 */
export function inspectLayoutInPage(options = {}) {
  const {
    rootSelector = null,
    checkReachability = false,
    overlay = null,
    intendedScrollers = [],
    visibleHeight = null,
    acceptedOverflow = [],
  } = options;
  const TOLERANCE = 0.5;
  const viewport = { width: window.innerWidth, height: visibleHeight ?? window.innerHeight };
  const issues = [];
  const advisories = [];
  const metrics = [];

  // Content of a closed <details> keeps a layout box in Chromium but is not
  // shown, so it is not visible here.
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    if (element.closest("details:not([open]) > :not(summary)")) return false;
    // Laid out entirely above or left of the page origin: an offscreen
    // measurement copy no one can scroll to.
    if (rect.bottom + window.scrollY < 0 || rect.right + window.scrollX < 0) return false;
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  // Fixed/sticky chrome (headers, FABs, docks) floats over content that
  // scrolls beneath it by design.
  const floatingLayer = (element) => {
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      const position = getComputedStyle(node).position;
      if (position === "fixed" || position === "sticky") return node;
    }
    return null;
  };
  const describe = (element) => {
    if (!element || element.nodeType !== 1) return String(element);
    const classes = typeof element.className === "string" ? element.className.trim().split(/\s+/).filter(Boolean).slice(0, 3) : [];
    const label = element.getAttribute("aria-label") || (element.tagName === "BUTTON" ? element.textContent.trim().slice(0, 40) : "");
    return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${classes.map((item) => `.${item}`).join("")}${label ? `[${label}]` : ""}`;
  };
  const box = (rect) => ({ left: Math.round(rect.left * 10) / 10, right: Math.round(rect.right * 10) / 10, top: Math.round(rect.top * 10) / 10, bottom: Math.round(rect.bottom * 10) / 10, width: Math.round(rect.width * 10) / 10 });
  const add = (kind, element, message, extra = {}) => {
    issues.push({ kind, element: describe(element), message, box: box(element.getBoundingClientRect()), ...extra });
  };
  const advise = (kind, element, message, extra = {}) => {
    advisories.push({ kind, element: describe(element), message, box: box(element.getBoundingClientRect()), ...extra });
  };
  const isIntendedScroller = (element) => intendedScrollers.some((selector) => element.matches(selector));
  const insideIntendedScroller = (element) => {
    for (let node = element.parentElement; node; node = node.parentElement) {
      if (isIntendedScroller(node)) return true;
    }
    return false;
  };

  const roots = rootSelector
    ? [...document.querySelectorAll(rootSelector)].filter(visible)
    : [document.body];
  const root = rootSelector ? roots.at(-1) : document.body;
  if (!root) return { viewport, issues: [{ kind: "root-missing", element: rootSelector, message: "Inspection root was not rendered" }], advisories, metrics };

  // 1. Document-level horizontal scrolling.
  const documentWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  if (documentWidth > document.documentElement.clientWidth + 1) {
    add("document-overflow", document.documentElement, "Document is horizontally scrollable", { scrollWidth: documentWidth, clientWidth: document.documentElement.clientWidth });
  }

  const elements = [root, ...root.querySelectorAll("*")].filter((element) => !(element instanceof SVGElement && element.tagName.toLowerCase() !== "svg") && visible(element));

  for (const element of elements) {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();

    // 2. Child outside its parent's padding box (horizontal). Out-of-flow
    // descendants are measured against their own containing block by the
    // viewport check below instead.
    const parent = element.parentElement;
    if (parent && element !== root && !acceptedOverflow.some((selector) => element.matches(selector)) && !["fixed", "absolute"].includes(style.position) && getComputedStyle(parent).display !== "contents" && !insideIntendedScroller(element) && element.tagName !== "LEGEND") {
      const parentStyle = getComputedStyle(parent);
      const parentRect = parent.getBoundingClientRect();
      const innerLeft = parentRect.left + parseFloat(parentStyle.borderLeftWidth);
      const innerRight = parentRect.right - parseFloat(parentStyle.borderRightWidth);
      const overRight = rect.right - innerRight;
      const overLeft = innerLeft - rect.left;
      if (overRight > TOLERANCE || overLeft > TOLERANCE) {
        add("child-outside-parent", element, "Element extends outside its parent container", { parent: describe(parent), parentBox: box(parentRect), overflowRight: Math.round(overRight * 10) / 10, overflowLeft: Math.round(overLeft * 10) / 10 });
      }
    }

    // 3. Unintended internal horizontal scrolling, and clipped containers
    // hiding overflowing content (overflow hidden/clip makes the defect
    // invisible to every scroll-width check).
    const overflowX = style.overflowX;
    const horizontallyOverflowing = element.scrollWidth > element.clientWidth + 1 && element.clientWidth > 0;
    if (horizontallyOverflowing && ["auto", "scroll"].includes(overflowX) && !isIntendedScroller(element) && element !== document.documentElement && element !== document.body) {
      add("internal-horizontal-scroll", element, "Container scrolls horizontally but is not an intended horizontal interface", { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth });
    }
    if (horizontallyOverflowing && ["hidden", "clip"].includes(overflowX) && !isIntendedScroller(element) && element.querySelector("input, select, textarea, button, fieldset")) {
      add("clipped-overflow", element, "Container clips horizontally overflowing form content", { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth });
    }

    // 4. Interactive elements beyond the viewport.
    if (element.matches("button, a[href], input, select, textarea, [role=button]") && !insideIntendedScroller(element)) {
      if (rect.right > viewport.width + 1 || rect.left < -1) {
        add("interactive-out-of-viewport", element, "Interactive element extends outside the viewport");
      }
      if (rect.width < 44 || rect.height < 44) {
        if (element.matches("button, [role=button], input:not([type=checkbox]):not([type=radio]), select")) {
          advise("touch-target", element, "Interactive element is smaller than 44x44 CSS px", { width: Math.round(rect.width), height: Math.round(rect.height) });
        }
      }
    }
  }

  // 5. Native date/time controls left at their platform appearance. WebKit on
  // iOS renders them with a theme-adjusted intrinsic size that ignores the
  // author's min-width: 0, which Chromium cannot reproduce. Asserting the
  // normalised appearance catches that class of defect on every engine.
  for (const input of root.querySelectorAll('input[type="date"], input[type="time"], input[type="datetime-local"], input[type="month"]')) {
    if (!visible(input)) continue;
    const style = getComputedStyle(input);
    const appearance = style.appearance || style.webkitAppearance;
    if (appearance !== "none" && !input.closest(".datetime-card")) {
      add("native-date-time-appearance", input, "Date/time input keeps its platform appearance (iOS intrinsic-width risk)", { appearance });
    }
  }

  // 6. Overlapping adjacent controls, compared by their painted (clipped)
  // rects: a control scrolled past the edge of .sheet-content is clipped by
  // it and does not overlap the header or footer it passes beneath.
  const clippedRect = (element) => {
    const rect = element.getBoundingClientRect();
    let { left, right, top, bottom } = rect;
    for (let node = element.parentElement; node && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.overflowX === "visible" && style.overflowY === "visible") continue;
      const clip = node.getBoundingClientRect();
      left = Math.max(left, clip.left);
      right = Math.min(right, clip.right);
      top = Math.max(top, clip.top);
      bottom = Math.min(bottom, clip.bottom);
    }
    return { left, right, top, bottom };
  };
  const controls = [...root.querySelectorAll("input:not([type=hidden]), select, textarea, button")].filter((control) => visible(control) && !insideIntendedScroller(control));
  for (let index = 0; index < controls.length; index += 1) {
    for (let other = index + 1; other < controls.length; other += 1) {
      if (controls[index].contains(controls[other]) || controls[other].contains(controls[index])) continue;
      const a = clippedRect(controls[index]);
      const b = clippedRect(controls[other]);
      if (a.right <= a.left || a.bottom <= a.top || b.right <= b.left || b.bottom <= b.top) continue;
      if (a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1) {
        if (floatingLayer(controls[index]) !== floatingLayer(controls[other])) {
          advise("floating-overlap", controls[index], "A fixed/sticky control floats over this control at the current scroll position", { other: describe(controls[other]) });
        } else {
          add("control-overlap", controls[index], "Adjacent controls overlap", { other: describe(controls[other]) });
        }
      }
    }
  }

  // 7. Sheets: header action accessibility, footer bounds and scroll-to-reveal
  // reachability of every control inside the scrollable body.
  const sheets = rootSelector ? [root].filter((element) => element.matches(".bottom-sheet")) : [...document.querySelectorAll(".bottom-sheet")].filter(visible);
  for (const sheet of sheets) {
    const sheetRect = sheet.getBoundingClientRect();
    const content = sheet.querySelector(":scope > .sheet-content");
    const footer = sheet.querySelector(":scope > .sheet-footer");
    const close = sheet.querySelector(":scope > header .bottom-sheet-close");
    if (sheetRect.top < -TOLERANCE || sheetRect.bottom > viewport.height + TOLERANCE) add("sheet-out-of-viewport", sheet, "Sheet extends beyond the viewport");
    if (footer && footer.getBoundingClientRect().bottom > viewport.height + TOLERANCE) add("sheet-footer-out-of-viewport", footer, "Sheet footer is outside the viewport");
    const dismissals = [...sheet.querySelectorAll("button")].filter((button) => visible(button) && (button.matches(".bottom-sheet-close") || /^(cancel|close)$/i.test(button.textContent.trim())));
    if (!dismissals.length) add("no-dismissal-control", sheet, "Sheet has no visible close or cancel control");
    for (const control of [close].filter(Boolean)) {
      const rect = control.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      if (!hit || (hit !== control && !control.contains(hit))) add("header-action-obscured", control, "Header close button is not the topmost element at its centre", { hit: describe(hit) });
      if (overlay && rect.right > viewport.width - overlay.right + TOLERANCE && rect.top < overlay.top) {
        add("header-action-under-overlay", control, "Header close button lies inside the simulated system status overlay zone", { overlay });
      }
    }
    if (footer && content) {
      metrics.push({ kind: "sheet", sheet: describe(sheet), sheetBox: box(sheetRect), contentClientHeight: content.clientHeight, contentScrollHeight: content.scrollHeight, footerBox: box(footer.getBoundingClientRect()) });
    }
    if (checkReachability && content) {
      const originalScroll = content.scrollTop;
      const targets = [...content.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea")].filter(visible);
      for (const target of targets) {
        target.scrollIntoView({ block: "nearest", inline: "nearest" });
        const rect = target.getBoundingClientRect();
        const contentRect = content.getBoundingClientRect();
        const footerTop = footer ? footer.getBoundingClientRect().top : Infinity;
        const visibleBottom = Math.min(contentRect.bottom, footerTop, viewport.height);
        if (rect.top < contentRect.top - TOLERANCE || rect.bottom > visibleBottom + TOLERANCE) {
          add("control-not-fully-revealed", target, "Scrolling cannot reveal the whole control", { visibleTop: Math.round(contentRect.top), visibleBottom: Math.round(visibleBottom) });
          continue;
        }
        const points = [[rect.left + rect.width / 2, rect.top + rect.height / 2], [rect.left + 3, rect.bottom - 3], [rect.right - 3, rect.bottom - 3]];
        for (const [x, y] of points) {
          const hit = document.elementFromPoint(x, y);
          if (!hit || (hit !== target && !target.contains(hit) && !hit.contains(target) && hit.closest("label") !== target.closest("label"))) {
            add("control-obscured", target, "Another element covers part of this control after scrolling it into view", { hit: describe(hit), x: Math.round(x), y: Math.round(y) });
            break;
          }
        }
      }
      content.scrollTop = originalScroll;
    }
  }

  // Width metrics for form containers and controls, for the evidence report.
  for (const element of root.querySelectorAll(".form-section, .form-row, .form-field, fieldset, input, select, textarea")) {
    if (!visible(element)) continue;
    const parent = element.parentElement;
    const rect = element.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    metrics.push({ kind: "width", element: describe(element), width: Math.round(rect.width * 10) / 10, left: Math.round(rect.left * 10) / 10, right: Math.round(rect.right * 10) / 10, parent: describe(parent), parentLeft: Math.round(parentRect.left * 10) / 10, parentRight: Math.round(parentRect.right * 10) / 10 });
  }

  return { viewport, documentWidth, issues, advisories, metrics };
}

/**
 * Horizontal interfaces designed to scroll (overflow-x: auto in styles.css)
 * or to clip offscreen panels (the month swipe track renders the previous and
 * next months beside the visible one). Their descendants are exempt from the
 * containment and viewport checks; the containers themselves still are not.
 */
export const INTENDED_HORIZONTAL_SCROLLERS = [
  ".control-tabs",
  ".meal-recent-list",
  ".plan-compare-table-wrap",
  ".drv-chips-scroll",
  ".family-status-row",
  ".legal-prose table",
  ".calendar-month-swipe",
];

/**
 * Elements that extend past their parent on purpose, each with its reason.
 * Keep this list short and specific: an entry here is a reviewed decision,
 * not a way to quieten a failure.
 */
export const ACCEPTED_CONTAINMENT_EXCEPTIONS = [
  // 44x44 hit area from padding cancelled by an equal negative margin
  // (styles.css, .calendar-settings-check).
  ".calendar-settings-check",
  // Deliberate transform: scale(1.16) on the profile avatar.
  ".profile-avatar-wrap",
  // The 43px opaque logo sits over the 32px cream tile of the desktop nav
  // brand mark; nothing is clipped or covered. Tidy-up candidate.
  ".desktop-nav-brand-mark > .brand",
];
