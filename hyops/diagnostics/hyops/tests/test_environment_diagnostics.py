#From the repository root:

python3 -m unittest hyops.tests.test_environment_diagnostics

#Run the complete Python test suite:

python3 -m unittest discover

#Run the repository's Python quality checks recommended by CONTRIBUTING.md:

bash tools/ci/check-python.sh
bash tools/ci/check-ruff.sh

#If pytest is installed in the development environment, the new tests can also be collected and executed with:

pytest hyops/tests/test_environment_diagnostics.py

#Expected result:

#5 tests passed
