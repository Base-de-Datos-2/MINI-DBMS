$ErrorActionPreference = 'Stop'
$taskRepo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskContainer = 'minidbms-postgis'
$taskVolume = 'minidbms-spatial-e1-pgdata'
$taskImage = 'postgis/postgis:17-3.5@sha256:01a6a70e41e6c4467c8f55f6063555ed72db2d6662cd0d571040d42eadaeb6f6'
docker version --format 'Docker server {{.Server.Version}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker server unavailable' }
$taskExistingContainers = @(docker ps -a --format '{{.Names}}')
$taskExistingVolumes = @(docker volume ls --format '{{.Name}}')
if ($taskExistingContainers -contains $taskContainer) { throw 'Container already exists; refusing replacement' }
if ($taskExistingVolumes -contains $taskVolume) { throw 'Volume already exists; refusing replacement' }
if (Get-NetTCPConnection -LocalPort 5433 -State Listen -ErrorAction SilentlyContinue) { throw 'Host port 5433 is already in use' }
$taskCredentialDir = Join-Path $taskRepo 'data\generated\postgres_e1'
if (Test-Path -LiteralPath $taskCredentialDir) { throw 'Comparator credential directory already exists; refusing replacement' }
New-Item -ItemType Directory -Path $taskCredentialDir | Out-Null
$taskPassword = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$taskEnvironment = "POSTGRES_USER=postgres`nPOSTGRES_DB=minidbms_spatial`nPOSTGRES_PASSWORD=$taskPassword`n"
$taskEnvironmentPath = Join-Path $taskCredentialDir 'postgres.env'
[IO.File]::WriteAllText($taskEnvironmentPath, $taskEnvironment, [Text.UTF8Encoding]::new($false))
$taskPassword = $null
$taskEnvironment = $null
docker volume create --label project=mini-dbms --label phase=e1 $taskVolume
if ($LASTEXITCODE -ne 0) { throw 'Could not create comparator volume' }
docker run -d --name $taskContainer --env-file $taskEnvironmentPath --publish '127.0.0.1:5433:5432' --mount "type=volume,source=$taskVolume,target=/var/lib/postgresql/data" --label project=mini-dbms --label phase=e1 --restart unless-stopped --health-cmd 'pg_isready -U postgres -d minidbms_spatial' --health-interval 5s --health-timeout 3s --health-start-period 15s --health-retries 6 $taskImage
if ($LASTEXITCODE -ne 0) { throw 'Could not start comparator container; generated credentials and volume preserved' }
Write-Output 'Comparator created: minidbms-postgis, database minidbms_spatial, host port 5433. Password retained locally in ignored generated data; it was not printed.'
