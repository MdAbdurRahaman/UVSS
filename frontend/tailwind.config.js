/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,ts}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Nunito', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        // UVSS / Dubotech brand
        navy: '#0D2B52',
        'navy-hi': '#15457f',
        danger: '#dc2626',
        ok: '#27c93f',
        ink: '#171717',
        muted: '#737373',
        faint: '#a3a3a3',
        line: '#e5e5e5',
        canvas: '#fafafa',
      },
      borderRadius: {
        panel: '12px',
        card: '10px',
      },
    },
  },
  plugins: [],
};
