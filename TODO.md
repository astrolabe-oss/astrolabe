### ACTIVE
* [~] FEATURE - export mermaid

### OSS RELEASE FOLLOW UPS
* [ ] code
  * [ ] astrolabe CI/CD move to github
  * [ ] corelib/platdb CI/CD move to github
* [ ] oss
  * [ ] demo video for README
  * [ ] rename astrolabe-oss/corelib repo to platdb?
  * [ ] pynapple repo filter and port over to example repo
  * [ ] example app - terraform repo
  * [ ] move cartographer to private repo
  * [ ] credit image: https://commons.wikimedia.org/wiki/File:Astrolabe.png

### BUGS
* [ ] `cli_args.py`: configargparse doesn't let parse lists in config file!  prevents us from putting seeds in config files
* [ ] cannot save nodes with no address or alias (used to be able to save nodes with protocol_mux only, this died during the neo4j refactor)

### FEATURES/IMPROVEMENTS
* [ ] UNKNOWN platdb node type!
* [ ] Rename discover/profile?
  * [ ] rename ProfileStrategy -> RemoteDiscoveryScript
* [ ] should "address" be the DNS name for a load balancer?
* [ ] should application be a "tag" not a Node?
* [ ] ProfileStrategies
  * [ ] a queuing system
 * [ ] ProfileStrategy::childProviders: rewrite provider lookup to be a shotgun approach instead of configured?


### REFACTORS/TESTS
* [ ] `node.py`: remove Node.children field (should be unused logically - cruft remains mainly in tests)
* [ ] `database.py`: neo4j vars should be looked up in ENV vars as well.  (Can we do this by convention for all args?)
* [ ] `discover.py`: tests for idempotency runs
* [ ] `database.py`: get rid of database.node_is* funcs, these shouldn't require a database call
* [ ] `node.py`: Node.profile_stategy_name is just for logging/audit, move to somethign like -> Node.discovery_audit
* [ ] `node.py`: move discover.create_node() -> node.create_node()
* [ ] `database.py`: need tests for logic/transforms, etc

### Documentation:
* [ ] Profile Strategies - examples
* [ ] Writing Custom Plugins/Providers - example
* [ ] Env Vars




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

