/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Blueprint palette. Ink and paper come from technical drawings; the two
        // signal colours are reserved for risk state and nothing else, so a red
        // element on this screen always means tier 3.
        ink: { DEFAULT: "#0F1E2E", soft: "#1B3149", line: "#2C4A6B" },
        paper: { DEFAULT: "#F7F8F6", edge: "#EAEDE8", deep: "#DFE4DD" },
        steel: { DEFAULT: "#6B7C8C", light: "#98A6B2", dark: "#48575F" },
        signal: { amber: "#C77E23", red: "#A6321E", blue: "#2D6E8F", green: "#3F6B4A" },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.08em" }],
      },
      boxShadow: {
        sheet: "0 1px 0 0 #EAEDE8, 0 12px 32px -24px rgba(15,30,46,0.45)",
      },
      backgroundImage: {
        // A faint drafting grid, drawn in CSS rather than shipped as an asset.
        // Named "blueprint" rather than "grid" so the utility does not collide
        // with a background-size key of the same name.
        blueprint:
          "linear-gradient(to right, rgba(44,74,107,0.06) 1px, transparent 1px)," +
          "linear-gradient(to bottom, rgba(44,74,107,0.06) 1px, transparent 1px)",
      },
      backgroundSize: { blueprint: "24px 24px" },
    },
  },
  plugins: [],
};
