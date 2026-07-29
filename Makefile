PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: verify-layout verify-contracts test-core test-edge test-inference \
	test-backend test-web test-integration test-e2e test-faults test-security \
	test-performance verify-data verify-models verify-all \
	check-environment check-environment-source generate-contracts \
	verify-contracts-source test-contract-packages-offline verify-compose \
	verify-sbom sbom verify-p1-offline verify-p1-strict

verify-layout:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/verify_layout.py

verify-contracts: verify-contracts-source
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/verify_packages.py --languages all

verify-contracts-source:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/verify_contracts.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-contracts/compatibility.py --self-test
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/generate.py --check-deterministic
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/generate-contracts/verify_packages.py --languages offline

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

test-performance:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py test-performance

verify-data:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py verify-data

verify-models:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/run_target.py verify-models

verify-compose:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tools/verify-layout/verify_compose.py

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

verify-all: check-environment verify-layout verify-contracts test-core test-edge \
	test-inference test-backend test-web test-integration test-e2e test-faults \
	test-security test-performance verify-data verify-models verify-compose verify-sbom
