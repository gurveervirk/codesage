# GitHub Actions Workflows

This directory contains CI/CD workflows for the CodeSage project.

## Workflows

### 1. `tests.yml` - Main Test Suite
**Triggers:**
- Push to any branch
- Pull requests to any branch

**What it does:**
- Tests against Python 3.13.5
- Runs libex tests (fails if missing expected outputs)
- Uploads test results as artifacts

---

### 2. `libex-tests.yml` - LibEx Specific Tests
**Triggers:**
- Push to any branch (only when libex files change)
- Pull requests (only when libex files change)

**Paths watched:**
- `backend/lib_sage/libex/**`
- `backend/tests/libex/**`
- `.github/workflows/libex-tests.yml`

**What it does:**
- Tests against Python 3.13.5
- Checks if expected outputs exist before running tests
- Fails explicitly if no expected outputs found
- Uploads JUnit XML test results

---

## Setup Requirements

### Dependencies
The workflows use `uv` for fast Python package management:
```bash
uv pip install -e . --system
```

Note: Dependencies are defined in the root `pyproject.toml`, not in `backend/`.

### Expected Outputs
For libex tests to run, you need to generate expected outputs:
```bash
cd backend/tests/libex
python prepare_tests.py
```

---

## Viewing Results

### GitHub UI
1. Go to your repository on GitHub
2. Click the "Actions" tab
3. Select a workflow run to see details
4. Download artifacts for detailed test results

### Status Badges
Add to your README.md:
```markdown
![Tests](https://github.com/gurveervirk/CodeSage/actions/workflows/tests.yml/badge.svg)
![LibEx Tests](https://github.com/gurveervirk/CodeSage/actions/workflows/libex-tests.yml/badge.svg)
```

---

## Local Testing

Before pushing, test locally:

```bash
# Run all tests
cd backend/tests
pytest -v

# Run libex tests
cd backend/tests/libex
pytest test_libex_outputs.py -v

# Generate expected outputs
python prepare_tests.py

# Regenerate all (override)
python prepare_tests.py --override
```

---

## Troubleshooting

### Tests failing in CI but passing locally?
- Check that you're using Python 3.13.5
- Ensure all dependencies are in `pyproject.toml`
- Check if expected outputs are committed

### LibEx tests skipped?
- Expected outputs are not committed to the repository
- Generate them locally and commit:
  ```bash
  cd backend/tests/libex
  python prepare_tests.py
  git add expected_outputs/
  git commit -m "Add expected outputs for libex tests"
  ```

### Workflow not triggering?
- Check branch protection rules
- Verify the workflow YAML syntax
- Ensure the paths in `on.push.paths` are correct

---

## Customization

### Add more test jobs
Edit `tests.yml`:
```yaml
- name: Run frontend tests
  run: |
    cd frontend
    npm test
```

### Change Python versions
Edit the workflows to use a different version:
```yaml
- name: Set up Python 3.13.5
  uses: actions/setup-python@v5
  with:
    python-version: '3.13.5'
```

### Run on specific branches only
Change the trigger:
```yaml
on:
  push:
    branches:
      - main
      - develop
```

---

## Best Practices

1. **Always run tests locally first** before pushing
2. **Commit expected outputs** for deterministic libex tests
3. **Review test artifacts** when tests fail in CI
4. **Keep workflows fast** by caching dependencies (already enabled with `uv`)
5. **Use matrix testing** for Python version compatibility

---

## Support

For issues with workflows:
1. Check the Actions tab for error details
2. Review workflow logs
3. Test locally with the same Python version
4. Check if dependencies need updating
