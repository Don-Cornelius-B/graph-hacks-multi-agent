from falkordb import FalkorDB

# Connect to local FalkorDB engine on port 6379
db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("infra_ops")

# 1. Reset any previous test nodes
graph.query("MATCH (n) DETACH DELETE n")

# 2. Seed Infrastructure Topology (Track 1 qualifier)
seed_infra = """
CREATE 
  (gw:Service {name: 'api-gateway', status: 'degraded'}),
  (auth:Service {name: 'auth-service', status: 'healthy'}),
  (pay:Service {name: 'payment-service', status: 'failing'}),
  (db_pg:Database {name: 'postgres-primary', status: 'healthy'}),
  (redis_cache:Database {name: 'redis-session', status: 'oom_killed'}),

  (gw)-[:DEPENDS_ON]->(auth),
  (gw)-[:DEPENDS_ON]->(pay),
  (auth)-[:DEPENDS_ON]->(redis_cache),
  (pay)-[:DEPENDS_ON]->(db_pg),
  (pay)-[:DEPENDS_ON]->(redis_cache)
"""
graph.query(seed_infra)

# 3. Seed Incident Memory & Past Runbooks (Track 2 qualifier)
seed_memory = """
CREATE 
  (inc1:Incident {id: 'INC-101', summary: 'Session cache exhaustion', root_cause: 'redis-session OOM'}),
  (rb1:Runbook {id: 'RB-04', action: 'FLUSH_STALE_SESSIONS_AND_RESIZE', target: 'redis-session'}),
  (inc1)-[:RESOLVED_BY]->(rb1)
"""
graph.query(seed_memory)

# 4. Verify count of created nodes
result = graph.query("MATCH (n) RETURN count(n) AS total_nodes")
print(f"Graph initialized successfully. Total nodes in graph: {result.result_set[0][0]}")