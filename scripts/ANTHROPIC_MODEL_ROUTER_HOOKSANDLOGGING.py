#!/usr/bin/env python3
import os
import sys
import json
import time
from datetime import datetime, timezone
from anthropic import Anthropic

# Configuration Paths & Constants
LOG_FILE_PATH = os.path.expanduser("~/.claude/router_metrics.log")
MODEL_HAIKU = "claude-3-5-haiku-latest"
MODEL_OPUS_4_6 = "claude-4-6-opus"
MODEL_OPUS_4_8 = "claude-4-8-opus"

# Setup the classification client
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
api_client = Anthropic(api_key=API_KEY) if API_KEY else None

def write_to_append_log(log_data: dict):
    """
    Safely opens and appends structured routing data to a continuous 
    local log file for historical analytics.
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        
        # Open in append mode ('a') to prevent overwriting existing history
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        sys.stderr.write(f"Logging Error: {str(e)}\n")

def classify_task_complexity(user_prompt: str) -> tuple[str, float]:
    """
    Uses a fast API triage call to classify the prompt complexity, 
    returning the assigned model tier alongside precise elapsed latency.
    """
    if not api_client:
        return "OPUS_4_6", 0.0  # Zero delay if relying on default routing
        
    router_system_prompt = (
        "You are an elite triage router. Analyze the user's prompt and respond "
        "with EXACTLY one of these strings and absolutely nothing else:\n"
        "- 'OPUS_4_8': Complex debugging, multi-file refactoring, abstract architecture.\n"
        "- 'OPUS_4_6': Standard boilerplate, script modifications, direct fast tasks.\n"
        "- 'HAIKU': Data extraction, formatting, markdown formatting."
    )
    
    start_time = time.perf_counter()
    try:
        response = api_client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=10,
            temperature=0.0,
            system=router_system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return response.content.text.strip().upper(), elapsed_ms
    except Exception:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return "OPUS_4_6", elapsed_ms

def main():
    # Capture the absolute entry time of the hook execution lifecycle
    hook_start_time = time.perf_counter()
    user_prompt = "UNKNOWN"
    
    try:
        # 1. Read prompt structure piped out from Claude Code
        input_data = sys.stdin.read()
        if not input_data:
            sys.exit(0)
            
        event_payload = json.loads(input_data)
        user_prompt = event_payload.get("prompt", "")
        
        # 2. Run classifier & compute latency
        decision, classification_ms = classify_task_complexity(user_prompt)
        
        # Map decision to official API model string
        if decision == "OPUS_4_8":
            target_model = MODEL_OPUS_4_8
        elif decision == "HAIKU":
            target_model = MODEL_HAIKU
        else:
            target_model = MODEL_OPUS_4_6
            
        # 3. Construct response structure for the terminal engine
        response_payload = {
            "status": "success",
            "modifiers": {
                "model": target_model
            }
        }
        
        # Write payload immediately to release Claude Code execution loop
        sys.stdout.write(json.dumps(response_payload))
        sys.stdout.flush()
        
        # 4. Compute full script execution metrics and append to log file
        total_hook_ms = (time.perf_counter() - hook_start_time) * 1000
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_sample": user_prompt[:60] + "..." if len(user_prompt) > 60 else user_prompt,
            "routed_model": target_model,
            "classification_latency_ms": round(classification_ms, 2),
            "total_hook_latency_ms": round(total_hook_ms, 2),
            "status": "SUCCESS"
        }
        write_to_append_log(log_entry)
        
    except Exception as e:
        total_hook_ms = (time.perf_counter() - hook_start_time) * 1000
        error_log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt_sample": user_prompt[:60] + "...",
            "routed_model": MODEL_OPUS_4_6, # Default fallback choice
            "classification_latency_ms": 0.0,
            "total_hook_latency_ms": round(total_hook_ms, 2),
            "status": f"ERROR: {str(e)}"
        }
        write_to_append_log(error_log)
        
        # Exit silently to keep terminal execution uninterrupted
        sys.exit(0)

if __name__ == "__main__":
    main()
