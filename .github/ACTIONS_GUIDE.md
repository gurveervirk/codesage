# GitHub Actions Quick Start

## What You Get

✅ **Automatic testing** on every push to any branch  
✅ **Multi-version testing** (Python 3.9-3.13)  
✅ **PR validation** before merging  
✅ **Smart libex testing** (only when files change)  
✅ **Test result artifacts** (downloadable)  

---

## First Time Setup

1. **Commit the workflow files:**
   ```bash
   git add .github/workflows/
   git commit -m "Add GitHub Actions workflows"
   git push
   ```

2. **Generate expected outputs for libex tests:**
   ```bash
   cd backend/tests/libex
   python prepare_tests.py
   git add expected_outputs/
   git commit -m "Add expected outputs for libex tests"
   git push
   ```

3. **Check Actions tab:**
   - Go to https://github.com/gurveervirk/CodeSage/actions
   - You should see your workflows running!

---

## Adding Status Badges

Add these to your main README.md:

```markdown
![Tests](https://github.com/gurveervirk/CodeSage/actions/workflows/tests.yml/badge.svg)
![LibEx Tests](https://github.com/gurveervirk/CodeSage/actions/workflows/libex-tests.yml/badge.svg)
![PR Checks](https://github.com/gurveervirk/CodeSage/actions/workflows/pr-checks.yml/badge.svg)
```

They'll show: ![Tests](https://img.shields.io/badge/tests-passing-brightgreen)

---

## Workflow Triggers

| Workflow | Triggers | When |
|----------|----------|------|
| `tests.yml` | All pushes, All PRs | Always |
| `libex-tests.yml` | Pushes/PRs affecting libex files | When libex code changes |
| `pr-checks.yml` | PRs to main/develop | Before merging |

---

## Local Testing (Before Push)

```bash
# Test libex
cd backend/tests/libex
pytest test_libex_outputs.py -v

# Regenerate expected outputs if needed
python prepare_tests.py --override
```

---

## Viewing Test Results

### In GitHub:
1. Click **Actions** tab
2. Select a workflow run
3. Click on a job to see logs
4. Download artifacts for detailed reports

### Status:
- ✅ Green checkmark = All tests passed
- ❌ Red X = Tests failed
- 🟡 Yellow dot = Running
- ⊘ Gray = Skipped

---

## Common Issues

### "Tests failing in CI but pass locally"
**Solution:** Check Python version
```bash
# Test with specific Python version
python3.11 -m pytest -v
```

### "LibEx tests skipped"
**Solution:** Generate and commit expected outputs
```bash
cd backend/tests/libex
python prepare_tests.py
git add expected_outputs/
git commit -m "Add expected outputs"
git push
```

### "Workflow not running"
**Solution:** Check:
- Workflow files are in `.github/workflows/`
- YAML syntax is valid
- Branch matches trigger conditions

---

## Customization

### Test only on main branch:
```yaml
on:
  push:
    branches:
      - main
```

### Add Slack notifications:
```yaml
- name: Slack notification
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

### Add email notifications:
GitHub sends emails automatically for failed workflows on your branches.

---

## Best Practices

1. ✅ **Always test locally first**
2. ✅ **Commit expected outputs** for libex tests
3. ✅ **Review failed workflow logs** before re-running
4. ✅ **Keep dependencies updated** in pyproject.toml
5. ✅ **Use descriptive commit messages** so you know what triggered failures

---

## Need Help?

- 📖 [GitHub Actions Docs](https://docs.github.com/en/actions)
- 🔍 Check workflow logs in Actions tab
- 💬 Ask in your PR comments
- 🐛 File an issue if workflows are broken
