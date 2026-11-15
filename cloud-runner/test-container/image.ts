import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { image } from "./box"

// Builds the agent image from ./Dockerfile once, before the container tests.
export default function setup(): void {
	const context = fileURLToPath(new URL("..", import.meta.url).href)
	execFileSync("docker", ["build", "--quiet", "--tag", image, context], { stdio: ["ignore", "ignore", "inherit"] })
}
