# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
- Temporality (first seen, last seen)
- Auto-seed (no need to pass in --seeds, seed from inventory)
- Support multiple k8s clusters in same discovery run
- Support multiple AWS accounts
- Mutable node types.  Create nodes first as Unknown - mutate to specific types upon inventory.

## [0.1.0] - 2025-05-15 - Multi-cluster, Model Refactor, plus more
### Added
- Support discovery on multiple k8s clusters (only during separate discovery run/configurations) #13
- Reverse IP lookup for internet (public_ip) nodes #12

### Changed
- AWS: Prefer private ipaddrs for node.address #9
- Reduced required python version `3.10` -> `3.9` 7d58d3
- Support multiple k8s namespaces in the same cluster #6
- Integrated separate `platdb` module into `astrolabe` core 2d413a
- Support multiple IP Addresses per node #5
- Differentiate `node_name` and `service_name` #4
- Refactored neomodel model relationships #3

## [0.0.1 Milestone 2] - 2024-11-13 Neo4J Rewrite
SHA `652003c756a00a7ae104e43a9901c81a9022c29e`
- FEATURE: Integrate Neo4J as primary datastore, remove exporter
- FEATURE: Mermaid exporter
- BUG: Fixed seed config parsing

## [0.0.1 Milestone 1] - 2024-10-30 Inventory and Neo4J Exporter
SHA `9631dadc5e2363755775904cf7d76cf8b12987f3`
- FEATURE: AWS - inventory load balancers, databases, caches
- FEATURE: k8s - inventory services
- FEATURE: Neo4J Exporter
- FEATURE: Idempotent discovery runs
- REFACTOR: Major refactors from itsy-bitsy, prepare for Neo4J rewrite

## [0.0.1 Milestone 0] - 2024-06-15 Initial
- Initial port from itsy-bitsy
