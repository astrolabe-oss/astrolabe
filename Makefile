test:
	@pytest

coverage:
	@pytest --cov --cov-fail-under=70 --cov-config .coveragerc

analyze:
	@prospector --profile .prospector.yaml