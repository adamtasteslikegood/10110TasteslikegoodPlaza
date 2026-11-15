import { fileURLToPath } from "node:url"
import { defineConfig } from "vitest/config"

// The commands the Worker sends to its container, run in a real container
// built from ./Dockerfile. This needs Docker, so it is not part of `npm test`
// (the Workers runtime, which has no containers): run `npm run test:container`.
// The sandbox SDK loads only in the Workers runtime, so a stand-in replaces it.
export default defineConfig({
	resolve: {
		alias: { "@cloudflare/sandbox": fileURLToPath(new URL("./test-container/sandbox-stub.ts", import.meta.url).href) },
	},
	test: {
		include: ["test-container/**/*.ctest.ts"],
		globalSetup: ["./test-container/image.ts"],
		testTimeout: 60_000,
		hookTimeout: 120_000,
		fileParallelism: false,
	},
})
