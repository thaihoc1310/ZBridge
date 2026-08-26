/** @type {import('tailwindcss').Config} */
const withAlpha = (variable) => `rgb(var(${variable}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: withAlpha("--background"),
        foreground: withAlpha("--foreground"),
        muted: withAlpha("--muted"),
        "muted-foreground": withAlpha("--muted-foreground"),
        accent: withAlpha("--accent"),
        "accent-secondary": withAlpha("--accent-secondary"),
        "accent-soft": withAlpha("--accent-soft"),
        border: withAlpha("--border"),
        card: withAlpha("--card"),
        input: withAlpha("--input"),
        popover: withAlpha("--popover"),
        inverse: withAlpha("--inverse"),
        "inverse-fg": withAlpha("--inverse-fg"),
        danger: {
          bg: withAlpha("--danger-bg"),
          fg: withAlpha("--danger-fg"),
          border: withAlpha("--danger-border"),
        },
        success: {
          bg: withAlpha("--success-bg"),
          fg: withAlpha("--success-fg"),
          border: withAlpha("--success-border"),
        },
        warning: {
          bg: withAlpha("--warning-bg"),
          fg: withAlpha("--warning-fg"),
          border: withAlpha("--warning-border"),
        },
        info: {
          bg: withAlpha("--info-bg"),
          fg: withAlpha("--info-fg"),
          border: withAlpha("--info-border"),
        },
        code: {
          bg: withAlpha("--code-bg"),
          fg: withAlpha("--code-fg"),
          key: withAlpha("--code-key"),
          string: withAlpha("--code-string"),
          number: withAlpha("--code-number"),
          keyword: withAlpha("--code-keyword"),
          punct: withAlpha("--code-punct"),
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Calistoga", "Georgia", "serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      boxShadow: {
        card: "var(--shadow-card)",
        "card-hover": "var(--shadow-card-hover)",
        accent: "0 8px 24px color-mix(in srgb, rgb(var(--accent)) 28%, transparent)",
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
