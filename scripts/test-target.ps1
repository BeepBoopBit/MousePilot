$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing @'
using System;
using System.Runtime.InteropServices;
public class MouseWheelProbe : System.Windows.Forms.Panel {
    public int HorizontalWheelEvents { get; private set; }
    public event EventHandler HorizontalWheel;
    protected override void WndProc(ref System.Windows.Forms.Message message) {
        if (message.Msg == 0x020E) {
            HorizontalWheelEvents++;
            if (HorizontalWheel != null) HorizontalWheel(this, EventArgs.Empty);
        }
        base.WndProc(ref message);
    }
}
public static class MouseTestDpi {
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);
}
'@
[void][MouseTestDpi]::SetThreadDpiAwarenessContext([IntPtr](-4))
$script:root = Split-Path $PSScriptRoot -Parent
$script:state = @{ run_id=[guid]::NewGuid().ToString(); mouse_down_events=0; mouse_up_events=0; clicks=0; double_clicks=0; wheel_events=0; drags=0; keys=@(); key_data=@() }
$form = New-Object System.Windows.Forms.Form
$form.Text = 'MousePilot verification target'
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(300,200)
$form.ClientSize = New-Object System.Drawing.Size(600,500)
$form.TopMost = $true
$button = New-Object System.Windows.Forms.Button
$button.Text = 'Click verification'
$button.Location = New-Object System.Drawing.Point(20,20)
$button.Size = New-Object System.Drawing.Size(220,50)
$textBox = New-Object System.Windows.Forms.RichTextBox
$textBox.Location = New-Object System.Drawing.Point(20,90)
$textBox.Size = New-Object System.Drawing.Size(420,35)
$panel = New-Object MouseWheelProbe
$panel.Location = New-Object System.Drawing.Point(20,150)
$panel.Size = New-Object System.Drawing.Size(420,120)
$panel.AutoScroll = $true
$content = New-Object System.Windows.Forms.Label
$content.Text = "Scroll verification`n" + ('Scroll content ' * 200)
$content.Size = New-Object System.Drawing.Size(380,1000)
$panel.Controls.Add($content)
$drag = New-Object System.Windows.Forms.Label
$drag.Text = 'Drag / double click'
$drag.BackColor = [System.Drawing.Color]::LightBlue
$drag.Location = New-Object System.Drawing.Point(20,320)
$drag.Size = New-Object System.Drawing.Size(140,70)
$helper = New-Object System.Windows.Forms.Form
$helper.Text = 'MousePilot focus probe'
$helper.StartPosition = 'Manual'
$helper.Location = New-Object System.Drawing.Point(1000,200)
$helper.Size = New-Object System.Drawing.Size(260,160)
$helper.TopMost = $true
$form.Controls.AddRange(@($button,$textBox,$panel,$drag))
function Save-State {
    $targets = @{}
    foreach ($pair in @(@('button',$button),@('input',$textBox),@('scroll',$panel),@('drag',$drag))) {
        $control = $pair[1]
        $point = $control.PointToScreen((New-Object System.Drawing.Point([int]($control.Width/2),[int]($control.Height/2))))
        $targets[$pair[0]] = @($point.X,$point.Y)
    }
    $horizontalPoint = $panel.PointToScreen((New-Object System.Drawing.Point(($panel.Width-5),[int]($panel.Height/2))))
    $targets['horizontal'] = @($horizontalPoint.X,$horizontalPoint.Y)
    $script:state.horizontal_wheel_events = $panel.HorizontalWheelEvents
    $script:state.left_button_down = ([MouseTestDpi]::GetAsyncKeyState(1) -band 0x8000) -ne 0
    $script:state.right_button_down = ([MouseTestDpi]::GetAsyncKeyState(2) -band 0x8000) -ne 0
    $script:state.middle_button_down = ([MouseTestDpi]::GetAsyncKeyState(4) -band 0x8000) -ne 0
    $script:state.selected_length = $textBox.SelectionLength
    $script:state.text = $textBox.Text
    $script:state.targets = $targets
    $script:state.drag_location = @($drag.Left,$drag.Top)
    $script:state | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 "$script:root\target-state.json"
}
$button.Add_Click({ $script:state.clicks++; $button.Text = "Clicks: $($script:state.clicks)"; Save-State })
$textBox.Add_TextChanged({ Save-State })
$textBox.Add_KeyDown({ param($sender,$event) $script:state.keys += $event.KeyCode.ToString(); $script:state.key_data += $event.KeyData.ToString(); Save-State })
$textBox.Add_KeyUp({ Save-State })
$panel.add_HorizontalWheel({ Save-State })
$panel.Add_MouseWheel({ $script:state.wheel_events++; Save-State })
$content.Add_MouseWheel({ $script:state.wheel_events++; Save-State })
$drag.Add_DoubleClick({ $script:state.double_clicks++; Save-State })
$drag.Add_MouseDown({ param($sender,$event) $script:state.mouse_down_events++; Save-State; $script:offset = $event.Location; $drag.Capture = $true })
$drag.Add_MouseMove({ param($sender,$event)
    if ($event.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $drag.Left += $event.X - $script:offset.X
        $drag.Top += $event.Y - $script:offset.Y
    }
})
$drag.Add_MouseUp({ $script:state.mouse_up_events++; $drag.Capture = $false; $script:state.drags++; Save-State })
$form.Add_LocationChanged({ if ($form.Visible) { Save-State } })
$form.Add_Shown({ Save-State; $helper.Show() })
$telemetryTimer = New-Object System.Windows.Forms.Timer
$telemetryTimer.Interval = 200
$telemetryTimer.Add_Tick({ if ($form.Visible) { Save-State } })
$telemetryTimer.Start()
try { [void]$form.ShowDialog() } finally { $telemetryTimer.Stop(); $telemetryTimer.Dispose(); $helper.Dispose(); $form.Dispose() }
