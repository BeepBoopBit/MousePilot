# Read-only UI Automation worker. Never invokes controls or reads field values.
param([Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,WindowsBase,UIAutomationClientsideProviders
    # Initialize UIA before registering the standard Win32 control proxies.
    [System.Windows.Automation.AutomationElement]::RootElement | Out-Null
    [System.Windows.Automation.ClientSettings]::RegisterClientSideProviders(
        [UIAutomationClientsideProviders.UIAutomationClientSideProviders]::ClientSideProviderDescriptionTable)
    $r = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Request)) | ConvertFrom-Json
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([long]$r.handle))
    if (-not $root -or $root.Current.ProcessId -ne $r.process_id) { throw 'Root window identity changed' }
    $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    function Read-Control($element) {
        $c = $element.Current
        $b = $c.BoundingRectangle
        if ($c.IsOffscreen -or -not $c.IsEnabled -or $b.IsEmpty -or $b.Width -le 0 -or $b.Height -le 0) { return $null }
        # Some Explorer provider nodes omit ControlType; keep walking their children.
        if (-not $c.ControlType) { return $null }
        $role = $c.ControlType.ProgrammaticName.Replace('ControlType.','')
        if ($role -notin @('Button','CheckBox','RadioButton','Edit','ComboBox','Slider','TabItem','MenuItem','Hyperlink','ListItem','TreeItem','SplitButton')) { return $null }
        $name = [string]$c.Name
        if ($name.Length -gt 200) { $name = $name.Substring(0,200) }
        $id = [string]$c.AutomationId
        if ($id.Length -gt 200) { $id = $id.Substring(0,200) }
        return @{ name=$name; role=$role; automation_id=$id;
            bounds=@([int][Math]::Floor($b.Left),[int][Math]::Floor($b.Top),[int][Math]::Ceiling($b.Right),[int][Math]::Ceiling($b.Bottom));
            _identity=@{runtime_id=@($element.GetRuntimeId()); name=$name; role=$role; automation_id=$id;
                bounds=@([int][Math]::Floor($b.Left),[int][Math]::Floor($b.Top),[int][Math]::Ceiling($b.Right),[int][Math]::Ceiling($b.Bottom))} }
    }
    function Control-AtPoint($point, $reference) {
        # Explorer can expose different provider IDs via tree walking and hit testing.
        # Observe the hit-tested identity now, then require that exact identity at click time.
        $node = [System.Windows.Automation.AutomationElement]::FromPoint(
            [System.Windows.Point]::new($point[0],$point[1]))
        $raw = [System.Windows.Automation.TreeWalker]::RawViewWalker
        $candidate = $null
        for ($depth=0; $node -and $depth -lt 32; $depth++) {
            if ([System.Windows.Automation.Automation]::Compare($node,$root)) { return $candidate }
            if (-not $candidate) {
                $control = Read-Control $node
                if ($control -and $control.name -ceq $reference.name -and
                    $control.role -eq $reference.role -and
                    ($control.bounds -join ',') -eq ($reference.bounds -join ',')) {
                    $candidate = $control
                }
            }
            $node = $raw.GetParent($node)
        }
        # A matching-looking control in another window is not an eligible target.
        return $null
    }
    if ($r.operation -eq 'validate') {
        $match = Control-AtPoint $r.point $r.identity
        if (-not $match -or
            ($match._identity.runtime_id -join ',') -ne ($r.identity.runtime_id -join ',')) {
            throw 'Control is no longer at the target point, is covered, disabled, or unavailable'
        }
        $actual = $match._identity
        if ($actual.name -cne $r.identity.name -or $actual.role -ne $r.identity.role -or
            $actual.automation_id -cne $r.identity.automation_id -or
            ($actual.bounds -join ',') -ne ($r.identity.bounds -join ',')) { throw 'Control changed or moved' }
        @{valid=$true} | ConvertTo-Json -Compress
    } else {
        $queue = [Collections.Generic.Queue[System.Windows.Automation.AutomationElement]]::new()
        $queue.Enqueue($root)
        $rows = [Collections.Generic.List[object]]::new()
        $seen = 0
        $truncated = $false
        while ($queue.Count -gt 0 -and $seen -lt 600 -and $rows.Count -lt $r.limit) {
            $node = $queue.Dequeue()
            $seen++
            try {
                $row = Read-Control $node
                if ($row) {
                    $point = @([int][Math]::Floor(($row.bounds[0]+$row.bounds[2])/2),
                               [int][Math]::Floor(($row.bounds[1]+$row.bounds[3])/2))
                    $canonical = Control-AtPoint $point $row
                    if ($canonical) { $rows.Add($canonical) }
                }
                $child = $walker.GetFirstChild($node)
                while ($child -and $seen+$queue.Count -lt 600) {
                    $queue.Enqueue($child)
                    $child = $walker.GetNextSibling($child)
                }
                if ($child) { $truncated = $true }
            } catch [System.Windows.Automation.ElementNotAvailableException] { }
        }
        @{elements=@($rows.ToArray());truncated=($truncated -or $queue.Count -gt 0)} | ConvertTo-Json -Depth 10 -Compress
    }
} catch {
    # Avoid dumping provider exception text, which may include application data.
    @{error='accessibility_unavailable';message='UI Automation could not inspect or revalidate this control. It may be changed, covered, elevated, or unsupported.'} | ConvertTo-Json -Compress
}
