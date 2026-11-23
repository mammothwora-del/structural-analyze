/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0b0f14", 900: "#10161d", 850: "#141b24", 800: "#19222d", 700: "#243040", 600: "#33445a", 400: "#7f93ab", 300: "#a9b8c9", 200: "#d3dce6" },
        accent: { DEFAULT: "#3fb6ff", dim: "#1f6f9e" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "monospace"] },
    },
  },
  plugins: [],
};
