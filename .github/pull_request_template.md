## Summary

Describe the user-visible problem and the change that solves it.

## Validation

- [ ] `python -m unittest discover -s scripts -p "test_*.py"`
- [ ] Collector Markdown and JSON smoke tests
- [ ] Snapshot comparison smoke test
- [ ] Skill metadata validation, when available

## Safety and compatibility

- [ ] The change remains read-only by default.
- [ ] Sensitive-looking file contents are never read or printed.
- [ ] User-facing behavior and compatibility impact are documented.
