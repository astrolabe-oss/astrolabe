DOCKER_COMPOSE=docker-compose \
	-f tests_integration/neo4j_ephemeral_db/docker-compose.yml

test:
	@pytest tests

coverage:
	@pytest --cov --cov-fail-under=75 --cov-config .coveragerc

lint:
	@prospector --profile .prospector.yaml $(filter-out $@,$(MAKECMDGOALS))

integration_up:
	@echo "Starting Neo4j container..."
	$(DOCKER_COMPOSE) up -d

integration_down:
	@echo "Stopping Neo4j container..."
	$(DOCKER_COMPOSE) down

integration_test:
	@if [ -z "$$($(DOCKER_COMPOSE) ps -q neo4j)" ]; then \
		echo "Neo4j container is not running..."; \
		echo "Turn it on with 'make test_env_up'"; \
		exit 1; \
	fi; \

	@echo "Running tests..."
	@pytest tests_integration
