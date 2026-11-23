/**
 * OpenAN Portal plugin bundle build for the Virtual Showroom (虚拟展厅).
 *
 * Output (dist-plugin/):
 *   index.js              ← UMD, sets window.__OPENAN_PLUGIN__virtual_showroom
 *   index.css             ← plugin styles
 *   plugin.manifest.json  ← runtime metadata consumed by the Portal bundle-loader
 *   cards.json            ← card config (edit to add new cards, no rebuild)
 *   images/*.svg          ← card cover images
 *
 * EXTERNAL (provided by the Portal host): react, react-dom
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync, readdirSync, existsSync } from 'fs';
import path from 'path';

const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const globalName = '__OPENAN_PLUGIN__virtual_showroom';

function file(p) {
    return readFileSync(path.join(root, p), 'utf-8');
}

function imageAssets() {
    const dir = path.join(root, 'assets', 'images');
    if (!existsSync(dir)) return [];
    return readdirSync(dir)
        .filter((f) => /\.(svg|png|jpg|jpeg|webp)$/i.test(f))
        .map((f) => ({ fileName: `images/${f}`, source: readFileSync(path.join(dir, f)) }));
}

export default defineConfig({
    define: {
        'process.env.NODE_ENV': JSON.stringify('production'),
    },
    plugins: [
        react(),
        {
            name: 'emit-plugin-static-assets',
            generateBundle() {
                this.emitFile({ type: 'asset', fileName: 'plugin.manifest.json', source: file('plugin.manifest.json') });
                this.emitFile({ type: 'asset', fileName: 'cards.json', source: file('cards.json') });
                for (const img of imageAssets()) {
                    this.emitFile({ type: 'asset', fileName: img.fileName, source: img.source });
                }
            },
        },
    ],
    build: {
        outDir: 'dist-plugin',
        emptyOutDir: true,
        lib: {
            entry: path.join(root, 'src/index.jsx'),
            name: globalName,
            formats: ['umd'],
            fileName: () => 'index.js',
        },
        rollupOptions: {
            external: ['react', 'react-dom'],
            output: {
                globals: {
                    react: 'React',
                    'react-dom': 'ReactDOM',
                },
                assetFileNames: 'index.css',
            },
        },
        cssCodeSplit: false,
    },
});
