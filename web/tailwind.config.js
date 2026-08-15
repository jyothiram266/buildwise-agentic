/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Blueprint & Corporate Executive palette
        ink: { DEFAULT: "#0B1520", soft: "#16283A", line: "#24405E" },
        paper: { DEFAULT: "#F4F6F8", edge: "#E2E7ED", deep: "#D5DDE6" },
        steel: { DEFAULT: "#5F7182", light: "#8D9DAE", dark: "#3A4A58" },
        signal: { amber: "#D97706", red: "#DC2626", blue: "#2563EB", green: "#059669" },
        brand: { 50: "#EFF6FF", 100: "#DBEAFE", 500: "#3B82F6", 600: "#2563EB", 700: "#1D4ED8" }
      },
      fontFamily: {
        sans: ["'Inter'", "'Plus Jakarta Sans'", "system-ui", "sans-serif"],
        display: ["'Plus Jakarta Sans'", "'Inter'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.08em" }],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(15, 23, 42, 0.05)",
        "2xs": "0 1px 1px 0 rgba(15, 23, 42, 0.03)",
        sheet: "0 1px 3px 0 rgba(15,23,42,0.06), 0 10px 25px -5px rgba(15,23,42,0.08)",
        glass: "0 8px 32px 0 rgba(15, 23, 42, 0.06)",
        glow: "0 0 20px -5px rgba(37, 99, 235, 0.25)",
      },
      backgroundImage: {
        blueprint:
          "linear-gradient(to right, rgba(36,64,94,0.05) 1px, transparent 1px)," +
          "linear-gradient(to bottom, rgba(36,64,94,0.05) 1px, transparent 1px)",
      },
      backgroundSize: { blueprint: "24px 24px" },
    },
  },
  plugins: [],
};
