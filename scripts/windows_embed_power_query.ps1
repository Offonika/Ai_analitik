param(
    [Parameter(Mandatory = $true)]
    [string]$PackageDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputWorkbook,

    [switch]$SkipTables
)

$ErrorActionPreference = "Stop"

function Release-ComObject {
    param([object]$Object)
    if ($null -ne $Object) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Object)
    }
}

function Query-NameFromFile {
    param([string]$FileName)
    $name = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    if ($name -match "^\d+_(.+)$") {
        return $Matches[1]
    }
    return $name
}

function Invoke-ExcelCom {
    param(
        [scriptblock]$Action,
        [int]$Retries = 30,
        [int]$DelayMilliseconds = 500
    )

    for ($attempt = 1; $attempt -le $Retries; $attempt += 1) {
        try {
            return & $Action
        }
        catch {
            $message = $_.Exception.Message
            $hresult = $_.Exception.HResult
            $details = $_.ToString()
            $exceptionType = $_.Exception.GetType().FullName
            $isRejected = (
                ($exceptionType -eq "System.Runtime.InteropServices.COMException") `
                -or ($hresult -eq -2147418111) `
                -or ($message -like "*RPC_E_CALL_REJECTED*") `
                -or ($details -like "*RPC_E_CALL_REJECTED*") `
                -or ($details -like "*0x80010001*")
            )
            if (($attempt -eq $Retries) -or (-not $isRejected)) {
                throw
            }
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }
}

function Delete-SheetIfExists {
    param(
        [object]$Workbook,
        [string]$SheetName
    )
    foreach ($sheet in @($Workbook.Worksheets)) {
        if ($sheet.Name -eq $SheetName) {
            $sheet.Delete()
            break
        }
    }
}

function Add-QueryTableIfPossible {
    param(
        [object]$Workbook,
        [string]$QueryName,
        [string]$SheetName,
        [string]$TableName
    )

    Delete-SheetIfExists -Workbook $Workbook -SheetName $SheetName
    $sheet = $Workbook.Worksheets.Add()
    $sheet.Name = $SheetName
    $sheet.Range("A1").Value2 = "Power Query: $QueryName"
    $sheet.Range("A2").Value2 = "Data will load after credentials are approved and Refresh All is pressed."

    try {
        $connectionString = "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=`$Workbook`$;Location=$QueryName;Extended Properties=`"`""
        $source = @($connectionString)
        $destination = $sheet.Range("A4")
        $listObject = $sheet.ListObjects.Add(0, $source, $true, 1, $destination)
        $listObject.Name = $TableName
        $listObject.QueryTable.CommandType = 2
        $listObject.QueryTable.CommandText = "SELECT * FROM [$QueryName]"
        $listObject.QueryTable.BackgroundQuery = $false
        $listObject.QueryTable.RefreshOnFileOpen = $false
        return "loaded"
    }
    catch {
        $sheet.Range("A4").Value2 = "Connection-only query is embedded. Load to table after entering database credentials."
        return "connection-only"
    }
}

$template = Get-ChildItem -Path $PackageDir -Filter "*Template*.xlsx" |
    Select-Object -First 1
if ($null -eq $template) {
    $template = Get-ChildItem -Path $PackageDir -Filter "*.xlsx" |
        Where-Object { $_.Name -notlike "*Ready*" } |
        Select-Object -First 1
}
if ($null -eq $template) {
    throw "Template workbook was not found in $PackageDir"
}

$queryDir = Join-Path $PackageDir "power_query_m"
if (-not (Test-Path $queryDir)) {
    throw "Power Query directory was not found: $queryDir"
}

$excel = $null
$workbook = $null

try {
    Write-Output "Opening Excel"
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AskToUpdateLinks = $false

    Write-Output "Opening template"
    $workbook = Invoke-ExcelCom { $excel.Workbooks.Open($template.FullName) }
    Start-Sleep -Seconds 3

    Write-Output "Clearing existing queries"
    while ($workbook.Queries.Count -gt 0) {
        Invoke-ExcelCom { $workbook.Queries.Item(1).Delete() } | Out-Null
    }

    Write-Output "Adding Power Query formulas"
    $queryFiles = Get-ChildItem -Path $queryDir -Filter "*.pq" | Sort-Object Name
    foreach ($file in $queryFiles) {
        $queryName = Query-NameFromFile -FileName $file.Name
        $formula = Get-Content -Path $file.FullName -Raw -Encoding UTF8
        Invoke-ExcelCom {
            $workbook.Queries.Add($queryName, $formula, "Generated WB/1C Power Query")
        } | Out-Null
    }

    $marts = @(
        @{ Query = "kpi_period"; Sheet = "PQ_kpi"; Table = "tbl_kpi_period" },
        @{ Query = "monthly_dynamics"; Sheet = "PQ_monthly"; Table = "tbl_monthly_dynamics" },
        @{ Query = "expenses"; Sheet = "PQ_expenses"; Table = "tbl_expenses" },
        @{ Query = "unit_economics"; Sheet = "PQ_unit_economics"; Table = "tbl_unit_economics" },
        @{ Query = "returns"; Sheet = "PQ_returns"; Table = "tbl_returns" },
        @{ Query = "lost_sales"; Sheet = "PQ_lost_sales"; Table = "tbl_lost_sales" },
        @{ Query = "onec_opiu_reconciliation"; Sheet = "PQ_1C_recon"; Table = "tbl_onec_opiu_reconciliation" }
    )

    $loadStatus = @()
    if ($SkipTables) {
        foreach ($mart in $marts) {
            $loadStatus += "$($mart.Query): embedded query"
        }
    }
    else {
        Write-Output "Adding worksheet query tables"
        foreach ($mart in $marts) {
            $status = Add-QueryTableIfPossible `
                -Workbook $workbook `
                -QueryName $mart.Query `
                -SheetName $mart.Sheet `
                -TableName $mart.Table
            $loadStatus += "$($mart.Query): $status"
        }
    }

    Write-Output "Writing status sheet"
    Delete-SheetIfExists -Workbook $workbook -SheetName "Power Query status"
    $statusSheet = $workbook.Worksheets.Add()
    $statusSheet.Name = "Power Query status"
    $statusSheet.Range("A1").Value2 = "Power Query is embedded"
    $statusSheet.Range("A2").Value2 = "Use Data -> Refresh All after setting pServer and database credentials."
    $row = 4
    foreach ($line in $loadStatus) {
        $statusSheet.Range("A$row").Value2 = $line
        $row += 1
    }
    $statusSheet.Columns.AutoFit() | Out-Null

    Write-Output "Saving workbook"
    Invoke-ExcelCom { $workbook.SaveAs($OutputWorkbook, 51) } | Out-Null
    $workbook.Close($true)
    $workbook = $null

    Write-Output $OutputWorkbook
}
finally {
    if ($null -ne $workbook) {
        $workbook.Close($false)
    }
    if ($null -ne $excel) {
        $excel.Quit()
    }
    Release-ComObject -Object $workbook
    Release-ComObject -Object $excel
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
