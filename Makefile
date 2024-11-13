test:
	@pytest

coverage:
	@pytest --cov --cov-fail-under=75 --cov-config .coveragerc

lint:
	@prospector --profile .prospector.yaml $(filter-out $@,$(MAKECMDGOALS))
