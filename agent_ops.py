"""
Agent Ops: Decoupled Multi-Agent Coordination via FalkorDB
Targeting FalkorDB Graph Hacks Hackathon:
  - Track 1: Connected Data (Multi-hop live topology traversal & blast radius analysis)
  - Track 2: Agent Memory & Coordination (Stateful asynchronous ticket handoffs & episodic memory)
"""

import os
import sys
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from falkordb import FalkorDB
from google import genai
from google.genai import types

# Load environment variables (.env)
load_dotenv()

# ANSI Color Codes for terminal UI
CYAN = "\033[96m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


def get_graph():
    """Connects to FalkorDB engine and selects the infra_ops graph."""
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", 6379))
    graph_name = os.environ.get("FALKORDB_GRAPH", "infra_ops")
    db = FalkorDB(host=host, port=port)
    return db.select_graph(graph_name)


# ----------------------------------------------------------------------
# MILESTONE 1: Decoupled Tool Layers
# ----------------------------------------------------------------------

# --- Agent 1: Diagnostic Tools ---

def trace_blast_radius(service_name: str) -> str:
    """Traces all upstream dependent services impacted by a degraded or failing target service or database.
    
    Args:
        service_name: Name of the target service or database (e.g., 'redis-session').
        
    Returns:
        JSON string containing the target service name, list of impacted upstream services, and blast radius size.
    """
    graph = get_graph()
    query = (
        "MATCH (target {name: $name})<-[:DEPENDS_ON*1..3]-(impacted) "
        "RETURN target.name AS root, collect(DISTINCT impacted.name) AS impacted, count(DISTINCT impacted) AS blast_radius_size"
    )
    result = graph.query(query, {"name": service_name})
    if result.result_set and len(result.result_set) > 0:
        row = result.result_set[0]
        root_name = row[0]
        impacted_list = row[1] if isinstance(row[1], list) else []
        size = row[2] if len(row) > 2 else len(impacted_list)
        return json.dumps({
            "target": root_name,
            "impacted_services": impacted_list,
            "blast_radius_size": size
        }, indent=2)
    return json.dumps({
        "target": service_name,
        "impacted_services": [],
        "blast_radius_size": 0
    }, indent=2)


def create_handoff_ticket(incident_id: str, target_service: str, diagnosis: str, blast_radius: list) -> str:
    """Creates an asynchronous stateful handoff ticket node in FalkorDB marked as PENDING_REMEDIATION.
    
    Args:
        incident_id: Unique incident/ticket identifier (e.g., 'INC-102').
        target_service: Name of the root cause service or database (e.g., 'redis-session').
        diagnosis: Diagnostic assessment of the failure mechanism.
        blast_radius: List of upstream services impacted by this incident.
        
    Returns:
        JSON string confirming handoff ticket creation and relationship in FalkorDB.
    """
    graph = get_graph()
    query = (
        "MERGE (h:Handoff {id: $inc_id}) "
        "SET h.status = 'PENDING_REMEDIATION', "
        "    h.diagnosis = $diagnosis, "
        "    h.blast_radius = $blast_radius, "
        "    h.created_at = timestamp() "
        "WITH h "
        "MATCH (s {name: $target_service}) "
        "MERGE (h)-[:TARGETS]->(s) "
        "RETURN h.id AS handoff_id, h.status AS status, s.name AS target"
    )
    result = graph.query(query, {
        "inc_id": incident_id,
        "diagnosis": diagnosis,
        "blast_radius": blast_radius,
        "target_service": target_service
    })
    if result.result_set and len(result.result_set) > 0:
        row = result.result_set[0]
        return json.dumps({
            "status": "success",
            "handoff_id": row[0],
            "ticket_status": row[1],
            "target_service": row[2]
        }, indent=2)
    return json.dumps({
        "status": "error",
        "message": f"Failed to create handoff ticket for '{target_service}'."
    }, indent=2)


# --- Agent 2: Remediation Tools ---

def fetch_pending_handoff() -> str:
    """Polls FalkorDB for the oldest unresolved handoff ticket with status 'PENDING_REMEDIATION'.
    
    Returns:
        JSON string containing the active ticket details or NO_PENDING_HANDOFF status.
    """
    graph = get_graph()
    query = (
        "MATCH (h:Handoff {status: 'PENDING_REMEDIATION'})-[:TARGETS]->(s) "
        "RETURN h.id AS incident_id, s.name AS target_service, h.diagnosis AS diagnosis, h.blast_radius AS blast_radius "
        "ORDER BY h.created_at ASC "
        "LIMIT 1"
    )
    result = graph.query(query)
    if result.result_set and len(result.result_set) > 0:
        row = result.result_set[0]
        return json.dumps({
            "status": "PENDING_REMEDIATION",
            "incident_id": row[0],
            "target_service": row[1],
            "diagnosis": row[2],
            "blast_radius": row[3] if isinstance(row[3], list) else []
        }, indent=2)
    return json.dumps({"status": "NO_PENDING_HANDOFF"}, indent=2)


def get_incident_memory(issue_pattern: str) -> str:
    """Searches episodic memory in FalkorDB for past incidents and verified runbooks matching an issue pattern.
    
    Args:
        issue_pattern: Keyword or phrase from the diagnosis or root cause (e.g., 'oom', 'redis-session').
        
    Returns:
        Structured JSON string containing matching historical incident records and associated verified runbook actions.
    """
    graph = get_graph()
    query = (
        "MATCH (i:Incident)-[:RESOLVED_BY]->(rb:Runbook) "
        "WHERE toLower(i.root_cause) CONTAINS toLower($pattern) "
        "   OR toLower(i.summary) CONTAINS toLower($pattern) "
        "RETURN i.id AS id, i.summary AS summary, rb.id AS runbook_id, rb.action AS action, rb.target AS target"
    )
    result = graph.query(query, {"pattern": issue_pattern})
    matches = []
    if result.result_set:
        for row in result.result_set:
            matches.append({
                "id": row[0],
                "summary": row[1],
                "runbook_id": row[2],
                "action": row[3],
                "target": row[4] if len(row) > 4 else None
            })
    return json.dumps({
        "query_pattern": issue_pattern,
        "matching_incidents": matches,
        "count": len(matches)
    }, indent=2)


def apply_fix_and_close_handoff(incident_id: str, root_cause: str, action_taken: str, target_service: str) -> str:
    """Remediates target service health, closes the handoff ticket as 'RESOLVED', and persists episodic memory.
    
    Args:
        incident_id: Identifier for the incident and handoff ticket (e.g., 'INC-102').
        root_cause: Identified root cause description.
        action_taken: Remediation action applied (e.g., 'FLUSH_STALE_SESSIONS_AND_RESIZE').
        target_service: Name of the service or database that was recovered.
        
    Returns:
        JSON string confirming ticket resolution, runbook creation, and service health recovery.
    """
    graph = get_graph()
    rb_id = f"RB-AUTO-{incident_id}"
    query = (
        "MERGE (h:Handoff {id: $inc_id}) "
        "SET h.status = 'RESOLVED', h.resolved_at = timestamp() "
        "WITH h "
        "MERGE (i:Incident {id: $inc_id}) "
        "SET i.root_cause = $root_cause, i.resolved_at = timestamp() "
        "WITH h, i "
        "MERGE (rb:Runbook {id: $rb_id, action: $action, target: $target}) "
        "MERGE (i)-[:RESOLVED_BY]->(rb) "
        "WITH h, i, rb "
        "MATCH (s {name: $target}) "
        "SET s.status = 'healthy' "
        "RETURN h.id AS handoff_id, h.status AS handoff_status, i.id AS incident_id, rb.id AS runbook_id, s.name AS target, s.status AS service_status"
    )
    result = graph.query(query, {
        "inc_id": incident_id,
        "root_cause": root_cause,
        "rb_id": rb_id,
        "action": action_taken,
        "target": target_service
    })
    if result.result_set and len(result.result_set) > 0:
        row = result.result_set[0]
        return json.dumps({
            "status": "success",
            "handoff_id": row[0],
            "handoff_status": row[1],
            "incident_id": row[2],
            "runbook_id": row[3],
            "target_service": row[4],
            "service_status": row[5]
        }, indent=2)
    return json.dumps({
        "status": "error",
        "message": f"Failed to remediate '{target_service}' or close handoff '{incident_id}'."
    }, indent=2)


# Tool execution maps
DIAGNOSTIC_TOOL_MAP = {
    "trace_blast_radius": trace_blast_radius,
    "create_handoff_ticket": create_handoff_ticket
}

REMEDIATION_TOOL_MAP = {
    "fetch_pending_handoff": fetch_pending_handoff,
    "get_incident_memory": get_incident_memory,
    "apply_fix_and_close_handoff": apply_fix_and_close_handoff
}


# ----------------------------------------------------------------------
# MILESTONE 2: Decoupled Multi-Turn Agent Orchestration
# ----------------------------------------------------------------------

import time

def call_gemini_with_retry(client, model: str, contents: list, config: types.GenerateContentConfig, max_retries: int = 5):
    """Executes client.models.generate_content with rate-limit retry backoff."""
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait_time = 30 * (attempt + 1)
                print(f"\n{BOLD}{YELLOW}⏳ Rate limit (429) hit. Pausing {wait_time}s before retry (Attempt {attempt+1}/{max_retries})...{RESET}")
                time.sleep(wait_time)
            else:
                raise e


def run_diagnostic_agent(alert_payload: str) -> str:
    """Agent 1 (Diagnostic Agent): Inspects alerts, traverses live topology, and writes a handoff ticket to FalkorDB.
    
    Args:
        alert_payload: Raw incoming operational alert text.
        
    Returns:
        Diagnostic and handoff summary report.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please set GEMINI_API_KEY in your environment or .env file.")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=api_key)

    system_instruction = (
        "You are Agent 1 (Diagnostic Agent) in an asynchronous multi-agent DevOps architecture.\n"
        "Your sole duty is to inspect operational alerts, query topology blast radiuses, determine root causes, "
        "and create a stateful `:Handoff` ticket in FalkorDB with status 'PENDING_REMEDIATION'.\n\n"
        "Instructions:\n"
        "1. Identify the primary failing root-cause node from the alert.\n"
        "2. Call `trace_blast_radius` on the failing node to determine impacted upstream services.\n"
        "3. Call `create_handoff_ticket` with a unique incident_id (e.g. 'INC-102'), target_service, diagnosis, and the blast_radius list.\n"
        "4. Do NOT attempt remediation. Once the ticket is persisted in FalkorDB, conclude your mission with a concise diagnostic handoff report.\n"
    )

    prompt = f"OPERATIONAL ALERT:\n{alert_payload}\n\nPlease diagnose this incident, trace the blast radius, and create a handoff ticket in FalkorDB."

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"{system_instruction}\n\n{prompt}")]
        )
    ]

    config = types.GenerateContentConfig(
        tools=[trace_blast_radius, create_handoff_ticket],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.1
    )

    print(f"\n{BOLD}{CYAN}{'='*72}{RESET}")
    print(f"{BOLD}{CYAN}🔎 STARTING AGENT 1 (DIAGNOSTIC AGENT){RESET}")
    print(f"{BOLD}Model:{RESET} {model_name}")
    print(f"{BOLD}Alert:{RESET} {alert_payload}")
    print(f"{BOLD}{CYAN}{'='*72}{RESET}\n")

    max_turns = 10
    turn = 0

    while turn < max_turns:
        turn += 1
        response = call_gemini_with_retry(
            client=client,
            model=model_name,
            contents=contents,
            config=config
        )

        function_calls = response.function_calls
        if not function_calls:
            final_text = response.text or "Diagnosis and handoff completed."
            print(f"\n{BOLD}{CYAN}📋 [Agent 1: Diagnostic] Diagnostic & Handoff Summary:{RESET}")
            print(f"{CYAN}{'='*72}{RESET}")
            print(final_text)
            print(f"{CYAN}{'='*72}{RESET}\n")
            return final_text

        contents.append(response.candidates[0].content)

        tool_response_parts = []
        for call in function_calls:
            fn_name = call.name
            fn_args = call.args or {}

            print(f"{BOLD}{YELLOW}🔎 [Agent 1: Diagnostic] Tool Invoked:{RESET} {BOLD}{fn_name}{RESET} | args: {json.dumps(fn_args)}")

            if fn_name in DIAGNOSTIC_TOOL_MAP:
                tool_output_str = DIAGNOSTIC_TOOL_MAP[fn_name](**fn_args)
            else:
                tool_output_str = json.dumps({"error": f"Unknown tool function: {fn_name}"})

            print(f"{BOLD}{GREEN}📥 [Agent 1: Diagnostic] Graph Return:{RESET}\n{tool_output_str}\n")

            try:
                parsed_output = json.loads(tool_output_str)
            except Exception:
                parsed_output = {"raw": tool_output_str}

            tool_response_parts.append(
                types.Part.from_function_response(
                    name=fn_name,
                    response={"result": parsed_output}
                )
            )

        contents.append(
            types.Content(
                role="user",
                parts=tool_response_parts
            )
        )

    return "Max conversation turns reached for Agent 1 without conclusion."


def run_remediation_agent() -> str:
    """Agent 2 (Remediation Agent): Decoupled agent that polls FalkorDB for active handoffs and executes runbooks.
    
    Returns:
        Remediation and post-mortem report.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please set GEMINI_API_KEY in your environment or .env file.")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=api_key)

    system_instruction = (
        "You are Agent 2 (Remediation Agent) in an asynchronous multi-agent DevOps architecture.\n"
        "You operate independently with no shared in-memory state from previous agents.\n"
        "Your duty is to poll FalkorDB for active `PENDING_REMEDIATION` handoff tickets, query episodic memory for historical runbooks, "
        "execute the remediation action, restore target service health to 'healthy', close the handoff ticket, and record new incident memory.\n\n"
        "Instructions:\n"
        "1. Call `fetch_pending_handoff` to check for active unresolved tickets.\n"
        "2. If no tickets are pending, report that queue is empty and exit.\n"
        "3. If a ticket is found, inspect its diagnosis and target_service, and call `get_incident_memory` to locate past verified runbooks.\n"
        "4. Call `apply_fix_and_close_handoff` passing the incident_id, root_cause, action_taken, and target_service.\n"
        "5. Output a comprehensive final post-mortem report detailing the remediation action, restored health, and graph memory status.\n"
    )

    prompt = "Poll FalkorDB for any active PENDING_REMEDIATION handoffs, remediate the target service, and close the ticket."

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"{system_instruction}\n\n{prompt}")]
        )
    ]

    config = types.GenerateContentConfig(
        tools=[fetch_pending_handoff, get_incident_memory, apply_fix_and_close_handoff],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.1
    )

    print(f"\n{BOLD}{MAGENTA}{'='*72}{RESET}")
    print(f"{BOLD}{MAGENTA}🔧 STARTING AGENT 2 (REMEDIATION AGENT - DECOUPLED POLL){RESET}")
    print(f"{BOLD}Model:{RESET} {model_name}")
    print(f"{BOLD}Goal:{RESET} Scan FalkorDB for PENDING_REMEDIATION handoff tickets & remediate")
    print(f"{BOLD}{MAGENTA}{'='*72}{RESET}\n")

    max_turns = 10
    turn = 0

    while turn < max_turns:
        turn += 1
        response = call_gemini_with_retry(
            client=client,
            model=model_name,
            contents=contents,
            config=config
        )

        function_calls = response.function_calls
        if not function_calls:
            final_text = response.text or "Remediation and ticket closure completed."
            print(f"\n{BOLD}{GREEN}✅ [Agent 2: Remediation] Remediation & Post-Mortem Report:{RESET}")
            print(f"{GREEN}{'='*72}{RESET}")
            print(final_text)
            print(f"{GREEN}{'='*72}{RESET}\n")
            return final_text

        contents.append(response.candidates[0].content)

        tool_response_parts = []
        for call in function_calls:
            fn_name = call.name
            fn_args = call.args or {}

            print(f"{BOLD}{YELLOW}🔧 [Agent 2: Remediation] Tool Invoked:{RESET} {BOLD}{fn_name}{RESET} | args: {json.dumps(fn_args)}")

            if fn_name in REMEDIATION_TOOL_MAP:
                tool_output_str = REMEDIATION_TOOL_MAP[fn_name](**fn_args)
            else:
                tool_output_str = json.dumps({"error": f"Unknown tool function: {fn_name}"})

            print(f"{BOLD}{GREEN}📥 [Agent 2: Remediation] Graph Return:{RESET}\n{tool_output_str}\n")

            try:
                parsed_output = json.loads(tool_output_str)
            except Exception:
                parsed_output = {"raw": tool_output_str}

            tool_response_parts.append(
                types.Part.from_function_response(
                    name=fn_name,
                    response={"result": parsed_output}
                )
            )

        contents.append(
            types.Content(
                role="user",
                parts=tool_response_parts
            )
        )

    return "Max conversation turns reached for Agent 2 without conclusion."


if __name__ == "__main__":
    alert = (
        "CRITICAL: Database 'redis-session' reported oom_killed. Client latency spiking on api-gateway."
    )
    if len(sys.argv) > 1:
        alert = " ".join(sys.argv[1:])

    print(f"\n{BOLD}{BLUE}{'#'*72}{RESET}")
    print(f"{BOLD}{BLUE}=== STEP 1: TRIGGERING DIAGNOSTIC AGENT ==={RESET}")
    print(f"{BOLD}{BLUE}{'#'*72}{RESET}")
    run_diagnostic_agent(alert)

    # Allow brief breathing space between decoupled agents
    time.sleep(3)

    print(f"\n{BOLD}{BLUE}{'#'*72}{RESET}")
    print(f"{BOLD}{BLUE}=== STEP 2: TRIGGERING REMEDIATION AGENT (DECOUPLED POLL) ==={RESET}")
    print(f"{BOLD}{BLUE}{'#'*72}{RESET}")
    run_remediation_agent()
