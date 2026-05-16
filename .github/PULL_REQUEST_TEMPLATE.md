## Summary

<!-- What does this change do, and why? -->

## Related

<!-- Link issues or ADRs. For an architectural change, link or add the ADR. -->

## Checklist

- [ ] Title and commits follow Conventional Commits
- [ ] One logical change; the PR is small and reviewable
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes; new behavior is covered by tests
- [ ] Public APIs have type hints and docstrings
- [ ] No secrets or customer data committed
- [ ] Change respects the scope anchors (CLAUDE.md section 1.3)
- [ ] Docs, CHANGELOG, and ADRs updated as needed
