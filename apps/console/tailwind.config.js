/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark technical instrument surface ramp.
        ink: {
          950: '#04070c',
          900: '#080d14',
          850: '#0b121b',
          800: '#101822',
          750: '#15202c',
          700: '#1b2836',
          600: '#243346',
          500: '#33455c',
        },
        wire: '#22c3d6',
      },
      fontFamily: {
        mono: [
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'DejaVu Sans Mono',
          'monospace',
        ],
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.85rem' }],
      },
      keyframes: {
        nodeIn: {
          '0%': { opacity: '0', transform: 'translateX(-14px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        dash: {
          '0%': { strokeDashoffset: '120' },
          '100%': { strokeDashoffset: '0' },
        },
        flow: {
          '0%': { strokeDashoffset: '24' },
          '100%': { strokeDashoffset: '0' },
        },
        pulseMark: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
      },
      animation: {
        nodeIn: 'nodeIn 420ms ease-out both',
        dash: 'dash 520ms ease-out both',
        flow: 'flow 900ms linear infinite',
        pulseMark: 'pulseMark 1.8s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
