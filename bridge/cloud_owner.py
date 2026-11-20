"""The cloud counterpart of DomainSDKOwner (bridge/domain_sdk.py).

A session builds one for a department named in CLOUD_DOMAINS. It drives the
cloud runner instead of a local Claude Code SDK client; the local worktree,
lease and readiness stay the bridge's own.
"""


class CloudOwner:
    def __init__(self, config, workspace, lease, readiness, *, runner, conversation):
        self._config, self._workspace = config, workspace
        self._lease, self._readiness = lease, readiness
        self._runner = runner
        # The runner's conversation key: one per session generation.
        self._conversation: str = conversation
