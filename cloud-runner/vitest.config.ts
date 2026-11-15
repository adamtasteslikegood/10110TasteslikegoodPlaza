import { cloudflareTest } from "@cloudflare/vitest-plugin"
import { defineConfig } from "vitest/config"

// The container image is built only on deploy and the test runtime has no
// containers, so tests load wrangler.test.jsonc: the same Durable Object
// binding and vars as wrangler.jsonc, without the `containers` block.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.test.jsonc" },
    }),
  ],
})
