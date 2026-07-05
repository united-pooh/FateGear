/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FFF8F0',
        paper: '#FEF3C7',
        sand: '#F5E6D3',
        primary: '#E85D3A',
        amber: '#F59E0B',
        gold: '#FBBF24',
        indigo: '#1E3A5F',
        forest: '#2D6A4F',
        brick: '#DC2626',
        ink: '#292524',
        muted: '#78716C',
        line: '#D6C4A8',
      },
      fontFamily: {
        display: ['"Arial Black"', '"Helvetica Neue"', 'sans-serif'],
        body: ['system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        suprematist: '6px 6px 0 #F59E0B',
      },
    },
  },
  plugins: [],
}
