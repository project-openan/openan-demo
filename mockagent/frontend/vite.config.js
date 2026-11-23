import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  base: '/debug/',
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      '/debug/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/debug\/api/, '/api'),
      },
      '/debug/a2a': { target: 'http://127.0.0.1:9000', changeOrigin: true },
    },
  },
})
