.PHONY: help setup validate research route status audit clean test

help:
	@echo "Acme Vendor Onboarding - Available Commands"
	@echo ""
	@echo "  make help       - Show this help message"
	@echo "  make setup      - Set up project (placeholder)"
	@echo "  make validate   - Run intake field validation"
	@echo "  make research   - Generate research pack"
	@echo "  make route      - Run approval routing"
	@echo "  make status     - Generate status report"
	@echo "  make audit      - Show audit log"
	@echo "  make clean      - Remove generated files"

setup:
	@echo "Setup: Creating necessary directories..."
	@mkdir -p packs runs data/samples
	@echo "✓ Project structure ready"

validate:
	@echo "⚠ Intake validation script not built yet"

research:
	@echo "⚠ Research pack generation not built yet"

route:
	@echo "⚠ Approval routing not built yet"

status:
	@echo "⚠ Status report generation not built yet"

audit:
	@echo "⚠ Audit log viewing not built yet"

clean:
	@echo "Cleaning generated files..."
	@rm -rf packs/* runs/*
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Clean complete"

test:
	python3 -m unittest discover -s tests -v
