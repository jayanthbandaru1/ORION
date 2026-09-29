# Queries Windows' own native Geolocation API (WinRT) directly and
# prints the result as one line of JSON. Exists because Chromium's
# navigator.geolocation inside Electron fails outright ("Failed to query
# location from network service") - the open-source Electron build has
# no Google geolocation API key compiled in, so its network-based lookup
# never works, regardless of app-level permission handling. Windows'
# own location service doesn't need that key at all, so this bypasses
# Chromium's geolocation implementation entirely. See main.js's
# getWindowsLocation() for how this gets invoked and parsed.
# ASCII only in this file on purpose: Windows PowerShell 5.1 reads a
# .ps1 without a BOM using the system ANSI codepage, and non-ASCII
# punctuation (em dashes, curly quotes) gets mangled into broken tokens.
$ErrorActionPreference = "Stop"
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
    })[0]

    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        return $netTask.Result
    }

    [Windows.Devices.Geolocation.Geolocator, Windows.Devices.Geolocation, ContentType = WindowsRuntime] | Out-Null
    $geolocator = New-Object Windows.Devices.Geolocation.Geolocator
    $geolocator.DesiredAccuracy = [Windows.Devices.Geolocation.PositionAccuracy]::Default

    $accessStatus = Await ([Windows.Devices.Geolocation.Geolocator]::RequestAccessAsync()) ([Windows.Devices.Geolocation.GeolocationAccessStatus])
    if ($accessStatus -ne [Windows.Devices.Geolocation.GeolocationAccessStatus]::Allowed) {
        $msg = "Windows denied location access (status: " + $accessStatus + "). Check Settings, Privacy and security, Location."
        Write-Output (@{ ok = $false; error = $msg } | ConvertTo-Json -Compress)
        exit 0
    }

    $pos = Await ($geolocator.GetGeopositionAsync()) ([Windows.Devices.Geolocation.Geoposition])
    $result = @{
        ok = $true
        lat = $pos.Coordinate.Point.Position.Latitude
        lon = $pos.Coordinate.Point.Position.Longitude
        accuracy_m = $pos.Coordinate.Accuracy
    }
    Write-Output ($result | ConvertTo-Json -Compress)
} catch {
    Write-Output (@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress)
}
