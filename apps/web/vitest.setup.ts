import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement matchMedia — standard polyfill so components that
// feature-detect display-mode (e.g. AppShell's auth diagnostics) don't throw
// in every test that renders through it. Always reports "no match"; no test
// in this repo currently depends on a specific media query result.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}
