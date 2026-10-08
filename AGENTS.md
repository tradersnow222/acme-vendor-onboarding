# Agent Guidelines

This document provides guidance for AI agents working on the acme-vendor-onboarding repository.

## Git Workflow

Every change to this repository must follow these strict rules:

### Mandatory Branch and PR Policy

1. **Always work on a new feature branch** — never commit directly to `main`
2. **Open a pull request** for every change, no matter how small
3. **Never merge your own pull request** — Matt reviews and merges all PRs
4. **Never force-push** — preserve commit history and add new commits to address feedback
5. **Never push directly to `main`** — the main branch is protected and requires PR review

### Commit Best Practices

- **Write small, focused commits**: Each commit should represent one logical change
- **Write clear commit messages**: Explain **why** the change was made, not just what changed
  - ✓ Good: "Add field validation to catch missing business owner before routing"
  - ✗ Bad: "Update script"
- **Commit frequently**: Don't accumulate large changes; commit as you complete each piece

### Workflow Summary

```
1. Create feature branch from main
2. Make changes and commit with clear messages
3. Push branch to remote
4. Open pull request with description
5. Wait for Matt's review
6. Address feedback with new commits
7. Matt merges when approved
```

## Repository Purpose

This repository implements a governed vendor onboarding workflow for Acme, Inc.:

- **Intake**: Collect five required fields from requesters
- **Research**: Build research packs from public sources via automated cloud agent
- **Approval routing**: Route to manager (always) and Security (when vendor touches customer data)

The workflow is built with:
- **Grok Bot**: Front door for requesters, status checks, and approval collection
- **Cursor (Grok Build)**: Durable project structure with rules, skills, and scripts
- **Cloud Agents**: Automated research pack generation via Cursor API

## Data Boundaries

- **Public data only**: Website content, trust pages, public pricing, public documentation
- **Synthesized data**: Sample requesters, approvers, and vendors clearly labeled as synthesized
- **No real data**: Never use actual customer data or Acme confidential information

## Approval Policy

- **Manager approval required** for every vendor
- **Security approval required** when vendor will touch customer data
- **Named person only**: Silence never counts as approval
- **Audit trail**: Every approval records who, when, what they saw, and cost

These guidelines ensure consistent, reviewable, and secure development of the vendor onboarding automation.
