import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        // VITE_API_PORT lets multiple dev instances run side by side
        target: `http://localhost:${process.env.VITE_API_PORT || 8000}`,
        changeOrigin: true,
      },
    },
  },
})
