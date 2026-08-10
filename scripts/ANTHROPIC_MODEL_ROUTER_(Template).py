import os
import sys
import json
import subprocess
from anthropic import Anthropic

# Define model string constants
MODEL_HAIKU = "claude-3-5-haiku-latest"
MODEL_OPUS_4_6 = "claude-4-6-opus"
MODEL_OPUS_4_8 = "claude-4-8-opus"

# Setup the Standard API Fallback client
# If ANTHROPIC_API_KEY is missing, this will be handled dynamically below.
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
api_client = Anthropic(api_key=API_KEY) if API_KEY else None

def run_via_subscription(model: str, prompt: str, system_prompt: str = "", max_tokens: int = 4000) -> str:
    """
    Executes a prompt using the local machine's Claude Code session credentials,
    safely utilizing your Claude Max Subscription usage rather than API billing.
    """
    # Build a clean command targeting the subscription engine via Claude Code CLI
    # It passes the requested model variant and instructions explicitly
    full_prompt = f"{system_prompt}\n\nTask: {prompt}" if system_prompt else prompt
    
    cmd = [
        "claude-code", 
        "run", 
        "--model", model, 
        "--max-tokens", str(max_tokens),
        "--non-interactive", # Prevents terminal from hanging on user input
        full_prompt
    ]
    
    try:
        # Execute the process locally using the machine's active subscription token
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Subscription run failed: {e.stderr}", file=sys.stderr)
        raise e
    except FileNotFoundError:
        print("❌ 'claude-code' CLI not found. Make sure it is installed globally (`npm install -g @anthropic-ai/claude-code`) and you are logged in.", file=sys.stderr)
        raise

def classify_task_complexity(user_prompt: str) -> str:
    """
    Uses Haiku to quickly triage the request. If an API key exists, it uses it for 
    the fast categorization. Otherwise, it defaults directly to standard Opus 4.6.
    """
    router_system_prompt = (
        "You are an elite triage router for LLM workloads. Analyze the user's prompt "
        "and determine the execution tier.\n\n"
        "Respond with EXACTLY one of these strings and absolutely nothing else:\n"
        "- 'OPUS_4_8': Complex debugging, deep reasoning, multi-file refactoring, abstract architecture.\n"
        "- 'OPUS_4_6': Standard boilerplate, direct script adjustments, explanations, fast coding.\n"
        "- 'HAIKU': Basic text transforms, data extraction, simple formatting."
    )
    
    # If API key is active, use it for the cheap triage step
    if api_client:
        try:
            response = api_client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=10,
                temperature=0.0,
                system=router_system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            return response.content[0].text.strip().upper()
        except Exception:
            pass # Fallback to default if API endpoint drops or hits rate limits
            
    # Default safe fallback if API is not configured or fails
    return "OPUS_4_6"

def route_and_execute(user_prompt: str, system_prompt: str = ""):
    """
    Dynamically routes the prompt. Prioritizes Subscription Usage via Claude Code,
    falling back entirely to the Anthropic API key if requested.
    """
    # 1. Classify the task
    decision = classify_task_complexity(user_prompt)
    
    # 2. Map decision token to actual model endpoint
    if decision == "OPUS_4_8":
        target_model = MODEL_OPUS_4_8
        reason = "Deep reasoning/Self-correction needed"
    elif decision == "HAIKU":
        target_model = MODEL_HAIKU
        reason = "Low complexity data/format task"
    else:
        target_model = MODEL_OPUS_4_6
        reason = "Pragmatic execution, direct speed optimized"
        
    # 3. Determine execution channel (Subscription vs API Key Fallback)
    if not api_client:
        print(f"💳 [Subscription Mode] Routing to {target_model} ({reason})")
        try:
            return run_via_subscription(target_model, user_prompt, system_prompt)
        except Exception:
            print("⚠️ Subscription execution failed. No fallback API key available.", file=sys.stderr)
            return None
    else:
        print(f"💰 [API Paid Mode] Routing to {target_model} ({reason})")
        try:
            response = api_client.messages.create(
                model=target_model,
                max_tokens=4000,
                temperature=0.5,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            return response.content[0].text
        except Exception as api_err:
            print(f"⚠️ API execution failed: {api_err}. Attempting Subscription fallback...", file=sys.stderr)
            return run_via_subscription(target_model, user_prompt, system_prompt)

# --- Example Usage ---
if __name__ == "__main__":
    # Ensure you have run `claude-code login` in your shell before testing this script!
    sample_prompt = "Review this script for asynchronous race conditions and provide a lightweight fix."
    result = route_and_execute(sample_prompt)
    print("\n--- Model Output ---\n", result)
