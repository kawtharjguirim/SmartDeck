# Secours de l'étape 12 : export PDF avec PowerPoint quand LibreOffice est absent.
# Usage : powershell -File tools\pptx_to_pdf.ps1 entree.pptx sortie.pdf
param(
    [Parameter(Mandatory = $true)][string]$Pptx,
    [Parameter(Mandatory = $true)][string]$Pdf
)
$ErrorActionPreference = "Stop"
$pp = New-Object -ComObject PowerPoint.Application
try {
    # Open(FileName, ReadOnly, Untitled, WithWindow)
    $pres = $pp.Presentations.Open((Resolve-Path $Pptx).Path, -1, 0, 0)
    $pres.SaveAs($Pdf, 32)  # 32 = ppSaveAsPDF
    $pres.Close()
}
finally {
    $pp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($pp) | Out-Null
}
