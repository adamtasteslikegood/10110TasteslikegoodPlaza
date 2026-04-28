# Git Workflow Scripts

This directory contains automation scripts for managing git workflows across the main repository and Backend submodule.

## Scripts

### `pm/atlassian_pm_link.py`

Dependency-free Jira + Confluence PM/session bridge. It reads Atlassian credentials from `.env`, fetches Jira project state plus Confluence planning/session pages, and writes a handoff briefing for future agent sessions.

**Usage:**

```bash
npm run pm:check  # Verify Jira and Confluence connectivity
npm run pm:brief  # Write .agent-work/pm/PROJECT_PM_BRIEFING.md
npm run pm:sync   # Publish/update the live briefing in Confluence
```

`scripts/pm/run_pm_daemon.sh` is the MCP launcher used by `auto_pm_mcp.json`; it creates the PM daemon virtualenv on first run and starts the Jira/Confluence PM daemon.

See [`docs/ATLASSIAN_PM_LINK.md`](../docs/ATLASSIAN_PM_LINK.md) for setup and workflow details.

### `git-workflow.sh`

A comprehensive git workflow automation script for managing commits and pushes across **all submodules** and the main repository. Works with any git repo — auto-detects submodules at runtime.

**Key Features:**

- ✅ Auto-detects all submodules (no hardcoded paths)
- ✅ `--recursive` flag for nested submodule trees
- ✅ Submodule-first, then main repo commits/pushes
- ✅ Filter to specific submodules with `--submodule-path` (repeatable)
- ✅ Interactive mode with step-by-step prompts
- ✅ Smart handling of staged/unstaged/untracked files
- ✅ AI-powered commit message generation (OpenAI)
- ✅ Separate messages for submodule and main repo
- ✅ Force push protection (requires confirmation for main/master)
- ✅ Dry-run mode to preview operations
- ✅ Colorful, verbose output
- ✅ Pre/post-workflow hooks
- ✅ Pull-before-commit support

**Quick Start:**

```bash
# Basic usage - commit and push all submodules + main
./scripts/git-workflow.sh -m "feat: new feature"

# Interactive mode
./scripts/git-workflow.sh -i

# Stage all and commit everything with message
./scripts/git-workflow.sh --all -m "chore: update all"

# Main repo only (skip submodules)
./scripts/git-workflow.sh --no-submodule -m "docs: update README"

# Include nested submodules
./scripts/git-workflow.sh --recursive --all -m "chore: update everything"

# Only a specific submodule
./scripts/git-workflow.sh --submodule-path Backend -m "fix: backend only"

# Dry run to preview
./scripts/git-workflow.sh --dry-run -m "test"
```

**Advanced Examples:**

```bash
# Different messages for submodule and main
./scripts/git-workflow.sh \
  --sub-message "fix: backend auth bug" \
  --main-message "chore: update backend reference"

# Multiple specific submodules
./scripts/git-workflow.sh \
  --submodule-path Backend \
  --submodule-path libs/shared \
  -m "chore: update selected"

# AI-generated commit message
export OPENAI_API_KEY="your-key-here"
./scripts/git-workflow.sh --auto --all

# Pull, commit, and push with tests
./scripts/git-workflow.sh \
  --pull-before \
  --run-before "npm test" \
  -m "feat: tested feature"

# Force push (with safety confirmation)
./scripts/git-workflow.sh \
  --force \
  --confirm-push \
  -m "fix: corrected history"
```

**Options Reference:**

| Category       | Flag                    | Description                        |
| -------------- | ----------------------- | ---------------------------------- |
| **Mode**       | `-i, --interactive`     | Interactive mode with prompts      |
|                | `-n, --dry-run`         | Preview without executing          |
|                | `-q, --quiet`           | Minimal output                     |
| **Repos**      | `--no-submodule`        | Skip all submodules                |
|                | `--no-main`             | Skip main repo                     |
|                | `--submodule-path PATH` | Filter to specific submodule (repeatable) |
|                | `-r, --recursive`       | Include nested submodules          |
| **Operations** | `--commit-only`         | Commit without pushing             |
|                | `--push`                | Enable push (auto with `-m`)       |
|                | `--confirm-push`        | Confirm before each push           |
|                | `--force`               | Force push (dangerous!)            |
| **Message**    | `-m "MSG"`              | Commit message                     |
|                | `--sub-message "MSG"`   | Submodule-specific message         |
|                | `--main-message "MSG"`  | Main repo-specific message         |
|                | `-F FILE`               | Read message from file             |
|                | `--editor [vim]`        | Use editor for message             |
|                | `--auto`                | AI-generate message                |
| **Staging**    | `-a, --all`             | Stage all without prompts          |
|                | `-u, --update`          | Stage tracked only                 |
|                | `-p, --patch`           | Interactive staging                |
|                | `--no-prompt-unstaged`  | Don't prompt for unstaged          |
| **Hooks**      | `--run-before CMD`      | Run command before                 |
|                | `--run-after CMD`       | Run command after                  |
|                | `--pull-before`         | Pull before commit                 |
|                | `--pull-rebase`         | Pull with rebase                   |
| **Branches**   | `--main-branch NAME`    | Specify main branch                |
|                | `--sub-branch NAME`     | Specify submodule branch           |

**Environment Variables:**

```bash
# AI commit message generation
export OPENAI_API_KEY="sk-..."       # Required for --auto
export OPENAI_MODEL="gpt-4"          # Optional (default: gpt-4)
export OPENAI_ENDPOINT="https://..." # Optional (custom endpoint)
```

**Workflow Order:**

1. Run `--run-before` command (if specified)
2. Pull changes (`--pull-before`)
3. **Process Each Submodule** (in detected order):
   - Check status
   - Stage files (with prompts or `--all`)
   - Commit
   - Push (if enabled)
4. **Process Main Repository:**
   - Check status
   - Update submodule references (for any submodules that changed)
   - Stage files
   - Commit
   - Push (if enabled)
5. Run `--run-after` command (if specified)

**Safety Features:**

- ⚠️ **Force push protection**: Requires confirmation for main/master branches
- ✅ **Clean tree checks**: Warns before pulling with uncommitted changes
- ✅ **Remote branch detection**: Auto-creates new branches or warns
- ✅ **Dry-run mode**: Test workflow without making changes
- ✅ **Verbose output**: See exactly what's happening

---

### `commit-phase-1.sh`

Legacy script for Phase 1 implementation. Commits specific files with predefined messages.

**Usage:**

```bash
./scripts/commit-phase-1.sh
```

### `list_revisions.sh`

Lists recent Cloud Run service revisions.

**Usage:**

```bash
./scripts/list_revisions.sh
```

## Best Practices

### Submodule Workflow

Always commit and push **submodules first**, then the main repo. This prevents broken references. The script handles this automatically for all detected submodules.

**✅ Correct:**

```bash
# Auto-detects and processes all submodules, then main
./scripts/git-workflow.sh -m "feat: add feature"

# With nested submodules
./scripts/git-workflow.sh --recursive -m "feat: add feature"

# OR manually for each submodule:
cd Backend && git commit && git push && cd ..
cd libs/shared && git commit && git push && cd ..
git commit && git push
```

**❌ Wrong:**

```bash
# DON'T commit main repo before pushing submodules!
git commit -a  # This includes submodule references
git push       # Main repo now points to unpushed submodule commits
cd Backend && git push  # Too late!
```

### Interactive Mode

Use `-i` when you want control over each step:

```bash
./scripts/git-workflow.sh -i
```

This will:

- Confirm branches
- Show staged changes before committing
- Confirm before each push
- Prompt for unstaged/untracked files

### AI Commit Messages

For quick, conventional commit messages:

```bash
export OPENAI_API_KEY="your-key"
./scripts/git-workflow.sh --auto --all
```

The AI will analyze your changes and generate a conventional commit message (feat:, fix:, chore:, etc.).

### Dry Run First

Always test complex workflows with `--dry-run`:

```bash
./scripts/git-workflow.sh --dry-run --force -m "risky change"
```

## Troubleshooting

**"Not a git repository" error:**

- Make sure you're in a git repository root
- Verify submodules are initialized: `git submodule update --init` (or `--init --recursive`)

**Unstaged changes prompts:**

- Use `--all` to stage everything automatically
- Use `--no-prompt-unstaged` to skip prompts

**Push fails:**

- Check you have push permissions
- Verify remote branch exists
- Use `--confirm-push` to review before pushing

**AI generation fails:**

- Verify `OPENAI_API_KEY` is set
- Check you have `jq` and `curl` installed
- Ensure API key has sufficient credits

## Contributing

When creating new scripts:

1. Make them executable: `chmod +x scripts/new-script.sh`
2. Add usage documentation in comments
3. Use the color functions from `git-workflow.sh`
4. Add entry to this README

## License

MIT License - see main repository LICENSE file.
