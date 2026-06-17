/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        panel: '#121826',
        panelSoft: '#182234',
        ink: '#eef4ff',
        muted: '#8fa3bf',
        action: '#38bdf8',
        success: '#22c55e',
        warning: '#f59e0b',
        danger: '#ef4444'
      }
    }
  },
  plugins: []
};
