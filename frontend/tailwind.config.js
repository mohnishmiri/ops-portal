/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "!./src/hooks/**",
  ],
  theme: {
    extend: {
      colors: {
        att: {
          50: "#eef7fc",
          100: "#d5ecf7",
          200: "#abdaf0",
          300: "#7ac3e5",
          400: "#3f9bca",
          500: "#2e80ac",
          600: "#246690",
          700: "#1e5275",
          800: "#1a445f",
          900: "#163a51",
        },
      },
    },
  },
  plugins: [],
};
