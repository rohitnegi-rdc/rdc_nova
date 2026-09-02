import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
	plugins: [
		sveltekit(),
		viteStaticCopy({
			targets: [
				{
					src: 'node_modules/onnxruntime-web/dist/*.jsep.*',

					dest: 'wasm'
				}
			]
		})
	],
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
	},
	build: {
		sourcemap: true
	},
	server: {
		proxy: {
			'/api': { target: 'http://localhost:8080', changeOrigin: true },
			'/oauth': { target: 'http://localhost:8080', changeOrigin: true },
			'/ws': { target: 'http://localhost:8080', changeOrigin: true, ws: true },
			'/socket.io': { target: 'http://localhost:8080', changeOrigin: true, ws: true },
			'/static/favicon.png': { target: 'http://localhost:8080', changeOrigin: true },
			'/static/splash.png': { target: 'http://localhost:8080', changeOrigin: true }
		}
	},
	worker: {
		format: 'es'
	},
	esbuild: {
		pure: process.env.ENV === 'dev' ? [] : ['console.log', 'console.debug', 'console.error']
	}
});
