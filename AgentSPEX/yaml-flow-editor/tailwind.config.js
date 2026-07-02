/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'node-step': '#E3F2FD',
        'node-step-border': '#1976D2',
        'node-if': '#FFE0B2',
        'node-if-border': '#E64A19',
        'node-loop': '#F3E5F5',
        'node-loop-border': '#7B1FA2',
        'node-parallel': '#C8E6C9',
        'node-parallel-border': '#388E3C',
        'node-call': '#B3E5FC',
        'node-call-border': '#0277BD',
        'node-synthesize': '#D1C4E9',
        'node-synthesize-border': '#512DA8',
      }
    },
  },
  plugins: [],
}

