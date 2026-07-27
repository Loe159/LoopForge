$dbPath = "C:\Users\pnv_llg.ASP\.local\share\kilo\kilo.db"

if (-not (Test-Path $dbPath)) {
    Write-Host "Database file not found: $dbPath"
    exit 1
}

# Try System.Data.SQLite (bundled with some Windows installs)
$assemblies = @(
    [System.AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.FullName -like "*System.Data.SQLite*" }
)

if ($assemblies.Count -eq 0) {
    # Try to load from GAC or find it
    try {
        [System.Reflection.Assembly]::LoadWithPartialName("System.Data.SQLite") | Out-Null
    } catch {
        try {
            Add-Type -AssemblyName "System.Data.SQLite" -ErrorAction Stop
        } catch {
            Write-Host "System.Data.SQLite not available in this PowerShell session."
            exit 1
        }
    }
}

$connectionString = "Data Source=$dbPath;Version=3;Read Only=True;"
$connection = New-Object System.Data.SQLite.SQLiteConnection($connectionString)
$connection.Open()

function Execute-Query($sql) {
    $command = $connection.CreateCommand()
    $command.CommandText = $sql
    $adapter = New-Object System.Data.SQLite.SQLiteDataAdapter($command)
    $table = New-Object System.Data.DataTable
    $adapter.Fill($table)
    return $table
}

Write-Host ("=" * 120)
$sessions = Execute-Query @"
    SELECT s.*, p.worktree as project_worktree, p.name as project_name
    FROM session s
    LEFT JOIN project p ON s.project_id = p.id
    ORDER BY s.time_created DESC
"@
Write-Host "TOTAL SESSIONS: $($sessions.Rows.Count)"
Write-Host ("=" * 120)

$i = 0
foreach ($row in $sessions.Rows) {
    $i++
    Write-Host "`n--- Session #$i ---"
    foreach ($col in $sessions.Columns) {
        $val = if ($row[$col.ColumnName] -eq [DBNull]::Value) { "NULL" } else { $row[$col.ColumnName] }
        Write-Host "  $($col.ColumnName): $val"
    }
}

Write-Host "`n`n" + ("=" * 120)
Write-Host "ALL PROJECTS"
Write-Host ("=" * 120)
$projects = Execute-Query "SELECT * FROM project ORDER BY time_updated DESC"
foreach ($row in $projects.Rows) {
    Write-Host "`n  id: $($row['id'])"
    Write-Host "  name: $($row['name'])"
    Write-Host "  worktree: $($row['worktree'])"
    Write-Host "  vcs: $($row['vcs'])"
    Write-Host "  time_created: $($row['time_created'])"
    Write-Host "  time_updated: $($row['time_updated'])"
    Write-Host "  sandboxes: $($row['sandboxes'])"
}

Write-Host "`n`n" + ("=" * 120)
Write-Host "ALL PROJECT DIRECTORIES"
Write-Host ("=" * 120)
$dirs = Execute-Query "SELECT * FROM project_directory ORDER BY project_id, type"
foreach ($row in $dirs.Rows) {
    Write-Host "  project_id: $($row['project_id']), directory: $($row['directory']), type: $($row['type']), strategy: $($row['strategy'])"
}

$connection.Close()