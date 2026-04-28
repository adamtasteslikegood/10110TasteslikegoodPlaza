#!/bin/zsh
# List recent Cloud Run revision names for one or more services
# Usage: list_revisions [-n N] [-s NAME] [-S NAME,...] [-p NAME] [-r NAME] [-h]
#        list_revisions --num N --service NAME --Services NAME,... --project NAME --region NAME --help
#
# To run as a command, add this script to your $PATH or create an alias in your .zshrc:
#   alias list_revisions="/full/path/to/scripts/list_revisions.sh"
# Or copy/move to a directory in $PATH and chmod +x.

# Defaults
NUM=3
PROJECT="comdottasteslikegood"
REGION="us-central1"
SERVICES=()

# ANSI color codes
COLOR_RESET="\033[0m"
COLOR_CYAN="\033[1;36m"
COLOR_GRAY="\033[2;37m"
COLOR_RED="\033[1;31m"
COLOR_YELLOW="\033[1;33m"

# Helper: add service(s) to SERVICES array, splitting comma-separated
add_services() {
  local input="$1"
  # Split by comma
  for svc in ${(s/,/)input}; do
    svc="${svc// /}"  # Remove spaces
    if [[ -n "$svc" ]]; then
      SERVICES+="$svc"
    fi
  done
}

# Helper: print error in red
print_error() {
  echo -e "${COLOR_RED}$1${COLOR_RESET}"
}

# Helper: print help in yellow/cyan
print_help() {
  echo -e "${COLOR_YELLOW}Usage:${COLOR_RESET}"
  echo -e "  list_revisions [-n N] [-s NAME] [-S NAME,...] [-p NAME] [-r NAME] [-h]"
  echo -e "  list_revisions --num N --service NAME --Services NAME,... --project NAME --region NAME --help"
  echo
  echo -e "${COLOR_YELLOW}Arguments:${COLOR_RESET}"
  echo -e "  ${COLOR_CYAN}-n, --num${COLOR_RESET}         Number of recent revisions to list (default: 3)"
  echo -e "  ${COLOR_CYAN}-s, --service${COLOR_RESET}     Service name (repeat or comma-separated for multiple)"
  echo -e "  ${COLOR_CYAN}-S, --Services${COLOR_RESET}    Same as --service, accepts comma-separated list"
  echo -e "  ${COLOR_CYAN}-p, --project${COLOR_RESET}     GCP project name (default: comdottasteslikegood)"
  echo -e "  ${COLOR_CYAN}-r, --region${COLOR_RESET}      GCP region (default: us-central1)"
  echo -e "  ${COLOR_CYAN}-h, --help${COLOR_RESET}        Show this help message and exit"
  echo
  echo -e "${COLOR_YELLOW}Examples:${COLOR_RESET}"
  echo -e "  list_revisions -s flask-backend -s express-frontend"
  echo -e "  list_revisions -S flask-backend,express-frontend,flask-migration"
  echo -e "  list_revisions --service flask-migration --Services express-frontend,flask-migration"
  echo
  echo -e "${COLOR_YELLOW}To run as a command:${COLOR_RESET}"
  echo -e "  Add to your PATH or alias in .zshrc, e.g.:"
  echo -e "    alias list_revisions=\"/full/path/to/scripts/list_revisions.sh\""
  echo
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -n|--num)
      NUM="$2"
      shift 2
      ;;
    -p|--project)
      PROJECT="$2"
      shift 2
      ;;
    -r|--region)
      REGION="$2"
      shift 2
      ;;
    -s|--service|-S|--Services|--services|--Service)
      add_services "$2"
      shift 2
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      print_error "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# If no services specified, use default
if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=("flask-backend" "express-frontend")
fi

# Remove duplicates, preserve order
typeset -A seen
SERVICES=(${(u)SERVICES})

for SERVICE in $SERVICES; do
  echo -e "${COLOR_CYAN}Listing $NUM most recent revisions for service '$SERVICE' in project '$PROJECT', region '$REGION'...${COLOR_RESET}"
  gcloud run revisions list \
    --service="$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --sort-by=~creationTimestamp \
    --limit="$NUM" \
    --format="value(metadata.name)"
  echo -e "${COLOR_GRAY}---${COLOR_RESET}"
done
