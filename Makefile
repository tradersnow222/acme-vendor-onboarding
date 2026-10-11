.PHONY: help setup validate research route status audit clean test run

help:
	@echo "Acme Vendor Onboarding - Available Commands"
	@echo ""
	@echo "  make help       - Show this help message"
	@echo "  make setup      - Set up project structure"
	@echo "  make validate SAMPLE=<zendesk|figma|asana> - Check the five intake fields"
	@echo "  make research TICKET=<id> - Dry run of the research agent launch"
	@echo "  make route SAMPLE=<zendesk|figma|asana>    - Show who must approve"
	@echo "  make status TICKET=<id>   - Show request status"
	@echo "  make audit TICKET=<id>    - Print runs/<id>/audit.csv"
	@echo "  make clean      - Remove generated files"
	@echo "  make run SAMPLE=<zendesk|figma|asana> - Trace one sample through every step"
	@echo ""
	@echo "Approval commands (no make target; add --help for options):"
	@echo "  python3 -m scripts.request_approvals --ticket <id> - Ask each approver on the route"
	@echo "  python3 -m scripts.record_approval --ticket <id> --role <role> --name <name> --decision <decision> --quote <words>"
	@echo "      - Record a decision a named person already gave in their own words"
	@echo "  python3 -m scripts.ticket --close <id> - Close out a decided request"
	@echo "  python3 -m scripts.stale_check [--record] - List approvals due a nudge"
	@echo "  python3 -m scripts.digest - Print the daily Ops digest"

setup:
	@echo "Setup: Creating necessary directories..."
	@mkdir -p packs runs data/samples
	@echo "✓ Project structure ready"

validate:
	@test -n "$(SAMPLE)" || { echo "usage: make validate SAMPLE=<zendesk|figma|asana>   e.g. make validate SAMPLE=zendesk" >&2; exit 2; }
	@python3 -m scripts.intake_check $(SAMPLE)

research:
	@test -n "$(TICKET)" || { echo "usage: make research TICKET=<id>   e.g. make research TICKET=VR-0001" >&2; exit 2; }
	@python3 -m scripts.launch_research --ticket $(TICKET)

route:
	@test -n "$(SAMPLE)" || { echo "usage: make route SAMPLE=<zendesk|figma|asana>   e.g. make route SAMPLE=zendesk" >&2; exit 2; }
	@python3 -m scripts.route $(SAMPLE)

status:
	@test -n "$(TICKET)" || { echo "usage: make status TICKET=<id>   e.g. make status TICKET=VR-0001" >&2; exit 2; }
	@python3 -m scripts.status --ticket $(TICKET)

audit:
	@test -n "$(TICKET)" || { echo "usage: make audit TICKET=<id>   e.g. make audit TICKET=VR-0001" >&2; exit 2; }
	@cat runs/$(TICKET)/audit.csv

clean:
	@echo "Cleaning generated files..."
	@rm -rf packs/* runs/*
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Clean complete"

test:
	cd "$(dir $(abspath $(firstword $(MAKEFILE_LIST))))" && python3 -m unittest discover -s tests -v

run:
	@python3 -m scripts.run $(SAMPLE)
