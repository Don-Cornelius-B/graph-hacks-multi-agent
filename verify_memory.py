"""
Verify Memory: Automated verification script for FalkorDB incident triage
Targeting Milestone 3:
  - Asserts target service 'redis-session' status is 'healthy'
  - Asserts new :Incident and :Runbook nodes exist and are linked via :RESOLVED_BY
  - Prints clear ASCII/tabular view of all graph memory edges and topology nodes
"""

import os
import sys
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
            col_widths[i] = max(col_widths[i], len(str(val)))
            
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "|" + "|".join(f" {headers[i].ljust(col_widths[i])} " for i in range(len(headers))) + "|"
    
    lines = [sep, header_line, sep]
    for row in rows:
        row_line = "|" + "|".join(f" {str(row[i]).ljust(col_widths[i])} " for i in range(len(row))) + "|"
        lines.append(row_line)
    lines.append(sep)
    return "\n".join(lines)


def run_verification(target_service="redis-session") -> bool:
    host = os.environ.get("FALKORDB_HOST", "localhost")
    port = int(os.environ.get("FALKORDB_PORT", 6379))
    graph_name = os.environ.get("FALKORDB_GRAPH", "infra_ops")

    db = FalkorDB(host=host, port=port)
    graph = db.select_graph(graph_name)

    print(f"\n{BOLD}{CYAN}{'='*72}{RESET}")
    print(f"{BOLD}{CYAN}🔍 FALKORDB GRAPH MEMORY & TOPOLOGY VERIFICATION{RESET}")
    print(f"{BOLD}Graph:{RESET} {graph_name} on {host}:{port}")
    print(f"{BOLD}{CYAN}{'='*72}{RESET}\n")

    assertions_passed = True

    # 1. Assert Target Service Status
    print(f"{BOLD}1. Verifying Service Health Status...{RESET}")
    svc_query = "MATCH (s {name: $name}) RETURN s.name AS name, s.status AS status, labels(s) AS labels"
    svc_res = graph.query(svc_query, {"name": target_service})

    if not svc_res.result_set or len(svc_res.result_set) == 0:
        print(f"  {RED}❌ Target entity '{target_service}' not found in graph!{RESET}")
        assertions_passed = False
    else:
        name, status, labels = svc_res.result_set[0]
        if status == "healthy":
            print(f"  {GREEN}✅ Target '{name}' ({labels[0] if labels else 'Node'}) status is 'healthy'!{RESET}")
        else:
            print(f"  {RED}❌ Target '{name}' status is '{status}' (expected 'healthy')!{RESET}")
            assertions_passed = False

    # 2. Query and Assert Episodic Memory Nodes & Edges
    print(f"\n{BOLD}2. Verifying Episodic Incident Memory & Runbooks...{RESET}")
    memory_query = (
        "MATCH (i:Incident)-[r:RESOLVED_BY]->(rb:Runbook) "
        "RETURN i.id AS incident_id, coalesce(i.root_cause, i.summary, 'N/A') AS root_cause, "
        "type(r) AS rel, rb.id AS runbook_id, rb.action AS action, coalesce(rb.target, 'N/A') AS target"
    )
    mem_res = graph.query(memory_query)

    mem_rows = mem_res.result_set if mem_res.result_set else []

    # Check if a newly generated incident or runbook exists
    has_auto_runbook = any(
        (str(row[3]).startswith("RB-AUTO-") or row[0] != "INC-101") and row[5] == target_service
        for row in mem_rows
    )

    if has_auto_runbook:
        print(f"  {GREEN}✅ New auto-remediated Incident and Runbook nodes verified with :RESOLVED_BY relationship!{RESET}")
    else:
        print(f"  {RED}❌ No newly created Incident/Runbook memory found for '{target_service}'!{RESET}")
        assertions_passed = False

    # 3. Print Tabular View of Graph Memory Edges
    print(f"\n{BOLD}{CYAN}📊 GRAPH MEMORY EDGES (:Incident -[:RESOLVED_BY]-> :Runbook):{RESET}")
    mem_headers = ["Incident ID", "Root Cause / Summary", "Relationship", "Runbook ID", "Action Taken", "Target"]
    print(format_table(mem_headers, mem_rows))

    # 4. Print Tabular View of Infrastructure Topology
    print(f"\n{BOLD}{CYAN}🌐 INFRASTRUCTURE TOPOLOGY STATUS:{RESET}")
    topo_query = (
        "MATCH (n) WHERE 'Service' IN labels(n) OR 'Database' IN labels(n) "
        "RETURN n.name AS name, labels(n)[0] AS type, n.status AS status "
        "ORDER BY n.name"
    )
    topo_res = graph.query(topo_query)
    topo_rows = topo_res.result_set if topo_res.result_set else []
    topo_headers = ["Entity Name", "Type", "Current Status"]
    print(format_table(topo_headers, topo_rows))

    # Final Verdict
    print(f"\n{BOLD}{'='*72}{RESET}")
    if assertions_passed:
        print(f"{BOLD}{GREEN}🎉 ALL FALKORDB MEMORY & TOPOLOGY ASSERTIONS PASSED!{RESET}")
    else:
        print(f"{BOLD}{RED}❌ VERIFICATION FAILED: One or more assertions did not pass.{RESET}")
    print(f"{BOLD}{'='*72}{RESET}\n")

    return assertions_passed


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "redis-session"
    success = run_verification(target)
    sys.exit(0 if success else 1)
