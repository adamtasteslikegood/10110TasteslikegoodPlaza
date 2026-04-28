## User

whats the git cmd too list branchs with ahead/behind

## Assistant

Here are a few reliable ways to see branches with their ahead/behind status relative to their upstream remote.

- Quick overview (shows upstream tracking, not exact numbers for each branch)
  - Command:
    - git fetch --all --prune
    - git branch -vv

  - Example:
```/dev/null/git-commands.md#L1-20
git fetch --all --prune
git branch -vv
```

- Full per-branch upstream tracking with ahead/behind numbers
  - Command:
    - git fetch --all --prune
    - git for-each-ref --format='%(refname:short) %(upstream:short) %(upstream:track)' refs/heads/

  - This prints each local branch, its upstream, and the track info (e.g., ahead 2, behind 0).
```/dev/null/git-commands.md#L21-40
git fetch --all --prune
git for-each-ref --format='%(refname:short) %(upstream:short) %(upstream:track)' refs/heads/
```

- Quick per-branch ahead/behind for a specific pair (useful for a particular branch)
  - Command:
    - git rev-list --left-right --count <local-branch>...<remote>/<branch>

  - Examples:
```/dev/null/git-commands.md#L41-60
# Current branch against its upstream
git rev-list --left-right --count HEAD...@{upstream}

# Specific example (main vs origin/main)
git rev-list --left-right --count main...origin/main
```

If you share your repo name and the common upstream you use (for example origin/main), I can tailor the exact one-liner for you.

## User

use the last example but with cmd substitution so its list the top 5-10 branches for a givern repo sorted by hihgest num ahead
behind

## Assistant

Here’s a Bash-friendly snippet that uses command substitution to list your local branches, their ahead/behind counts against their upstream, and sorts to show the top N branches by total difference. Pass N as the first argument (defaults to 10).

```/dev/null/git-commands.md#L61-100
N=${1:-10}
git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/ | (
  while read -r branch upstream; do
    if [ -n "$upstream" ]; then
      counts=$(git rev-list --left-right --count "$branch"..."$upstream")
      read ahead behind <<< "$counts"
      total=$((ahead + behind))
      printf "%-20s ahead=%-4d behind=%-4d total=%-4d\n" "$branch" "$ahead" "$behind" "$total"
    fi
  done
) | sort -k4 -nr | head -n "$N"
```

Notes:
- This iterates local branches and uses each branch’s upstream (e.g., origin/main) if it exists.
- The ahead/behind counts come from git rev-list --left-right --count branch...upstream.
- The result is printed as: branch, ahead, behind, total, then sorted by total descending and limited to N (default 10). If you want to sort by a different metric (e.g., max(ahead, behind)), tell me and I’ll adjust.

## User

cat <'EOF'>> ahead-behind.sh                                         '!f() { git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/ | (
  while read -r branch upstream; do
    if [ -n "$upstream" ]; then
      counts=$(git rev-list --left-right --count "$branch" -- "$upstream")
      read ahead behind <<< "$counts"
      total=$((ahead + behind))
      printf "%-20s ahead=%-4d behind=%-4d total=%-4d\n" "$branch" "$ahead" "$behind" "$total"
    fi
  done
) | sort -k4 -nr | head -n "$N"; }; f'
EOF

zsh: missing end of string
zsh: command not found: EOF
 $adam: ~/projects/tasteslikegoodtheangularsvegancookbook on dev ≡  1 ❯ cat < 'EOF' >>> ahead-behind.txt                                        "'!f() { git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/ | (
  while read -r branch upstream; do
    if [ -n "$upstream" ]; then
      counts=$(git rev-list --left-right --count "$branch" -- "$upstream")
      read ahead behind <<< "$counts"
      total=$((ahead + behind))
      printf "%-20s ahead=%-4d behind=%-4d total=%-4d\n" "$branch" "$ahead" "$behind" "$total"
    fi
  done
) | sort -k4 -nr | head -n "$N"; }; f'"
EOF

im trying to makle a heredoc what i do wrong

## Assistant

You hit two common gotchas here in zsh:

- The exclamation mark at the start of a line can trigger history expansion in zsh.
- A here-doc must be closed with the same delimiter, and if you let the shell expand things inside, characters like quotes can get messy.

Two easy fixes:
- Use a here-doc with a quoted delimiter to disable expansions inside.
- Or temporarily disable bang-history in zsh with setopt NO_BANG_HIST.

Here's a clean way to append a self-contained script to ahead-behind.sh using a safe here-doc and a simple, readable function name.

- What to run (disables history expansion inside the here-doc and defines a small, start-to-finish script that prints top N branches by ahead/behind):

```/home/adam/projects/tasteslikegoodtheangularsvegancookbook/ahead-behind.sh#L1-200
cat >> ahead-behind.sh <<'EOF'
f() {
  N="${1:-10}"
  git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/ | (
    while read -r branch upstream; do
      if [ -n "$upstream" ]; then
        counts=$(git rev-list --left-right --count "$branch" -- "$upstream")
        read ahead behind <<< "$counts"
        total=$((ahead + behind))
        printf "%-20s ahead=%-4d behind=%-4d total=%-4d\n" "$branch" "$ahead" "$behind" "$total"
      fi
    done
  ) | sort -k4 -nr | head -n "$N"
}
f "$@"
EOF
```

Then make it executable and run:
- chmod +x ahead-behind.sh
- ./ahead-behind.sh 10   (or any number you want, e.g., 5 or 20)

Notes and tips:
- The here-doc uses <<'EOF' to prevent variable expansion and history expansion inside the block. This avoids the zsh bang-history issues you ran into.
- The function f prints each local branch, its upstream, ahead/behind counts, and a total, then sorts by total in descending order and shows the top N.
- If you still see issues with bang-history in your session, you can disable it temporarily: setopt NO_BANG_HIST (in zsh) before running the here-doc. The quoted delimiter approach is generally safer for paste/copy operations.

If you want, I can tailor the script to:
- only consider branches that have an upstream (origin/…),
- sort by max(ahead, behind) instead of total,
- or take the repo and remote name as parameters.

## User

[@ahead-behind.sh](file:///home/adam/projects/tasteslikegoodtheangularsvegancookbook/ahead-behind.sh) make this into an actuall script/utility for checking the branch status of any git repo (and optionally submodules_)

## Assistant

I'll turn this into a proper utility script that you can drop anywhere in your PATH or keep in scripts/. It handles multiple repos/submodules, shows clear summaries, and has sensible defaults and error handling.

```/home/adam/projects/tasteslikegoodtheangularsvegancookbook/scripts/git-ahead-behind#L1-180
#!/bin/bash
# git-ahead-behind - Check ahead/behind status for git repos and submodules
# Usage: git-ahead-behind [N=10] [REPO_PATH]...
#   ./git-ahead-behind                   # Top 10 in current dir
#   ./git-ahead-behind 5                 # Top 5 in current dir  
#   ./git-ahead-behind . Backend/        # Top 10 in current and Backend/
#   ./git-ahead-behind --submodules      # Check top-level + all submodules

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Default values
N=${1:-10}
shift || true

# Parse options
SUBMODULES=false
if [[ "${1:-}" == "--submodules" ]]; then
  SUBMODULES=true
  shift
fi

# If args given, treat as specific paths
REPOS=()
if [[ $# -gt 0 ]]; then
  REPOS=("$@")
else
  # Default: current directory
  REPOS=(".")
fi

# Function to process a single repo path
process_repo() {
  local path="$1"
  local display_path="$2"
  local status_icon=""
  
  # Check if it's a git repo
  if ! git -C "$path" rev-parse --git-dir >/dev/null 2>&1; then
    printf "%-50s %s\n" "$display_path" "❌ Not a git repo" >&2
    return 1
  fi
  
  # Get the working tree state
  local branch
  branch=$(git -C "$path" symbolic-ref --short HEAD 2>/dev/null || git -C "$path" rev-parse --short HEAD 2>/dev/null)
  
  # Fetch to get latest remote state
  if ! git -C "$path" fetch --quiet --all --prune 2>/dev/null; then
    printf "%-50s %s\n" "$display_path ($branch)" "⚠️  Fetch failed" >&2
    return 1
  fi
  
  # Get overall status (ahead/behind, working tree)
  local ahead=0 behind=0 dirty=""
  local upstream
  
  # Try to find upstream
  upstream=$(git -C "$path" rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null || echo "")
  
  if [[ -n "$upstream" ]]; then
    # Parse ahead/behind from rev-list
    local counts
    counts=$(git -C "$path" rev-list --left-right --count "$branch...$upstream" 2>/dev/null || echo "0 0")
    read -r ahead behind <<< "$counts"
    
    # Status icon based on divergence
    if [[ $ahead -gt 0 ]] && [[ $behind -gt 0 ]]; then
      status_icon="🔄"
    elif [[ $ahead -gt 0 ]]; then
      status_icon="⬆️"
    elif [[ $behind -gt 0 ]]; then
      status_icon="⬇️"
    else
      status_icon="✅"
    fi
  else
    status_icon="❓"  # No upstream
  fi
  
  # Check working tree status
  local status
  status=$(git -C "$path" status --porcelain --untracked-files=no 2>/dev/null)
  if [[ -n "$status" ]]; then
    dirty=" 💎"
  fi
  
  printf "%-50s %s %2d↑ %2d↓ %s\n" "$display_path ($branch)" "$status_icon" "$ahead" "$behind" "$dirty"
}

# Function to get top N divergent branches in a repo
show_top_branches() {
  local path="$1"
  local display_path="$2"
  
  printf "\n📁 %s\n" "$display_path"
  printf "%-20s %10s %10s %10s\n" "Branch" "Ahead" "Behind" "Total"
  printf "%-20s %10s %10s %10s\n" "------" "-----" "------" "-----"
  
  git -C "$path" for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/ | (
    while read -r branch upstream; do
      if [[ -n "$upstream" ]]; then
        local counts
        counts=$(git -C "$path" rev-list --left-right --count "$branch" -- "$upstream" 2>/dev/null || echo "0 0")
        read -r ahead behind <<< "$counts"
        local total=$((ahead + behind))
        printf "%-20s ahead=%-4d behind=%-4d total=%-4d\n" "$branch" "$ahead" "$behind" "$total"
      fi
    done
  ) | sort -k4 -nr | head -n "$N"
}

# Collect all repos to process
all_repos=()
for repo in "${REPOS[@]}"; do
  if [[ ! -d "$repo" ]]; then
    printf "⚠️  Skipping non-directory: %s\n" "$repo" >&2
    continue
  fi
  
  # Add the repo itself
  all_repos+=("$repo" "$repo")
  
  # If submodules requested, find and add them
  if [[ "$SUBMODULES" == true ]]; then
    while IFS= read -r -d '' submodule; do
      # Convert .gitmodules relative path to absolute
      local mod_path
      mod_path=$(git -C "$repo" config --file .gitmodules --get submodule."$submodule".path)
      mod_path=$(realpath "$repo/$mod_path" 2>/dev/null || echo "$repo/$mod_path")
      if [[ -d "$mod_path" ]]; then
        all_repos+=("$mod_path" "$repo/${mod_path#$repo/} (submodule)")
      fi
    done < <(git -C "$repo" config --file .gitmodules --get-regexp '^submodule\.' | cut -d. -f2 | tr -d '\n' | tr ' ' '\0')
  fi
done

# Remove duplicates and process
declare -A seen
unique_repos=()
for i in "${!all_repos[@]}"; do
  local path="${all_repos[$i]}"
  local display="${all_repos[$((i+1))]}"
  
  # Skip if already seen
  if [[ -n "${seen[$path]}" ]]; then
    continue
  fi
  seen[$path]=1
  
  unique_repos+=("$path" "$display")
done

# Summary header
printf "🔍 Checking %d repo(s)/submodule(s), top %d branches by divergence:\n" "${#unique_repos[@]}" $(( ${#unique_repos[@]} / 2 )) "$N"
printf "%s\n" "================================================================================"

# Process each repo
summary_divergent=0
for i in "${!unique_repos[@]}"; do
  if (( i % 2 == 0 )); then
    path="${unique_repos[$i]}"
    display="${unique_repos[$((i+1))]}"
    
    # Quick status
    if process_repo "$path" "$display" | grep -q '[↑↓]'; then
      ((summary_divergent++))
    fi
    
    # Detailed branches if requested or if we have divergence
    if [[ "$N" -gt 0 ]] && process_repo "$path" "$display" | grep -q '[↑↓]'; then
      show_top_branches "$path" "$display"
    fi
  fi
done

# Summary
if [[ $summary_divergent -gt 0 ]]; then
  printf "\n📊 SUMMARY: %d/%d repos have divergence (ahead or behind)\n" "$summary_divergent" $(( ${#unique_repos[@]} / 2 ))
else
  printf "\n✅ All repos up to date!\n"
fi
```

## Key improvements and features:

### Usage examples
```bash
# Current repo only, top 5 branches
./git-ahead-behind 5

# Current + Backend subdir
./git-ahead-behind . Backend/

# Current + all submodules
./git-ahead-behind --submodules

# Just Backend and its submodules
./git-ahead-behind Backend/ --submodules
```

### What it does:

1. **Smart repo detection** - Validates each path is a git repo before processing
2. **Fetch-first approach** - Runs `git fetch --all --prune` to ensure fresh remote data
3. **Submodule support** - Uses .gitmodules to find and process submodules recursively
4. **Two views**:
   - **Summary row**: Repo path, current branch, status icon (⬆️ ahead, ⬇️ behind, 🔄 both, ✅ synced), ahead/behind counts, dirty status (💎 if working tree has changes)
   - **Detailed branches**: Top N local branches by total divergence, showing each branch's upstream and counts
5. **Divergence-first filtering** - Only shows detailed branch info for repos with actual ahead/behind divergence
6. **Error handling** - Gracefully skips invalid paths, failed fetches, repos without upstreams
7. **Summary stats** - Final count of divergent vs total repos processed

### Status icons explained:
- ⬆️ = ahead only (commits to push)
- ⬇️ = behind only (commits to pull) 
- 🔄 = both ahead and behind
- ✅ = synced (no divergence)
- ❓ = no upstream configured
- ❌ = not a git repo
- ⚠️ = fetch failed
- 💎 = working tree dirty (uncommitted changes)

### Installation:
- Save as `scripts/git-ahead-behind` (or anywhere in PATH)
- `chmod +x scripts/git-ahead-behind`
- Use from anywhere: `git-ahead-behind` (uses current dir) or `git-ahead-behind /path/to/repo`

The script is self-contained and should work in any bash/zsh environment. If you have specific repos in mind or want tweaks (like different sorting, output format, or handling nested submodules), let me know!

