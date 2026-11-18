# Ouvre un PPTX dans PowerPoint (sans fenêtre) et exporte chaque slide en PNG.
# Sert de vérification CA-04 : si PowerPoint ne peut pas ouvrir le fichier, le script échoue.
# Usage : powershell -File tools\preview_pptx.ps1 output\fichier.pptx
param([Parameter(Mandatory = $true)][string]$Path)

$file = (Resolve-Path $Path).Path
$outDir = Join-Path (Split-Path $file) ([IO.Path]::GetFileNameWithoutExtension($file) + "_preview")
New-Item -ItemType Directory -Force $outDir | Out-Null

$pp = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $pres = $pp.Presentations.Open($file, -1, 0, 0)
    $i = 0
    foreach ($slide in $pres.Slides) {
        $i++
        $slide.Export((Join-Path $outDir ("slide{0:D2}.png" -f $i)), "PNG", 1280, 720)
    }
    Write-Output "PowerPoint a ouvert $($pres.Slides.Count) slides ; aperçus dans $outDir"
    $pres.Close()
}
finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
