#!/bin/bash

################################################################################
# Git Workflow Script - Multi-Submodule & Main Repo Management
################################################################################
# Manages commits and pushes across ALL submodules and the main repository.
# Works with any git repo — auto-detects submodules at runtime.
# Supports --recursive for nested submodule trees.
#
# Usage: ./git-workflow.sh [OPTIONS]
# Example: ./git-workflow.sh -i -m "feat: new feature"
# Example: ./git-workflow.sh --no-submodule --push
# Example: ./git-workflow.sh --all -m "chore: update all"
# Example: ./git-workflow.sh --recursive -m "chore: update everything"
# Example: ./git-workflow.sh --submodule-path Backend -m "fix: backend only"
################################################################################

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Disable pagers for all git commands in this script
export GIT_PAGER=cat

################################################################################
# COLORS & FORMATTING
################################################################################
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly BOLD='\033[1m'
readonly NC='\033[0m' # No Color

################################################################################
# DEFAULT CONFIGURATION
################################################################################
INTERACTIVE=false
VERBOSE=true
DRY_RUN=false

# What to process
DO_SUBMODULE=true
DO_MAIN=true

# Operations
DO_COMMIT=true
DO_PUSH=true
CONFIRM_PUSH=false
COMMIT_ONLY=false
FORCE_OPERATIONS=false

# Branches (auto-detected by default)
MAIN_BRANCH=""
SUB_BRANCH=""

# Commit message options
COMMIT_MESSAGE=""
COMMIT_MESSAGE_FILE=""
COMMIT_MESSAGE_EDITOR=""
COMMIT_MESSAGE_AUTO=false
SUB_MESSAGE=""
MAIN_MESSAGE=""
USE_GIT_EDITOR=false

# Hooks
RUN_BEFORE=""
RUN_AFTER=""
PULL_BEFORE=false
PULL_REBASE=false

# Paths — submodule filtering (empty = all detected submodules)
SUBMODULE_FILTER_PATHS=()
RECURSIVE=false
PROJECT_ROOT=""

# Populated at runtime by detect_submodules()
DETECTED_SUBMODULES=()
COMMITTED_SUBMODULES=()

# Staging behavior
STAGE_ALL_FLAG=false
STAGE_TRACKED_ONLY=false
STAGE_INTERACTIVE=false
PROMPT_FOR_UNSTAGED=true
PROMPT_FOR_UNTRACKED=true
ADDITIONAL_FILES=()

# AI Configuration for auto-generation
AI_MODEL="${OPENAI_MODEL:-gpt-4}"
AI_API_KEY="${OPENAI_API_KEY:-}"
AI_ENDPOINT="${OPENAI_ENDPOINT:-https://api.openai.com/v1/chat/completions}"

################################################################################
# HELPER FUNCTIONS
################################################################################

print_color() {
    local color=$1
    shift
    if [[ "$VERBOSE" == true ]]; then
        echo -e "${color}$*${NC}"
    fi
}

print_header() {
    if [[ "$VERBOSE" == true ]]; then
        echo ""
        echo -e "${YELLOW}=========================================="
        echo "  $1"
        echo -e "==========================================${NC}"
        echo ""
    fi
}

print_success() { print_color "$GREEN" "✅ $*"; }
print_info() { print_color "$BLUE" "ℹ️  $*"; }
print_warning() { print_color "$YELLOW" "⚠️  $*"; }
print_error() { print_color "$RED" "❌ $*"; }

confirm() {
    local prompt="$1"
    local response
    read -rp "$(echo -e "${CYAN}${prompt} [y/N]:${NC} ")" response
    [[ "$response" =~ ^[Yy]$ ]]
}

get_current_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
}

is_clean_working_tree() {
    git diff-index --quiet HEAD -- 2>/dev/null
}

has_staged_changes() {
    ! git diff --cached --quiet 2>/dev/null
}

has_unstaged_changes() {
    ! git diff --quiet 2>/dev/null
}

has_untracked_files() {
    [[ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]]
}

branch_exists() {
    git rev-parse --verify "$1" >/dev/null 2>&1
}

remote_branch_exists() {
    git ls-remote --heads origin "$1" 2>/dev/null | grep -q "$1"
}

################################################################################
# VALIDATION FUNCTIONS
################################################################################

validate_git_repo() {
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        print_error "Not a git repository. Please run from project root."
        exit 1
    fi
}

validate_submodules() {
    if [[ "$DO_SUBMODULE" != true ]]; then
        return 0
    fi

    for sm_path in "${DETECTED_SUBMODULES[@]}"; do
        if [[ ! -d "$sm_path" ]]; then
            print_error "Submodule directory '$sm_path' not found."
            print_info "Try: git submodule update --init${RECURSIVE:+ --recursive}"
            exit 1
        fi

        if [[ ! -d "$sm_path/.git" ]] && [[ ! -f "$sm_path/.git" ]]; then
            print_error "'$sm_path' is not a git repository."
            print_info "Try: git submodule update --init${RECURSIVE:+ --recursive}"
            exit 1
        fi
    done
}

detect_submodules() {
    if [[ "$DO_SUBMODULE" != true ]]; then
        return 0
    fi

    local recursive_flag=""
    if [[ "$RECURSIVE" == true ]]; then
        recursive_flag="--recursive"
    fi

    # Read submodule paths from git
    local all_submodules=()
    while IFS= read -r line; do
        # git submodule status output: " <sha> <path> (<describe>)" or "-<sha> <path>"
        local sm_path
        sm_path=$(echo "$line" | awk '{print $2}')
        if [[ -n "$sm_path" ]]; then
            all_submodules+=("$sm_path")
        fi
    done < <(git submodule status $recursive_flag 2>/dev/null)

    if [[ ${#all_submodules[@]} -eq 0 ]]; then
        print_warning "No submodules found in this repository"
        DO_SUBMODULE=false
        return 0
    fi

    # Apply filter if --submodule-path was specified
    if [[ ${#SUBMODULE_FILTER_PATHS[@]} -gt 0 ]]; then
        for filter_path in "${SUBMODULE_FILTER_PATHS[@]}"; do
            local found=false
            for sm_path in "${all_submodules[@]}"; do
                if [[ "$sm_path" == "$filter_path" ]]; then
                    DETECTED_SUBMODULES+=("$sm_path")
                    found=true
                    break
                fi
            done
            if [[ "$found" == false ]]; then
                print_error "Specified submodule '$filter_path' not found."
                print_info "Available submodules: ${all_submodules[*]}"
                exit 1
            fi
        done
    else
        DETECTED_SUBMODULES=("${all_submodules[@]}")
    fi

    print_info "Detected ${#DETECTED_SUBMODULES[@]} submodule(s): ${DETECTED_SUBMODULES[*]}"
}

################################################################################
# AI COMMIT MESSAGE GENERATION
################################################################################

generate_ai_commit_message() {
    local diff_output="$1"
    local repo_name="$2"

    if [[ -z "$AI_API_KEY" ]]; then
        print_error "AI commit message generation requires OPENAI_API_KEY environment variable"
        print_info "Set it with: export OPENAI_API_KEY='your-key-here'"
        return 1
    fi

    print_info "Generating commit message using AI ($AI_MODEL)..."

    # Prepare the prompt
    local prompt="Based on the following git diff, generate a concise, conventional commit message (e.g., feat:, fix:, chore:, docs:).
Include a clear summary line and bullet points for key changes.

Git diff:
$diff_output

Generate a commit message following conventional commits format."

    # Create JSON payload
    local json_payload
    json_payload=$(jq -n \
        --arg model "$AI_MODEL" \
        --arg prompt "$prompt" \
        '{
            model: $model,
            messages: [
                {
                    role: "system",
                    content: "You are a helpful assistant that generates clear, concise git commit messages following conventional commits format."
                },
                {
                    role: "user",
                    content: $prompt
                }
            ],
            temperature: 0.7,
            max_tokens: 500
        }')

    # Make API request
    local response
    response=$(curl -s -X POST "$AI_ENDPOINT" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $AI_API_KEY" \
        -d "$json_payload")

    # Extract message from response
    local message
    message=$(echo "$response" | jq -r '.choices[0].message.content // empty')

    if [[ -z "$message" ]]; then
        print_error "Failed to generate AI commit message"
        print_info "API Response: $response"
        return 1
    fi

    echo "$message"
}

################################################################################
# GIT OPERATIONS
################################################################################

get_repo_status() {
    local repo_name=$1
    local repo_path=${2:-.}

    print_header "$repo_name Status"

    pushd "$repo_path" >/dev/null

    local current_branch
    current_branch=$(get_current_branch)

    print_info "Branch: $current_branch"
    print_info "Location: $(pwd)"
    echo ""

    if [[ "$VERBOSE" == true ]]; then
        git status
    else
        git status -s
    fi
    echo ""

    popd >/dev/null

    echo "$current_branch"
}

handle_unstaged_and_untracked() {
    local repo_name=$1

    # Check for unstaged changes
    if has_unstaged_changes && [[ "$PROMPT_FOR_UNSTAGED" == true ]] && [[ "$STAGE_ALL_FLAG" != true ]]; then
        echo ""
        print_warning "Unstaged changes detected in $repo_name"
        git status -s
        echo ""
        echo "Options:"
        echo "  1) Stage all changes (git add -A)"
        echo "  2) Stage tracked files only (git add -u)"
        echo "  3) Interactive staging (git add -i)"
        echo "  4) Skip staging (use only already staged files)"
        echo "  5) Abort"
        echo ""
        local choice
        read -rp "$(echo -e "${CYAN}Choose an option [1-5]:${NC} ")" choice

        case $choice in
            1)
                git add -A
                print_success "Staged all changes"
                ;;
            2)
                git add -u
                print_success "Staged tracked files"
                ;;
            3)
                git add -i
                ;;
            4)
                print_info "Using only staged files"
                ;;
            5)
                print_error "Aborted by user"
                exit 1
                ;;
            *)
                print_error "Invalid choice. Aborting."
                exit 1
                ;;
        esac
        echo ""
    fi

    # Check for untracked files
    if has_untracked_files && [[ "$PROMPT_FOR_UNTRACKED" == true ]] && [[ "$STAGE_ALL_FLAG" != true ]]; then
        echo ""
        print_warning "Untracked files detected in $repo_name"
        git ls-files --others --exclude-standard
        echo ""
        if confirm "Stage untracked files?"; then
            git add -A
            print_success "Staged untracked files"
        else
            print_info "Untracked files will not be included in commit"
        fi
        echo ""
    fi
}

stage_files() {
    local repo_name=$1

    # Handle --all flag (stage everything no questions asked)
    if [[ "$STAGE_ALL_FLAG" == true ]]; then
        print_info "Staging all changes (--all flag)"
        git add -A
        echo ""
        print_info "Staged changes:"
        git diff --cached --stat
        echo ""
        return
    fi

    # Handle specific files
    if [[ ${#ADDITIONAL_FILES[@]} -gt 0 ]]; then
        print_info "Staging specific files: ${ADDITIONAL_FILES[*]}"
        git add "${ADDITIONAL_FILES[@]}"
    elif [[ "$STAGE_TRACKED_ONLY" == true ]]; then
        print_info "Staging tracked files only (git add -u)"
        git add -u
    elif [[ "$STAGE_INTERACTIVE" == true ]]; then
        print_info "Interactive staging..."
        git add -i
    fi

    # Handle unstaged and untracked files with prompts
    handle_unstaged_and_untracked "$repo_name"

    echo ""
    if has_staged_changes; then
        print_info "Staged changes:"
        git diff --cached --stat
    else
        print_warning "No changes staged"
    fi
    echo ""
}

get_commit_message() {
    local repo_name=$1
    local is_submodule=$2
    local message=""

    # Priority order:
    # 1. Repo-specific message (SUB_MESSAGE or MAIN_MESSAGE)
    # 2. General COMMIT_MESSAGE
    # 3. Auto-generate from AI
    # 4. Prompt user or use editor

    if [[ "$is_submodule" == true ]] && [[ -n "$SUB_MESSAGE" ]]; then
        message="$SUB_MESSAGE"
    elif [[ "$is_submodule" == false ]] && [[ -n "$MAIN_MESSAGE" ]]; then
        message="$MAIN_MESSAGE"
    elif [[ -n "$COMMIT_MESSAGE" ]]; then
        message="$COMMIT_MESSAGE"
    elif [[ "$COMMIT_MESSAGE_AUTO" == true ]]; then
        local diff_output
        diff_output=$(git diff --cached)
        message=$(generate_ai_commit_message "$diff_output" "$repo_name")
        if [[ $? -ne 0 ]] || [[ -z "$message" ]]; then
            print_error "Failed to generate AI commit message"
            exit 1
        fi
        print_success "Generated commit message:"
        echo "$message"
        echo ""
        if [[ "$INTERACTIVE" == true ]]; then
            if ! confirm "Use this commit message?"; then
                print_info "Please enter commit message manually:"
                read -r message
            fi
        fi
    fi

    echo "$message"
}

commit_changes() {
    local repo_name=$1
    local branch=$2
    local is_submodule=${3:-false}

    print_header "Committing $repo_name"

    # Stage files first
    stage_files "$repo_name"

    # Check if there are changes to commit
    if ! has_staged_changes; then
        print_warning "No changes staged for commit in $repo_name"
        return 1
    fi

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would commit to $repo_name ($branch)"
        local msg
        msg=$(get_commit_message "$repo_name" "$is_submodule")
        print_info "[DRY RUN] Message: ${msg:-<would use editor>}"
        return 0
    fi

    if [[ "$INTERACTIVE" == true ]]; then
        echo ""
        print_info "Ready to commit to $repo_name ($branch)"
        print_info "Staged files:"
        git diff --cached --name-status
        echo ""
        if ! confirm "Proceed with commit?"; then
            print_warning "Skipping commit for $repo_name"
            return 1
        fi
    fi

    # Determine how to commit
    local message
    message=$(get_commit_message "$repo_name" "$is_submodule")

    if [[ -n "$COMMIT_MESSAGE_FILE" ]]; then
        # Commit with message from file
        git commit -F "$COMMIT_MESSAGE_FILE"
    elif [[ -n "$message" ]]; then
        # Commit with provided message
        git commit -m "$message"
    elif [[ "$USE_GIT_EDITOR" == true ]]; then
        # Use editor (default git behavior)
        if [[ "$STAGE_ALL_FLAG" == true ]]; then
            git commit --all --verbose
        else
            git commit --verbose
        fi
    elif [[ -n "$COMMIT_MESSAGE_EDITOR" ]]; then
        # Use specific editor
        EDITOR="$COMMIT_MESSAGE_EDITOR" git commit
    else
        # Default: use git's default editor
        git commit --verbose
    fi

    print_success "Committed to $repo_name"
    print_info "Latest commit:"
    git log --oneline -1
    echo ""

    return 0
}

push_changes() {
    local repo_name=$1
    local branch=$2

    print_header "Pushing $repo_name"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would push $repo_name to origin/$branch"
        if [[ "$FORCE_OPERATIONS" == true ]]; then
            print_warning "[DRY RUN] With --force flag"
        fi
        return 0
    fi

    # Safety check for main/master branches with force
    if [[ "$FORCE_OPERATIONS" == true ]] && [[ "$branch" =~ ^(main|master)$ ]]; then
        print_error "Refusing to force push to $branch branch!"
        print_warning "This is extremely dangerous and can destroy team history."
        if [[ "$INTERACTIVE" == true ]]; then
            if ! confirm "Are you ABSOLUTELY sure you want to force push to $branch?"; then
                print_warning "Skipping force push for $repo_name"
                return 1
            fi
        else
            print_error "Use --interactive flag to confirm force push to $branch"
            return 1
        fi
    fi

    # Check if remote branch exists
    if ! remote_branch_exists "$branch"; then
        print_warning "Remote branch 'origin/$branch' does not exist"
        if [[ "$INTERACTIVE" == true ]] || [[ "$CONFIRM_PUSH" == true ]]; then
            if confirm "Create new remote branch 'origin/$branch'?"; then
                git push -u origin "$branch"
                print_success "Pushed $repo_name to origin/$branch (new branch)"
                return 0
            else
                print_warning "Skipping push for $repo_name"
                return 1
            fi
        else
            print_info "Creating new remote branch 'origin/$branch'"
            git push -u origin "$branch"
            print_success "Pushed $repo_name to origin/$branch (new branch)"
            return 0
        fi
    fi

    if [[ "$INTERACTIVE" == true ]] || [[ "$CONFIRM_PUSH" == true ]]; then
        echo ""
        print_info "Ready to push $repo_name to origin/$branch"
        if [[ "$FORCE_OPERATIONS" == true ]]; then
            print_warning "This will be a FORCE PUSH!"
        fi
        if ! confirm "Proceed with push?"; then
            print_warning "Skipping push for $repo_name"
            return 1
        fi
    fi

    # Perform push
    if [[ "$FORCE_OPERATIONS" == true ]]; then
        print_warning "Force pushing $repo_name..."
        git push --force origin "$branch"
        print_success "Force pushed $repo_name to origin/$branch"
    else
        git push origin "$branch"
        print_success "Pushed $repo_name to origin/$branch"
    fi
    echo ""

    return 0
}

pull_changes() {
    local repo_name=$1
    local branch=$2

    print_info "Pulling latest changes for $repo_name..."

    if [[ "$DRY_RUN" == true ]]; then
        print_info "[DRY RUN] Would pull $repo_name from origin/$branch"
        return 0
    fi

    # Check if working tree is clean
    if ! is_clean_working_tree; then
        print_warning "Working tree is dirty in $repo_name"
        if [[ "$INTERACTIVE" == true ]]; then
            if confirm "Stash changes before pull?"; then
                git stash push -m "Auto-stash before pull by git-workflow.sh"
                print_info "Changes stashed"
            else
                print_error "Cannot pull with dirty working tree"
                return 1
            fi
        else
            print_error "Cannot pull with dirty working tree. Use --interactive or commit/stash changes."
            return 1
        fi
    fi

    if [[ "$PULL_REBASE" == true ]]; then
        git pull --rebase origin "$branch"
    else
        git pull origin "$branch"
    fi

    print_success "Pulled latest changes for $repo_name"
    echo ""
}

################################################################################
# WORKFLOW FUNCTIONS
################################################################################

process_submodules() {
    if [[ "$DO_SUBMODULE" != true ]]; then
        return 0
    fi

    if [[ ${#DETECTED_SUBMODULES[@]} -eq 0 ]]; then
        return 0
    fi

    for sm_path in "${DETECTED_SUBMODULES[@]}"; do
        local sm_name
        sm_name=$(basename "$sm_path")

        print_header "Processing Submodule: $sm_path"

        cd "$PROJECT_ROOT/$sm_path"

        # Auto-detect branch (--sub-branch overrides all)
        local branch="$SUB_BRANCH"
        if [[ -z "$branch" ]]; then
            branch=$(get_current_branch)
            print_info "Auto-detected branch for $sm_path: $branch"
        fi

        # Interactive branch confirmation
        if [[ "$INTERACTIVE" == true ]]; then
            local response
            read -rp "$(echo -e "${CYAN}Branch for $sm_path [$branch]:${NC} ")" response
            if [[ -n "$response" ]]; then
                branch="$response"
            fi
        fi

        # Pull before if requested
        if [[ "$PULL_BEFORE" == true ]]; then
            pull_changes "$sm_path" "$branch"
        fi

        # Show status
        get_repo_status "$sm_path" "." >/dev/null

        # Commit
        local committed=false
        if [[ "$DO_COMMIT" == true ]]; then
            if commit_changes "$sm_path" "$branch" true; then
                committed=true
                COMMITTED_SUBMODULES+=("$sm_path")
            fi
        fi

        # Push
        if [[ "$DO_PUSH" == true ]] && [[ "$committed" == true ]]; then
            push_changes "$sm_path" "$branch"
        fi

        cd "$PROJECT_ROOT"
    done
}

process_main_repo() {
    if [[ "$DO_MAIN" != true ]]; then
        return 0
    fi

    print_header "Processing Main Repository"

    cd "$PROJECT_ROOT"

    # Auto-detect branch if not specified
    if [[ -z "$MAIN_BRANCH" ]]; then
        MAIN_BRANCH=$(get_current_branch)
        print_info "Auto-detected main branch: $MAIN_BRANCH"
    fi

    # Interactive branch confirmation
    if [[ "$INTERACTIVE" == true ]]; then
        local response
        read -rp "$(echo -e "${CYAN}Main repo branch [$MAIN_BRANCH]:${NC} ")" response
        if [[ -n "$response" ]]; then
            MAIN_BRANCH="$response"
        fi
    fi

    # Pull before if requested
    if [[ "$PULL_BEFORE" == true ]]; then
        pull_changes "Main Repo" "$MAIN_BRANCH"
    fi

    # Show status
    get_repo_status "Main Repository" "." >/dev/null

    # If any submodules were committed, update their references
    if [[ ${#COMMITTED_SUBMODULES[@]} -gt 0 ]]; then
        print_info "Updating submodule references in main repo..."
        for sm_path in "${COMMITTED_SUBMODULES[@]}"; do
            git add "$sm_path"
            print_info "  Updated reference: $sm_path"
        done
    fi

    # Commit
    if [[ "$DO_COMMIT" == true ]]; then
        if commit_changes "Main Repository" "$MAIN_BRANCH" false; then
            MAIN_COMMITTED=true
        fi
    fi

    # Push
    if [[ "$DO_PUSH" == true ]] && [[ "$MAIN_COMMITTED" == true ]]; then
        push_changes "Main Repository" "$MAIN_BRANCH"
    fi
}

################################################################################
# MAIN EXECUTION
################################################################################

show_usage() {
    cat << EOF
${BOLD}Git Workflow Script - Submodule & Main Repo Management${NC}

${BOLD}USAGE:${NC}
    $0 [OPTIONS]

${BOLD}DESCRIPTION:${NC}
    Manages git commits and pushes across all submodules and the main repository.
    Works with any git repo — auto-detects submodules at runtime.
    Default workflow: commit submodules → commit main → push submodules → push main

${BOLD}OPTIONS:${NC}
    ${BOLD}Mode:${NC}
    -i, --interactive           Interactive mode (prompts at each step)
    -n, --dry-run              Show what would happen without executing
    -q, --quiet                Minimal output
    -v, --verbose              Verbose output (default)
    -h, --help                 Show this help message

    ${BOLD}Repository Selection:${NC}
    --main                     Process main repo only
    --no-main                  Skip main repo
    --submodule                Process submodule(s) only
    --no-submodule             Skip all submodules
    --submodule-path PATH      Process only this submodule (repeatable)
    -r, --recursive            Include nested submodules (recursive)

    ${BOLD}Operations:${NC}
    --commit-only              Only commit, don't push
    --push                     Enable pushing (default when using -m)
    --no-push                  Disable pushing
    --confirm-push             Confirm before each push
    --force                    Force push (use with extreme caution!)
    --all                      Stage all changes without prompts (git add -A)

    ${BOLD}Branches:${NC}
    --main-branch BRANCH       Main repo branch (default: current)
    --sub-branch BRANCH        Submodule branch (default: current)

    ${BOLD}Commit Message:${NC}
    -m, --message MSG          Commit message for both repos
    --sub-message MSG          Commit message for submodule only
    --main-message MSG         Commit message for main repo only
    -F, --file FILE            Read commit message from file
    --editor [EDITOR]          Use editor for commit message (default: git config)
    --auto, --generate         Auto-generate commit message using AI
                               Requires OPENAI_API_KEY environment variable

    ${BOLD}Staging:${NC}
    -a, --all                  Stage all changes without prompts (git add -A)
    -u, --update               Stage tracked files only (git add -u)
    -p, --patch                Interactive staging (git add -i)
    --no-prompt-unstaged       Don't prompt for unstaged files
    --no-prompt-untracked      Don't prompt for untracked files
    FILES...                   Stage specific files (as final arguments)

    ${BOLD}Hooks:${NC}
    --run-before CMD           Execute command before workflow
    --run-after CMD            Execute command after workflow
    --pull-before              Pull before committing
    --pull-rebase              Use rebase when pulling

${BOLD}EXAMPLES:${NC}
    ${BOLD}Basic usage:${NC}
    # Default: prompt for staging, use editor, commit all submodules + main
    $0

    # Commit with message (automatically enables push)
    $0 -m "feat: add new feature"

    # Stage all and commit everything with message
    $0 --all -m "chore: update all files"

    # Interactive mode with custom message
    $0 -i -m "feat: add authentication"

    # Include nested submodules
    $0 --recursive --all -m "chore: update everything"

    ${BOLD}Advanced usage:${NC}
    # Commit only, no push
    $0 --commit-only -m "wip: work in progress"

    # Main repo only, specific branch
    $0 --no-submodule --main-branch dev/feature -m "docs: update README"

    # Only process a specific submodule
    $0 --submodule-path Backend -m "fix: backend bug"

    # Multiple specific submodules
    $0 --submodule-path Backend --submodule-path libs/shared -m "chore: update"

    # Different messages for submodule and main
    $0 --sub-message "fix: backend bug" --main-message "chore: update backend ref"

    # AI-generated commit message
    $0 --auto --all

    # Pull before, then commit and push both
    $0 --pull-before -m "chore: sync and update"

    ${BOLD}Force operations (DANGEROUS):${NC}
    # Force push (will prompt for confirmation on main/master)
    $0 --force -m "fix: corrected history" --confirm-push

    ${BOLD}Custom hooks:${NC}
    # Run tests before committing
    $0 --run-before "npm test" -m "feat: new feature"

    # With editor
    $0 --editor vim --all

${BOLD}ENVIRONMENT VARIABLES:${NC}
    OPENAI_API_KEY      API key for AI commit message generation
    OPENAI_MODEL        Model to use (default: gpt-4)
    OPENAI_ENDPOINT     API endpoint (default: OpenAI)

${BOLD}WORKFLOW ORDER:${NC}
    1. Run --run-before command (if specified)
    2. Pull changes (if --pull-before specified)
    3. Process Each Submodule (in order detected):
       - Check status
       - Stage files (with prompts or --all)
       - Commit
       - Push (if enabled)
    4. Process Main Repository:
       - Check status
       - Update submodule references (for any submodules that changed)
       - Stage files
       - Commit
       - Push (if enabled)
    5. Run --run-after command (if specified)

EOF
}

parse_arguments() {
    local parsing_files=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -i|--interactive)
                INTERACTIVE=true
                shift
                ;;
            -n|--dry-run)
                DRY_RUN=true
                shift
                ;;
            -q|--quiet)
                VERBOSE=false
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            --main)
                DO_MAIN=true
                DO_SUBMODULE=false
                shift
                ;;
            --no-main)
                DO_MAIN=false
                shift
                ;;
            --submodule)
                DO_SUBMODULE=true
                DO_MAIN=false
                shift
                ;;
            --no-submodule)
                DO_SUBMODULE=false
                shift
                ;;
            --submodule-path)
                SUBMODULE_FILTER_PATHS+=("$2")
                shift 2
                ;;
            -r|--recursive)
                RECURSIVE=true
                shift
                ;;
            --commit-only)
                COMMIT_ONLY=true
                DO_PUSH=false
                shift
                ;;
            --push)
                DO_PUSH=true
                shift
                ;;
            --no-push)
                DO_PUSH=false
                shift
                ;;
            --confirm-push)
                CONFIRM_PUSH=true
                shift
                ;;
            --force)
                FORCE_OPERATIONS=true
                shift
                ;;
            --main-branch)
                MAIN_BRANCH="$2"
                shift 2
                ;;
            --sub-branch)
                SUB_BRANCH="$2"
                shift 2
                ;;
            -m|--message)
                COMMIT_MESSAGE="$2"
                # Auto-enable push when message is provided
                DO_PUSH=true
                shift 2
                ;;
            --sub-message)
                SUB_MESSAGE="$2"
                shift 2
                ;;
            --main-message)
                MAIN_MESSAGE="$2"
                shift 2
                ;;
            -F|--file)
                COMMIT_MESSAGE_FILE="$2"
                shift 2
                ;;
            --editor)
                if [[ -n "${2:-}" ]] && [[ ! "$2" =~ ^- ]]; then
                    COMMIT_MESSAGE_EDITOR="$2"
                    shift 2
                else
                    USE_GIT_EDITOR=true
                    shift
                fi
                ;;
            --auto|--generate)
                COMMIT_MESSAGE_AUTO=true
                shift
                ;;
            -a|--all)
                STAGE_ALL_FLAG=true
                PROMPT_FOR_UNSTAGED=false
                PROMPT_FOR_UNTRACKED=false
                shift
                ;;
            -u|--update)
                STAGE_TRACKED_ONLY=true
                shift
                ;;
            -p|--patch)
                STAGE_INTERACTIVE=true
                shift
                ;;
            --no-prompt-unstaged)
                PROMPT_FOR_UNSTAGED=false
                shift
                ;;
            --no-prompt-untracked)
                PROMPT_FOR_UNTRACKED=false
                shift
                ;;
            --run-before)
                RUN_BEFORE="$2"
                shift 2
                ;;
            --run-after)
                RUN_AFTER="$2"
                shift 2
                ;;
            --pull-before)
                PULL_BEFORE=true
                shift
                ;;
            --pull-rebase)
                PULL_REBASE=true
                PULL_BEFORE=true
                shift
                ;;
            --)
                # Everything after -- is treated as files
                shift
                parsing_files=true
                ;;
            -*)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
            *)
                # Treat remaining args as files to stage
                ADDITIONAL_FILES+=("$1")
                shift
                ;;
        esac
    done
}

main() {
    # Parse command line arguments
    parse_arguments "$@"

    # Store project root
    PROJECT_ROOT=$(pwd)

    # Validation
    validate_git_repo
    detect_submodules
    validate_submodules

    # Track what was committed
    MAIN_COMMITTED=false

    # Show configuration in interactive mode
    if [[ "$INTERACTIVE" == true ]]; then
        print_header "Configuration"
        print_info "Submodules: $([ "$DO_SUBMODULE" == true ] && echo "✓ (${#DETECTED_SUBMODULES[@]} found)" || echo "✗")"
        if [[ "$DO_SUBMODULE" == true ]] && [[ ${#DETECTED_SUBMODULES[@]} -gt 0 ]]; then
            for sm in "${DETECTED_SUBMODULES[@]}"; do
                print_info "  - $sm"
            done
        fi
        print_info "Recursive: $([ "$RECURSIVE" == true ] && echo "✓" || echo "✗")"
        print_info "Main repo: $([ "$DO_MAIN" == true ] && echo "✓" || echo "✗")"
        print_info "Commit: $([ "$DO_COMMIT" == true ] && echo "✓" || echo "✗")"
        print_info "Push: $([ "$DO_PUSH" == true ] && echo "✓" || echo "✗")"
        print_info "Pull before: $([ "$PULL_BEFORE" == true ] && echo "✓" || echo "✗")"
        print_info "Stage all: $([ "$STAGE_ALL_FLAG" == true ] && echo "✓" || echo "✗")"
        print_info "Force operations: $([ "$FORCE_OPERATIONS" == true ] && echo "✓ (DANGEROUS)" || echo "✗")"
        echo ""
        if ! confirm "Continue with this configuration?"; then
            print_warning "Aborted by user"
            exit 0
        fi
    fi

    # Display header
    print_header "Git Workflow Script"
    if [[ "$DRY_RUN" == true ]]; then
        print_warning "DRY RUN MODE - No changes will be made"
    fi

    # Run before hook
    if [[ -n "$RUN_BEFORE" ]]; then
        print_info "Executing pre-workflow command: $RUN_BEFORE"
        if [[ "$DRY_RUN" != true ]]; then
            eval "$RUN_BEFORE"
        fi
        echo ""
    fi

    # Execute workflow
    process_submodules
    process_main_repo

    # Run after hook
    if [[ -n "$RUN_AFTER" ]]; then
        print_info "Executing post-workflow command: $RUN_AFTER"
        if [[ "$DRY_RUN" != true ]]; then
            eval "$RUN_AFTER"
        fi
        echo ""
    fi

    # Final summary
    print_header "Workflow Complete"

    if [[ "$DO_SUBMODULE" == true ]] && [[ ${#DETECTED_SUBMODULES[@]} -gt 0 ]]; then
        for sm_path in "${DETECTED_SUBMODULES[@]}"; do
            cd "$PROJECT_ROOT/$sm_path"
            print_info "$sm_path latest commits:"
            git log --oneline -3
            echo ""
            cd "$PROJECT_ROOT"
        done
    fi

    if [[ "$DO_MAIN" == true ]]; then
        print_info "Main repo latest commits:"
        git log --oneline -3
        echo ""
    fi

    print_success "All operations completed successfully!"

    if [[ "$DRY_RUN" == true ]]; then
        print_warning "This was a DRY RUN - no actual changes were made"
    fi
}

# Run main function with all arguments
main "$@"
