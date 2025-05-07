### CURRENT
* [ ] include ipaddress array field in the platdb database

### OSS RELEASE FOLLOW UPS
* [x] rename astrolabe-oss/corelib repo to platdb?
* [x] pynapple repo filter and port over to example repo
* [x] example app - terraform repo
* [ ] demo video for README
* [ ] credit image: https://commons.wikimedia.org/wiki/File:Astrolabe.png

### BUGS
* [x] `cli_args.py`: configargparse doesn't let parse lists in config file! (NOV 2024)
* [ ] cannot save nodes with no address or alias (used to be able to save nodes with protocol_mux only, this died during the neo4j refactor)

### RETHINK
* [ ] Rethink:  ProfileStrategy: RemoteProfile vs LocalProfile?
* [ ] Rethink:  address/name.  For example, should "address" be the DNS name for a load balancer?  What is address exactly?
* [ ] Rethink: hould application be a "tag" not a Node?
* [ ] Rethink: Unknown/Null node types.
* [ ] Rethink: provider determination - shotgun lookup instead of configured?
* [ ] Rethink: export, json.  Entire graph vs seed?  Seed for export?  Last run?
* [ ] Rethink: NodeTransport.  Do we even need it anymore?

### FEATURES/IMPROVEMENTS
* [x] FEATURE - export mermaid (NOV 2024)
* [ ] k8s - add k8s_cluster as a node_attribute
* [ ] Seed auto discovery based on inventory 
* [ ] `database.py`: neo4j vars should be looked up in ENV vars as well.  (Can we do this by convention for all args?)
* [ ] `discover.py`: is it idempotent right now?
* [ ] `database.py`: get rid of database.node_is* funcs, these shouldn't require a database call

### CRUFT
* [ ] `node.py`: remove Node.children field (should be unused logically - cruft remains mainly in tests)
* [ ] `node.py`: Node.profile_stategy_name is just for logging/audit, move to somethign like -> Node.discovery_audit
* [ ] `node.py`: move discover.create_node() -> node.create_node()
* [ ] `database.py`: need tests for logic/transforms, etc

### BIG ONE: TEMPORALNESS
* [ ] `temporalness` - introduce the concept of time/when to solve for changing infra

### BIG ONE: DEFENSIVENESS
* [ ] `defensiveness` - mux not expected from profile results
* [ ] `definsiveness` - how do we handle ALL exceptions in discovery/profiling?  Throw non-exiting exception & log?

### Documentation:
* [ ] Profile Strategies - examples
* [ ] Writing Custom Plugins/Providers - example
* [ ] Env Vars
* [ ] Install doc

### FOR OSS RELEASE (NOV 2024)
* [x] code
  * [x] `discover.py`: idempotent `discover` subsequent runs
  * [x] `exporter_ascii.py`: get ascii exporter working
  * [x] `exporter_graphviz.py`: get export graphviz working
* [x] OSS
  * [x] update license
  * [x] createe astrolabe github org
  * [x] create astrolabe fiter-repo and ported over
  * [x] corelib filter-repo and ported or over

### NEO4J INTEGRATION (OCT 2024)
* [x] ASG->Deployments not attached
* [x] unit tests for astrolabe error out if NEO4J_* env vars are not set

### PROFILE STRATEGY REWRITE (OCT 2024)
* [x] get rid of HintProfileStrategy!
* [x] move service name rewrites to network!
* [x] profile(.., pfs, ...) -> profile(.., pfs[], ...)
* [x] rename profile_strategy_used_name -> profile_strategy_name

### DESIGN PHILOSOPHY
* Convention over Configuration
* Defensive Programming (log and proceed)
* Allow incomplet
