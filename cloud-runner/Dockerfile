FROM node:24-trixie-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends bash ca-certificates git ripgrep \
	&& rm -rf /var/lib/apt/lists/*

# The install script from the Claude Code package puts its native binary in place
RUN npm install --global @anthropic-ai/claude-code@2.1.308

COPY --from=docker.io/cloudflare/sandbox:1.0.3 /usr/local/bin/sandbox-shim /usr/local/bin/sandbox-shim

WORKDIR /workspace
# Keep the container running between requests
CMD ["sleep", "infinity"]
