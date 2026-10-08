.PHONY: help setup validate research route status audit clean

help:
	@echo "Acme Vendor Onboarding - Available Commands"
	@echo ""
	@echo "  make help       - Show this help message"
	@echo "  make setup      - Set up project (placeholder)"
	@echo "  make validate   - Run intake field validation (coming in PR 4)"
	@echo "  make research   - Generate research pack (coming in PR 5)"
	@echo "  make route      - Run approval routing (coming in PR 6)"
	@echo "  make status     - Generate status report (coming in PR 6)"
	@echo "  make audit      - Show audit log (coming in PR 6)"
	@echo "  make clean      - Remove generated files"
	@echo ""
	@echo "Full workflow will be available after PR 8"

setup:
	@echo "Setup: Creating necessary directories..."
	@mkdir -p packs runs data/samples
	@echo "✓ Project structure ready"
	@echo ""
	@echo "Next: Add sample data and validation scripts in upcoming PRs"

validate:
	@echo "⚠ Intake validation script not yet implemented (coming in PR 4)"

research:
	@echo "⚠ Research pack generation not yet implemented (coming in PR 5)"

route:
	@echo "⚠ Approval routing not yet implemented (coming in PR 6)"

status:
	@echo "⚠ Status report generation not yet implemented (coming in PR 6)"

audit:
	@echo "⚠ Audit log viewing not yet implemented (coming in PR 6)"

clean:
	@echo "Cleaning generated files..."
	@rm -rf packs/* runs/*
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Clean complete"
