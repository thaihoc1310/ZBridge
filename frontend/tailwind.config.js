/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        accent: "var(--accent)",
        "accent-secondary": "var(--accent-secondary)",
        border: "var(--border)",
        card: "var(--card)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Calistoga", "Georgia", "serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        card: "0 4px 18px rgba(15, 23, 42, 0.06)",
        "card-hover": "0 20px 35px rgba(15, 23, 42, 0.1)",
        accent: "0 8px 24px rgba(0, 82, 255, 0.28)",
      },
      keyframes: {
        pulseSoft: { "0%,100%": { opacity: "1", transform: "scale(1)" }, "50%": { opacity: ".65", transform: "scale(1.25)" } },
        spinSlow: { to: { transform: "rotate(360deg)" } },
        float: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-10px)" } },
      },
      animation: {
        "pulse-soft": "pulseSoft 2s ease-in-out infinite",
        "spin-slow": "spinSlow 12s linear infinite",
        float: "float 5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

