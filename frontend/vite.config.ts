/// <reference types="vitest" />

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import fs from 'fs';

// Vite plugin: copies each plugins/<name>/frontend/ into frontend/src/plugins/<name>/
// before build and dev-server start so import.meta.glob can discover plugin components.
// Adding a plugin: drop plugins/<name>/ with a frontend/index.tsx and rebuild.
// Removing a plugin: delete plugins/<name>/ and rebuild. No traces in core code.
function syncPluginFrontends() {
  const pluginsRoot = path.resolve(__dirname, '../plugins')
  const destRoot = path.resolve(__dirname, 'src/plugins')

  function sync() {
    if (!fs.existsSync(pluginsRoot)) return
    if (fs.existsSync(destRoot)) fs.rmSync(destRoot, { recursive: true })
    fs.mkdirSync(destRoot, { recursive: true })
    for (const name of fs.readdirSync(pluginsRoot)) {
      const src = path.join(pluginsRoot, name, 'frontend')
      if (fs.existsSync(src) && fs.statSync(src).isDirectory()) {
        fs.cpSync(src, path.join(destRoot, name), { recursive: true })
      }
    }
  }

  return {
    name: 'sync-plugin-frontends',
    buildStart: sync,
    configureServer() { sync() },
  }
}

export default defineConfig({
  plugins: [react(), syncPluginFrontends()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  base: '/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        // The vendor stack changes far less often than app code, so it gets
        // its own chunk and stays cached in browsers across releases.
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'],
          // The webplayer plugin imports hls.js at module level and the
          // eager plugin-slot glob pulls it into the shared chunk; keep the
          // ~400KB player library in its own long-cached chunk instead.
          hls: ['hls.js'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/ui/api': 'http://localhost:8088',
      '/login': 'http://localhost:8088',
      '/logout': 'http://localhost:8088',
      '/stream': 'http://localhost:8088',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
