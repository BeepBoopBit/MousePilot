import json
import os
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows PowerShell UI Automation worker")
class WindowsUIAWorkerTests(unittest.TestCase):
    def test_missing_control_type_does_not_abort_discovery(self):
        worker = Path(__file__).resolve().parents[1] / "src/mousepilot/uia.ps1"
        # Load the actual worker function without enumerating the user's desktop.
        script = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:MOUSEPILOT_UIA_WORKER,[ref]$null,[ref]$null)
$fn = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Read-Control'},$true)
Invoke-Expression $fn.Extent.Text
$rect = [pscustomobject]@{IsEmpty=$false;Width=20;Height=10;Left=0;Top=0;Right=20;Bottom=10}
$current = [pscustomobject]@{IsOffscreen=$false;IsEnabled=$true;BoundingRectangle=$rect;ControlType=$null;Name=$null;AutomationId=$null}
$element = [pscustomobject]@{Current=$current}
$element | Add-Member -MemberType ScriptMethod -Name GetRuntimeId -Value { @(42,1) }
$missing = Read-Control $element
$current.ControlType = [pscustomobject]@{ProgrammaticName='ControlType.Button'}
$valid = Read-Control $element
@{missing_skipped=($null -eq $missing);valid=$valid} | ConvertTo-Json -Depth 8 -Compress
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "MOUSEPILOT_UIA_WORKER": str(worker)},
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        data = json.loads(result.stdout)
        self.assertTrue(data["missing_skipped"])
        self.assertEqual(data["valid"]["role"], "Button")
        self.assertEqual(data["valid"]["name"], "")
        self.assertEqual(data["valid"]["bounds"], [0, 0, 20, 10])
