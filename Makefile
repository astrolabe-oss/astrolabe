test:
	@pytest

coverage:
	@pytest --cov --cov-fail-under=70 --cov-config ../.coveragerc

lint:
	@prospector --profile .prospector.yaml $(filter-out $@,$(MAKECMDGOALS))
