"""
Agent Ops: FalkorDB Autonomous Incident Triage & Graph Memory Persister
Targeting FalkorDB Graph Hacks Hackathon:
  - Track 1: Connected Data (Blast Radius Analysis across Service Topology)
  - Track 2: Agent Memory & Coordination (Episodic Incident Memory & Runbook Persistence)
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
# MILESTONE 1: Production-Grade FalkorDB Tool Layer
# ----------------------------------------------------------------------

def trace_blast_radius(service_name: str) -> str:
    """Traces all upstream dependent services impacted by a degraded or failing target service or database.
    
    Args:
        service_name: Name of the target service or database (e.g., 'redis-session').
        
    Returns:
        JSON string containing the target service name, list of impacted upstream services, and count.
    """
    graph = get_graph()
    query = (
        "MATCH (target {name: $name})<-[:DEPENDS_ON*1..3]-(impacted) "
        "RETURN target.name AS root, collect(DISTINCT impacted.name) AS impacted"
    )
    result = graph.query(query, {"name": service_name})
    if result.result_set and len(result.result_set) > 0:
        row = result.result_set[0]
        root_name = row[0]
        impacted_list = row[1] if isinstance(row[1], list) else []
        return json.dumps({
            "target": root_name,
            "impacted_services": impacted_list,
            "blast_radius_size": len(impacted_list)
        }, indent=2)
    return json.dumps({
        "target": service_name,
        "impacted_services": [],
        "blast_radius_size": 0
    }, indent=2)


def get_incident_memory(issue_pattern: str) -> str:
    """Searches episodic memory in FalkorDB for past incidents and verified runbooks matching an issue pattern.
    
    Args:
        issue_pattern: Keyword or phrase from the alert or root cause (e.g., 'oom', 'redis-session', 'latency').
        
    Returns:
        Structured JSON string containing matching historical incident records and associated verified runbook actions.
    """
    graph = get_graph()
    query = (
        "MATCH (i:Incident)-[:RESOLVED_BY]->(rb:Runbook) "
        "WHERE toLower(i.root_cause) CONTAINS toLower($pattern) OR toLower(i.summary) CONTAINS toLower($pattern) "
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


def apply_fix_and_remember(incident_id: str, root_cause: str, action_taken: str, target_service: str) -> str:
    """Remediates the target service, updates its status to 'healthy', and records the incident resolution into episodic memory.
    
    Args:
        incident_id: Identifier for the new or existing incident (e.g., 'INC-102').
        root_cause: Identified root cause of the incident.
        action_taken: Remediation action executed (e.g., 'FLUSH_STALE_SESSIONS_AND_RESIZE').
        target_service: Name of the service or database that was recovered.
        
    Returns:
        JSON string confirming transaction outcome, created runbook ID, and updated service status.
    """
    graph = get_graph()
    rb_id = f"RB-AUTO-{incident_id}"
    query = (
        "MERGE (i:Incident {id: $inc_id}) "
        "SET i.root_cause = $root_cause, i.resolved_at = timestamp() "
        "MERGE (rb:Runbook {id: $rb_id, action: $action, target: $target}) "
        "MERGE (i)-[:RESOLVED_BY]->(rb) "
        "WITH rb, i "
        "MATCH (s {name: $target}) "
        "SET s.status = 'healthy' "
        "RETURN i.id, rb.id, s.status"
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
            "incident_id": row[0],
            "runbook_id": row[1],
            "target_service": target_service,
            "target_status": row[2]
        }, indent=2)
    return json.dumps({
        "status": "error",
        "message": f"Failed to execute remediation for '{target_service}' or update graph memory."
    }, indent=2)


# Execution mapping dictionary
TOOL_MAP = {
    "trace_blast_radius": trace_blast_radius,
    "get_incident_memory": get_incident_memory,
    "apply_fix_and_remember": apply_fix_and_remember
}


# ----------------------------------------------------------------------
# MILESTONE 2: Autonomous Multi-Turn Agent Loop
# ----------------------------------------------------------------------

def run_triage_agent(alert_payload: str) -> str:
    """Autonomous agent runner coordinating incident triage using FalkorDB graph tools and Gemini.
    
    Args:
        alert_payload: Alert message describing the incident.
        
    Returns:
        Final resolution summary string.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set GEMINI_API_KEY in your environment or .env file."
        )

    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    client = genai.Client(api_key=api_key)

    system_instruction = (
        "You are an autonomous DevOps & Systems Engineering incident triage agent for FalkorDB.\n"
        "Your task is to triage incoming alerts, investigate impacted services, find matching historical runbooks, "
        "execute the remediation action, and persist resolution memories into the knowledge graph.\n\n"
        "Follow this exact sequence:\n"
        "1. Identify the failing/degraded component from the alert and call `trace_blast_radius` to determine upstream impacted services.\n"
        "2. Call `get_incident_memory` with relevant keywords to locate historical runbooks and previous resolutions.\n"
        "3. Execute the fix and persist resolution memory by calling `apply_fix_and_remember`. Assign a new incident ID (e.g. 'INC-102').\n"
        "4. Output a comprehensive final triage decision with root cause analysis, impacted components, applied runbook, and confirmation of healthy status.\n"
    )

    prompt = f"INCIDENT ALERT:\n{alert_payload}\n\nPlease triage the incident, execute the remediation runbook, and record the solution into episodic memory."

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"{system_instruction}\n\n{prompt}")]
        )
    ]

    config = types.GenerateContentConfig(
        tools=[trace_blast_radius, get_incident_memory, apply_fix_and_remember],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.1
    )

    print(f"\n{BOLD}{CYAN}{'='*72}{RESET}")
    print(f"{BOLD}{CYAN}🚀 STARTING AUTONOMOUS TRIAGE AGENT{RESET}")
    print(f"{BOLD}Model:{RESET} {model_name}")
    print(f"{BOLD}Alert:{RESET} {alert_payload}")
    print(f"{BOLD}{CYAN}{'='*72}{RESET}\n")

    max_turns = 10
    turn = 0

    while turn < max_turns:
        turn += 1
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config
        )

        function_calls = response.function_calls
        if not function_calls:
            # Multi-turn loop complete: final text response generated
            final_text = response.text or "Incident triage completed."
            print(f"\n{BOLD}{MAGENTA}🤖 Final agent triage decision:{RESET}")
            print(f"{MAGENTA}{'='*72}{RESET}")
            print(final_text)
            print(f"{MAGENTA}{'='*72}{RESET}\n")
            return final_text

        # Append model's response to conversation history
        contents.append(response.candidates[0].content)

        # Process each requested function call
        tool_response_parts = []
        for call in function_calls:
            fn_name = call.name
            fn_args = call.args or {}

            print(f"{BOLD}{YELLOW}⚡ Tool invoked:{RESET} {BOLD}{fn_name}{RESET} | args: {json.dumps(fn_args)}")

            if fn_name in TOOL_MAP:
                tool_output_str = TOOL_MAP[fn_name](**fn_args)
            else:
                tool_output_str = json.dumps({"error": f"Unknown tool function: {fn_name}"})

            print(f"{BOLD}{GREEN}📥 Tool response data from FalkorDB:{RESET}\n{tool_output_str}\n")

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

        # Send tool responses back to the conversation
        contents.append(
            types.Content(
                role="user",
                parts=tool_response_parts
            )
        )

    return "Max conversation turns reached without a final response."


if __name__ == "__main__":
    test_alert = (
        "CRITICAL: Database 'redis-session' reported oom_killed. Client latency spiking on api-gateway."
    )
    if len(sys.argv) > 1:
        test_alert = " ".join(sys.argv[1:])

    run_triage_agent(test_alert)
