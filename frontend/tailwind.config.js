/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#14202B",
          soft: "#2A3A48",
          mute: "#5C6B78",
          line: "#D5DAD6",
        },
        paper: {
          DEFAULT: "#F2F4F2",
          raised: "#FFFFFF",
          sunk: "#E7EAE7",
        },
        teal: {
          DEFAULT: "#0E7C93",
          deep: "#0A5C6E",
          wash: "#E2F0F3",
        },
        signal: {
          granted: "#2F7A4F",
          grantedWash: "#E4F0E8",
          warn: "#B8860B",
          warnWash: "#F7EFDC",
          denied: "#A3372A",
          deniedWash: "#F6E5E2",
        },
      },
      fontFamily: {
        display: ["'Barlow Condensed'", "system-ui", "sans-serif"],
        sans: ["'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
    },
  },
  plugins: [],
}
