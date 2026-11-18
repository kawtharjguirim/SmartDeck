# CA-04 : ouvre chaque PPTX dans PowerPoint (sans fenêtre) et affiche « nom|slides » ou « nom|ERREUR ».
# Usage : powershell -File tools\check_open_pptx.ps1 a.pptx b.pptx ...
$pp = New-Object -ComObject PowerPoint.Application
try {
    foreach ($path in $args) {
        $name = [IO.Path]::GetFileName($path)
        try {
            # Open(FileName, ReadOnly, Untitled, WithWindow)
            $pres = $pp.Presentations.Open((Resolve-Path $path).Path, -1, 0, 0)
            Write-Output "$name|$($pres.Slides.Count)"
            $pres.Close()
        }
        catch {
            Write-Output "$name|ERREUR $($_.Exception.Message)"
        }
    }
}
finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
