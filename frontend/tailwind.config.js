/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'profit': '#10b981',
        'loss': '#ef4444',
        'neutral': '#6b7280',
      }
    },
  },
  plugins: [],
}
