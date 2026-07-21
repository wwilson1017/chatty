import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import basicSsl from '@vitejs/plugin-basic-ssl'

export default defineConfig({
  // VITE_HTTPS=1 serves dev over self-signed HTTPS — required to test mic
  // capture (live meeting recording) from a phone on the LAN, since
  // getUserMedia only exists in secure contexts. Off by default.
  plugins: [react(), tailwindcss(), ...(process.env.VITE_HTTPS ? [basicSsl()] : [])],
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
