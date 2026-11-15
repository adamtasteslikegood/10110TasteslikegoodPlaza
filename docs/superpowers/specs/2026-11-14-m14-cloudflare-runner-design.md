# M14: department sessions on Cloudflare (cloud runner)

**Status:** approved by Adam 2026-11-14, including the API-key route in §5 (his Anthropic
API key, through the AI Gateway already on his account unless its setup makes a fresh one
better) and use of his Workers Paid plan. Nothing is built or deployed yet.
**Baseline:** dev `eb6b170`. Cloudflare facts were read from developers.cloudflare.com on
2026-11-14 (pages listed in §11); `@cloudflare/sandbox` latest is 1.0.3.

## 1. Intent

Run a department's Claude Code session in its own Cloudflare sandbox, so that:

- the agent can write only to its own copy of one repository;
- no file or secret from Adam's computer is reachable, because none is there;
- the network is limited to a named list of sites;
- several departments run at the same time without touching each other;
- the Cloudflare path is tested now, not after two more milestones.

## 2. Owner direction (2026-11-14), and what it supersedes

Adam chose Cloudflare first. This supersedes the 2026-10-23 order (local, then relay
with Hetzner, then Cloudflare) recorded in
`docs/research/cloudflare-durable-objects/ANALYSIS.md` and in the
`2026-10-23-domain-session-store-execution-backend` plan, phase 5.

Also decided by Adam on 2026-11-14:

- The local bridge keeps working as it does now. Local sessions get no sandbox in M14.
- The agent stays in its worktree and needs network access.
- It must not reach third parties at will, edit files on his computer, or pull secrets
  into something that gets committed.
- Agents should be able to see who is doing what. In-game agents claiming on the dev
  relay is intended.

## 3. Goals, non-goals, anti-goals

**Goals**

1. Stage 1: a runner on Cloudflare that Adam can drive with `curl`, with no bridge change.
2. Stage 2: the bridge can start a department on the runner, and more than one
   department can be active at once. Stage 2 is outlined here (§6.7) and gets its own
   plan only after Adam has read the stage 1 evidence.
3. Evidence for each item the roadmap marks unverified: Claude Code in a sandbox,
   the login path, resume after the instance is replaced, and cost.

**Non-goals**

- Sandboxing local sessions, or a local provider behind the same contract.
- Moving the bridge itself, or its SQLite state, to Cloudflare (M15).
- Hetzner as an execution host.
- Lanes, orchestrator agents and agent-to-agent messages. That is the next design.
- Permission prompts answered from the game during a cloud run.
- Subscription sign-in inside a cloud container (see §5).

**Anti-goals** (a build that does any of these has failed)

- A credential of any kind inside the container: env, file, clone URL or argument.
- A container with open Internet access.
- The admin Cloudflare token given to the runner, the bridge or an agent.
- A change to the bridge that alters how a local session behaves.

## 4. Approaches

| | Approach | Trade-off |
|---|---|---|
| A | Claude Code's own sandbox, switched on by the local bridge | Smallest change, but it protects the laptop, not the place Adam wants this to run |
| B | One Docker container per department, locally and on Hetzner | Strong boundary, same shape as Cloudflare, but another host to operate first |
| **C** | **Cloudflare Sandbox containers behind a Worker** | **Chosen. Largest step, on beta parts, but it is the end goal and its docs now cover this exact use** |

Adam picked C: local sessions already carry the risk he accepts on his laptop, and
Cloudflare is where the system has to work.

Within C, one further choice, **my call**: stage 1 runs the Claude Code command line
with JSON event output, as Cloudflare's guide does. Adam's saved note
(`Docs/files/durable-agent-microvm-sandbox/`) proposes a Python Agent SDK worker inside
the VM. That is needed for permission prompts and is deferred with them; the runner's
outside contract (commands in, numbered events out) is the one in that note, so the
inside can change later.

## 5. Login and billing: disposition (approved 2026-11-14)

Cloudflare's documented route sends Claude Code's model calls through AI Gateway. The
Worker adds the gateway token after the request leaves the container. The gateway holds
either an Anthropic API key or Cloudflare Unified Billing credits. Either way, cloud runs
are **billed per token**, not against Adam's Claude subscription.

Adam's recorded answer (2026-10-23) was to support both subscription sign-in and an API
key. Disposition proposed here: **the cloud runner supports the API-key route only.**
Subscription sign-in would put a long-lived personal token inside the container, which
§3 forbids, and whether Anthropic's terms allow it in a hosted container is still
unverified. Local sessions keep both routes.

## 6. Design

### 6.1 Parts

- **Runner Worker** (`cloud-runner/`, TypeScript, in this repo). Authenticates callers
  and routes each request to one workspace object.
- **Workspace object** (a Durable Object, one per workspace name). Owns the container,
  the run state, the event log (its own SQLite) and the snapshot id. It is
  single-threaded, so one run at a time per workspace needs no extra lock.
- **Container** (one per workspace object). Holds a clone of one GitHub repository on
  one branch, and Claude Code at a pinned version. Internet access is off.
- **Outbound handler** (in the Worker). Every request from the container passes
  through it. It allows or refuses by host and adds credentials.

A workspace name is `<project id>-<department>`, the same pair the bridge uses for its
branch `plaza/workspace-<project id>-<department>`.

### 6.2 What the caller can do

| Call | Effect |
|---|---|
| Create workspace | Start the container and clone `repo` at `branch` |
| Start run | Run one prompt, continuing the workspace's conversation or starting a new one on request; refused while a run is active |
| Read events after N | Numbered events since N; a reconnecting client loses and repeats nothing |
| Read status | Idle, running, stopped or failed; last result; pushed commit |
| Stop run | Interrupt the active run |
| Read diff | Uncommitted and unpushed changes |
| Delete workspace | Destroy the container, snapshot and log |

Exact routes, payloads and method names are the builder's.

### 6.3 A run

1. The object starts or reuses its container. If none is running, it starts one from
   the last snapshot, or from a fresh clone when there is no snapshot.
2. It starts Claude Code in the background with the prompt, a turn limit and the model.
3. An alarm fires every minute while the run is active. It keeps the container alive
   (work inside a container does not count as activity) and copies new events into the log.
4. When the run ends, the object pushes the branch, takes a snapshot, and records the
   result and the pushed commit.
5. With no run active, the container stops after 15 minutes idle (**my call**).

### 6.4 What survives

- **The pushed branch is the durable record.** It is pushed after every run.
- **The snapshot is a convenience.** It carries uncommitted files and Claude Code's own
  session files to the next instance. Snapshots are in public beta and expire after 30
  days, and an instance can stop without warning.
- If the snapshot is missing, the next run starts from the pushed branch with a new
  conversation, and the status says uncommitted work was lost. In stage 2 the bridge
  sends its M13 recap in that case.
- Whether Claude Code resumes its conversation after a snapshot restore is an
  acceptance test (§8), not an assumption.
- The event log keeps the last 10,000 events per workspace, each capped at 256 KiB
  (**my call**, matching the bridge's transcript record cap).

### 6.5 Network (**my call**; Adam has not ruled on the list)

Only ports 80 and 443 leave a container, and only through the handler. HTTPS only.

| Destination | Allowed | Credential added by the Worker |
|---|---|---|
| The AI Gateway endpoint of this account | All methods | Gateway token |
| `github.com`, this workspace's repository only | Clone, fetch, push | Scoped GitHub token |
| `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org` | GET only | None |
| Per-workspace additions, set at create | GET only | None |
| Everything else | Refused with 403 | |

This is the control that answers "it must not go and attack someone": a container
cannot open a connection the list does not name. Every allowed host is also a way to
send data out, which is why the list is short and additions are read-only.

### 6.6 What replaces the bridge's tool guard in the cloud

| Local guarantee | Cloud replacement |
|---|---|
| Writes stay in the department's worktree | The container holds nothing else |
| No write to another department's files | One container per workspace |
| Git changes only on the owned branch | Token scoped to one repository; the handler refuses other repositories; GitHub branch rules protect `dev` and `main` |
| Permission mode `dontAsk` with a hook | Skip-permissions inside the container, as Cloudflare's guide does; the container is the limit |
| Paid guard probe evidence | Stage 1 acceptance tests (§8) |

One gap, stated plainly: the agent can push any branch name in its one repository.
Protected branches are safe only where the repository has branch rules.

### 6.7 Stage 2: the bridge (outline; planned after stage 1 evidence)

Stage 1 is planned and built from this document. Stage 2 is not: it starts when Adam
has read the stage 1 results, and the proposals marked below are confirmed or changed
then. A failed conversation resume in stage 1 does not block stage 2; it means the
bridge sends its M13 recap on every cloud run.

Settled:

- A project setting names where each department runs: `local` (default) or `cloud`.
- Cloud departments do not count against the local limit of one active department.
  They have their own limit, default 3 (**my call**).
- The bridge relays runner events to the client as it does for a local run. If the
  bridge disconnects mid-run, the run continues, and the bridge reads events after its
  last number on reconnect.
- A live `domain_state` carries where the department runs. Godot shows it.
- The runner gets no relay credential. The bridge holds the relay claim as today.
- Only repositories hosted on GitHub can run in the cloud.

Proposed, to confirm at the stage 2 gate:

1. **Local worktree.** A cloud department still gets its local worktree, branch and
   lease, as today, so results and diffs read the same way. The agent does not run
   there. After each run the bridge fetches the branch and fast-forwards the worktree;
   anything else is an error, not a merge. Switching a department between `local` and
   `cloud` needs a stopped session and a clean worktree.
2. **The bridge and GitHub.** Today the bridge never pushes (`bridge/PROTOCOL.md`).
   Stage 2 has it push `plaza/workspace-*` branches to the project's own repository
   with the git login already on the machine. This is a real change to a stated rule.
3. **Runner token for real projects.** Stage 1 uses one token for one test repository.
   Real projects need a token per repository or a GitHub App.
4. **Sessions.** Ending a session starts a new cloud conversation on the next run; the
   workspace is deleted only when the department is. The recap is sent when a
   conversation starts new.
5. **Claims while the bridge is away.** The claim lapses and the cloud run finishes
   and pushes anyway, matching the 2026-11-13 ruling that a run in progress is not
   interrupted when its claim is lost.
6. **Names.** `project_id` is a hash of the local git directory path, so a workspace
   name belongs to one checkout on one machine.

**Cost of stage 2:** it changes `project_service.py`, `domain_manager.py`,
`domain_session.py`, `config.py` and `domain_protocol.py`, all guarded files, so the
paid guard probe must be rerun and `bridge/tool_guard_acceptance.json` regenerated.
`domain_sdk.py` and `guarded_transport.py` stay untouched; the cloud path is a second
implementation beside them, not a change to them.

## 7. Resources this creates (approval of this document is the go-ahead)

All in Adam's Cloudflare account, development only:

1. Worker `plaza-cloud-runner-dev`, with its workspace objects and container image.
2. An authenticated AI Gateway, and a gateway token with Run permission.
3. An Anthropic API key stored in the gateway, or Unified Billing credits (§5).
4. A GitHub fine-grained token, contents read and write, on one test repository.
   Adam creates it; it is stored as a Worker secret and never printed.
5. A caller secret for the runner, generated at deploy, stored as a Worker secret and
   in a git-ignored file. (**My call** for development; an Access application like the
   relay's is the stage 2 option.)

The building session deploys and runs the §8 tests itself, using the admin credential
in Adam's main checkout only for `wrangler` commands, as it did for the relay
(**my call**). That credential is not given to the runner, the bridge or any in-game
agent. Everything that can be proven under local `wrangler dev` is proven there first.
Docker must be running for `wrangler deploy`.

## 8. Stage 1 acceptance

Each is run against the deployed runner and logged in
`docs/research/cloudflare-durable-objects/spike-c.md`:

1. A prompt runs to completion; its events and final result are readable.
2. A client that drops mid-run reads the missing events with no loss or repeat.
3. From inside a run, a request to an unlisted host gets 403, and a push to another
   repository is refused.
4. No credential is found in the container's environment, files or `.git/config`.
5. Two workspaces run at the same time and neither sees the other's files.
6. After the instance is destroyed, the next run restores the snapshot: an
   uncommitted file is intact, and Claude Code either resumes its conversation or the
   failure is recorded with what was tried.
7. Stop interrupts a run, and the workspace accepts the next one.
8. Measured cost of a ten-minute run and of an idle hour.

## 9. Expected cost (from Cloudflare's published rates)

A `standard-1` instance (half a vCPU, 4 GiB, 8 GB disk) costs about $0.04 an hour idle
and up to about $0.075 an hour at full CPU, before the Workers Paid allowance. Snapshots
are free during the beta. Model tokens will be the larger cost.

## 10. Left to the builder

- Routes, payload shapes, event schema and SDK method names, checked against the
  installed `@cloudflare/sandbox` 1.x types.
- Instance size, the Claude Code version pin and the turn limit default.
- How spend per run is capped: a Claude Code flag if the pinned version has one,
  otherwise a gateway limit.
- Test layout for `cloud-runner/` and how it joins CI.

## 11. Sources (fetched 2026-11-14)

- `developers.cloudflare.com/sandbox/` (overview: microVM per instance; the scheduling
  policy sandboxes use is in public beta)
- `/sandbox/coding-agents/claude-code/` and `/sandbox/get-started/build-a-coding-agent-runner/`
- `/sandbox/concepts/security/` and `/sandbox/concepts/lifetime/`
- `/containers/platform/pricing/` and `/containers/platform/limits/`
