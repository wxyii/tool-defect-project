PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: verify-layout verify-contracts verify-monitoring verify-production-security verify-runbooks verify-p5-offline test-core test-edge test-inference \
	test-backend test-web test-integration test-e2e test-faults test-security \
	test-performance verify-data verify-models verify-all \
	check-environment check-environment-source generate-contracts \
	verify-contracts-source verify-v2-scope test-contract-packages-offline verify-compose \
	verify-sbom sbom verify-p1-offline verify-p1-strict verify-p6-01 verify-p6-02 verify-p6-03 verify-p6-04 verify-p6-05 verify-p6-06 verify-p6-07 verify-p6-08 verify-g6 \
	verify-p7-01 verify-p7-02 verify-p7-03 verify-p7-04 verify-p7-05 verify-p7-06 verify-p7-07 verify-g7

verify-layout:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/verify_layout.py

verify-contracts: verify-contracts-source
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/verify_packages.py --languages all

verify-contracts-source:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/verify_contracts.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/compatibility.py --self-test
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/compatibility.py --major 2 --self-test
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/generate.py --check-deterministic
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/verify_packages.py --languages offline

verify-v2-scope:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/verify_v2_scope.py

generate-contracts:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/generate.py

test-contract-packages-offline:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/verify_packages.py --languages offline

test-core:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-core

test-edge:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-edge

test-inference:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-inference

test-backend:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-backend

test-web:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-web

test-integration:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-integration

test-e2e:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-e2e

test-faults:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-faults

test-security:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/security/scan_secrets.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/security/verify_deployment_security.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-security

test-performance:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-performance

verify-data:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py verify-data

verify-models:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py verify-models

verify-p6-01:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/artifact-migrator/verify_p6_01.py

verify-p6-02:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s jobs/dataset-builder/tests -p 'test_*.py'
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/dataset-builder/verify_p6_02.py

verify-p6-03:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/training-pipeline/verify_p6_03.py

verify-p6-04:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/model-evaluator/verify_p6_04.py

verify-p6-05:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/model-evaluator/verify_p6_05.py

verify-p6-06:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/model-evaluator/verify_p6_06.py

verify-p6-07: test-web

verify-p6-08:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/model-evaluator/verify_p6_08.py
	$(MAKE) verify-data verify-models test-integration test-e2e test-security

verify-g6:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) jobs/model-evaluator/verify_g6.py

verify-p7-01:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-01

verify-p7-02:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-02

verify-p7-03:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-03

verify-p7-04:
	$(MAKE) test-faults test-security test-performance
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-04

verify-p7-05:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-05

verify-p7-06:
	$(MAKE) verify-runbooks
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-06

verify-p7-07:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py P7-07

verify-g7:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/p7/verify.py G7

verify-compose:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/verify_compose.py

verify-monitoring:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-monitoring/verify_monitoring.py

verify-production-security:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/security/verify_deployment_security.py

verify-runbooks:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/operations/verify_runbooks.py

verify-p5-offline: verify-monitoring verify-production-security verify-runbooks \
	test-faults test-security test-performance

verify-sbom:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/sbom/generate_sbom.py --check

sbom:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/sbom/generate_sbom.py

check-environment-source:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/check_environment.py source

check-environment:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/check_environment.py strict

verify-p1-offline: check-environment-source verify-layout verify-contracts-source verify-compose test-security verify-sbom

verify-p1-strict: check-environment verify-layout verify-contracts verify-compose test-security verify-sbom
	POSTGRES_PASSWORD=ci-only RABBITMQ_PASSWORD=ci-only MINIO_ROOT_USER=ci-only \
	MINIO_ROOT_PASSWORD=ci-only GRAFANA_ADMIN_USER=ci-only GRAFANA_ADMIN_PASSWORD=ci-only \
	docker compose -f deploy/compose/development.yml config --quiet

verify-all: verify-p1-strict verify-data test-core test-edge test-inference \
	test-backend test-web test-integration test-e2e verify-p5-offline verify-models verify-g7
