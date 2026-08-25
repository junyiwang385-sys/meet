# Extraction troubleshooting

## Import failures

Use the source layout explicitly:

```text
PYTHONPATH=src python -m meeting_agent.harness.main --help
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m meeting_agent.harness.main --help
```

## Compatibility paths

If a board deployment still expects `python -m harness.main`, use the original `board_sync_20260820/scripts` snapshot. The new package is not automatically deployed to RK1828.
