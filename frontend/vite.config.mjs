import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root,
  cacheDir: 'node_modules/.vite',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    fs: {
      strict: true,
      allow: [root],
    },
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
