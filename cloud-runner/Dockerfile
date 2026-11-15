FROM node:24-trixie-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends bash ca-certificates git ripgrep tini \
	&& rm -rf /var/lib/apt/lists/*

# The install script from the Claude Code package puts its native binary in place
RUN npm install --global @anthropic-ai/claude-code@2.1.308

COPY --from=docker.io/cloudflare/sandbox:1.0.3 /usr/local/bin/sandbox-shim /usr/local/bin/sandbox-shim

# The agent runs as this user, never as root (PLZG-311). The runner's own
# commands stay root's: there is no USER line, so an exec is root unless the
# runner drops to the agent with setpriv (src/container.ts, asAgent).
# /workspace is root's, so the agent cannot replace the directories in it: the
# runner makes /workspace/repo (the agent's) and /workspace/task (root's alone).
# The layout mark is imageLayout in src/container.ts: change both together.
RUN useradd --create-home --shell /bin/bash agent \
	&& echo 2 > /etc/plaza-runner-layout

WORKDIR /workspace
# tini is PID 1 and reaps every exited process, so a finished task leaves no
# zombie and its pid and group id are not held (Copilot C1). The instance is
# started with no entrypoint of its own, so this one runs, from the image and
# from a snapshot alike. sleep keeps the container running between requests.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
