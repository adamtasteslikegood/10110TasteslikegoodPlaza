// Types `ctx.exports`, so the Workspace can hand the Outbound entrypoint to the
// container's intercepts with props.
declare namespace Cloudflare {
	interface GlobalProps {
		mainModule: typeof import("./index")
		durableNamespaces: "Workspace"
	}
}
