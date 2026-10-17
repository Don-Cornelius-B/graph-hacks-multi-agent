"""
Verify Memory: Automated verification script for FalkorDB decoupled multi-agent triage
Targeting Milestone 3:
  - Asserts target service 'redis-session' status is 'healthy'
  - Asserts stateful :Handoff ticket lifecycle (status == 'RESOLVED' and [:TARGETS]->target)
  - Asserts episodic memory persistence (baseline INC-101 and new auto-remediated Incident-[:RESOLVED_BY]->Runbook)
  - Prints clear ASCII / formatted tabular views of Handoffs, Graph Memory, and Topology
"""

import os
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from falkordb import FalkorDB

# Try importing tabulate for clean tables, fallback to custom ASCII formatter
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Load environment
load_dotenv()


def format_table(headers, rows):
    """Formats tabular data using tabulate or fallback ASCII box drawing."""
    if HAS_TABULATE:
        return tabulate(rows, headers=headers, tablefmt="fancy_grid")
    
    # Custom ASCII fallback
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            val_str = str(val)[:60]  # truncate long strings for terminal
            col_widths[i] = max(col_widths[i], len(val_str))
            
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "|" + "|".join(f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))) + "|"
    
    lines = [sep, header_line, sep]
    for row in rows:
        row_line = "|" + "|".join(f" {str(row[i])[:60].ljust(col_widths[i])} " for i in range(len(row))) + "|"
        lines.append(row_line)
    lines.append(sep)
    return "\n".join(lines)


def run_verification(target_service="redis-session") -> bool:
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", 6379))
    graph_name = os.environ.get("FALKORDB_GRAPH", "infra_ops")

    db = FalkorDB(host=host, port=port)
    graph = db.select_graph(graph_name)

    print(f"\n{BOLD}{CYAN}{'='*75}{RESET}")
    print(f"{BOLD}{CYAN}🔍 FALKORDB MULTI-AGENT STATE & MEMORY VERIFICATION{RESET}")
    print(f"{BOLD}Graph:{RESET} {graph_name} on {host}:{port}")
    print(f"{BOLD}Target Component:{RESET} {target_service}")
    print(f"{BOLD}{CYAN}{'='*75}{RESET}\n")

    assertions_passed = True

    # ------------------------------------------------------------------
    # 1. Health Status Assertion
    # ------------------------------------------------------------------
    print(f"{BOLD}1. Verifying Service Health Status...{RESET}")
    svc_query = "MATCH (s {name: $name}) RETURN s.name AS name, s.status AS status, labels(s) AS labels"
    svc_res = graph.query(svc_query, {"name": target_service})

    if not svc_res.result_set or len(svc_res.result_set) == 0:
        print(f"  {RED}❌ Target entity '{target_service}' not found in graph!{RESET}")
        assertions_passed = False
    else:
        name, status, labels = svc_res.result_set[0]
        label_str = labels[0] if labels else "Node"
        if status == "healthy":
            print(f"  {GREEN}✅ Target '{name}' ({label_str}) status is 'healthy'!{RESET}")
        else:
            print(f"  {RED}❌ Target '{name}' ({label_str}) status is '{status}' (expected 'healthy')!{RESET}")
            assertions_passed = False

    # ------------------------------------------------------------------
    # 2. Handoff Coordination Assertion
    # ------------------------------------------------------------------
    print(f"\n{BOLD}2. Verifying Stateful Handoff Ticket Lifecycle...{RESET}")
    handoff_query = (
        "MATCH (h:Handoff)-[r:TARGETS]->(s) "
        "RETURN h.id AS handoff_id, h.status AS status, coalesce(h.diagnosis, 'N/A') AS diagnosis, s.name AS target "
        "ORDER BY h.created_at ASC"
    )
    handoff_res = graph.query(handoff_query)
    handoff_rows = handoff_res.result_set if handoff_res.result_set else []

    has_resolved_handoff = any(
        row[1] == "RESOLVED" and row[3] == target_service
        for row in handoff_rows
    )

    if has_resolved_handoff:
        print(f"  {GREEN}✅ Verified active handoff ticket resolved state ('RESOLVED') targeting '{target_service}'!{RESET}")
    else:
        print(f"  {RED}❌ No resolved handoff ticket found for '{target_service}'!{RESET}")
        assertions_passed = False

    # ------------------------------------------------------------------
    # 3. Episodic Memory Persistence Assertion
    # ------------------------------------------------------------------
    print(f"\n{BOLD}3. Verifying Episodic Incident Memory & Runbooks...{RESET}")
    memory_query = (
        "MATCH (i:Incident)-[r:RESOLVED_BY]->(rb:Runbook) "
        "RETURN i.id AS incident_id, coalesce(i.root_cause, i.summary, 'N/A') AS root_cause, "
        "type(r) AS rel, rb.id AS runbook_id, rb.action AS action, coalesce(rb.target, 'N/A') AS target"
    )
    mem_res = graph.query(memory_query)
    mem_rows = mem_res.result_set if mem_res.result_set else []

    has_baseline = any(row[0] == "INC-101" for row in mem_rows)
    has_new_incident = any(
        (str(row[3]).startswith("RB-AUTO-") or row[0] != "INC-101") and row[5] == target_service
        for row in mem_rows
    )

    if has_baseline and has_new_incident:
        print(f"  {GREEN}✅ Both baseline seed (INC-101) and new remediated incident verified with :RESOLVED_BY edges!{RESET}")
    elif not has_baseline:
        print(f"  {RED}❌ Baseline incident INC-101 missing from graph memory!{RESET}")
        assertions_passed = False
    else:
        print(f"  {RED}❌ Newly persisted incident memory for '{target_service}' missing!{RESET}")
        assertions_passed = False

    # ------------------------------------------------------------------
    # 4. Tabular ASCII Visualizations
    # ------------------------------------------------------------------
    print(f"\n{BOLD}{CYAN}📋 TABLE 1: HANDOFF TICKET LIFECYCLE (:Handoff -[:TARGETS]-> :Service|Database):{RESET}")
    handoff_headers = ["Handoff ID", "Status", "Target Component", "Diagnosis Summary"]
    formatted_handoffs = [
        [row[0], row[1], row[3], (row[2][:65] + "...") if len(row[2]) > 65 else row[2]]
        for row in handoff_rows
    ]
    print(format_table(handoff_headers, formatted_handoffs))

    print(f"\n{BOLD}{CYAN}📊 TABLE 2: GRAPH MEMORY EDGES (:Incident -[:RESOLVED_BY]-> :Runbook):{RESET}")
    mem_headers = ["Incident ID", "Root Cause / Summary", "Relationship", "Runbook ID", "Action Taken", "Target"]
    formatted_mems = [
        [row[0], (row[1][:50] + "...") if len(row[1]) > 50 else row[1], row[2], row[3], row[4], row[5]]
        for row in mem_rows
    ]
    print(format_table(mem_headers, formatted_mems))

    print(f"\n{BOLD}{CYAN}🌐 TABLE 3: LIVE SERVICE TOPOLOGY STATUS:{RESET}")
    topo_query = (
        "MATCH (n) WHERE 'Service' IN labels(n) OR 'Database' IN labels(n) "
        "RETURN n.name AS name, labels(n)[0] AS type, n.status AS status "
        "ORDER BY n.name"
    )
    topo_res = graph.query(topo_query)
    topo_rows = topo_res.result_set if topo_res.result_set else []
    topo_headers = ["Entity Name", "Type", "Current Status"]
    print(format_table(topo_headers, topo_rows))

    # ------------------------------------------------------------------
    # Final Verdict
    # ------------------------------------------------------------------
    print(f"\n{BOLD}{'='*75}{RESET}")
    if assertions_passed:
        print(f"{BOLD}{GREEN}🎉 ALL FALKORDB MULTI-AGENT ASSERTIONS PASSED!{RESET}")
    else:
        print(f"{BOLD}{RED}❌ VERIFICATION FAILED: One or more assertions did not pass.{RESET}")
    print(f"{BOLD}{'='*75}{RESET}\n")

    return assertions_passed


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "redis-session"
    success = run_verification(target)
    sys.exit(0 if success else 1)
