"""Execute the actual legacy handler watchdog without importing production services."""

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("modern,expected_timers", [(True, []), (False, [9000])])
def test_legacy_watchdog_defers_to_modern_startup_recovery(modern, expected_timers):
    node = shutil.which("node")
    if not node:
        pytest.skip(
            "Node is required for the script contract; browser CI covers this too"
        )
    module = ast.parse((Path(__file__).parents[1] / "bot" / "miniapp.py").read_text())
    handler = next(
        item
        for item in module.body
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "miniapp_index"
    )
    assignment = next(
        item
        for item in ast.walk(handler)
        if isinstance(item, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "watchdog_script"
            for target in item.targets
        )
    )
    script = (
        ast.literal_eval(assignment.value).split(">", 1)[1].rsplit("</script>", 1)[0]
    )
    harness = """
const vm = require('node:vm');
let input = ''; process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  const {script, modern} = JSON.parse(input); const timers = [];
  const window = {fetch() {}, addEventListener() {}, setTimeout(fn, delay) {timers.push(delay)}};
  if (modern) window.__BANANO_BOOT_RECOVERY__ = {done() {}};
  vm.runInNewContext(script, {window});
  process.stdout.write(JSON.stringify(timers));
});
"""
    result = subprocess.run(
        [node, "-e", harness],
        input=json.dumps({"script": script, "modern": modern}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == expected_timers
