/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#070707',
        sidebar: '#0b0b0b',
        card: '#0f0f0f',
        'card-raised': '#151515',
        border: 'rgba(255,255,255,0.09)',
        accent: '#6152df',
        'accent-light': '#9f92ff',
        'accent-pale': '#c7c2ff',
        ok: '#7bd0a7',
        warn: '#dacd8a',
        danger: '#e48181',
        body: '#e6e6e6',
        muted: 'rgba(255,255,255,0.5)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
};
