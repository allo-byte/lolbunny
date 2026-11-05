# BunnyLoL - Etapa 2: gestor multi-IA (Windows PowerShell).
# Ejecutar DENTRO de la carpeta del proyecto (la que contiene app.py), con el archivo
# 0001-Etapa-2-gestor-multi-IA-modular-backend-ai.patch en esa misma carpeta.
$ErrorActionPreference = "Stop"

function Git { & (Get-Command git.exe -ErrorAction Stop).Source @args; if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') fallo" } }

$patch = "0001-Etapa-2-gestor-multi-IA-modular-backend-ai.patch"
if (-not (Test-Path ".git") -or -not (Test-Path "app.py")) { throw "Ejecuta esto en la raiz del proyecto (donde esta app.py)." }
if (-not (Test-Path $patch)) { throw "Falta $patch en esta carpeta." }

# 0) Seguridad: arbol limpio (el parche y este script sin rastrear no cuentan) y partir de etapa-1-limpieza
$sucio = & git status --porcelain | Where-Object { $_ -notmatch '^\?\? (0001-Etapa-2|aplicar_etapa2)' }
if ($sucio) { throw "Hay cambios sin guardar:`n$sucio`nHaz commit o stash antes de seguir." }
Git fetch origin etapa-1-limpieza
Git checkout etapa-1-limpieza
Git pull --ff-only origin etapa-1-limpieza
Write-Host "Partiendo de etapa-1-limpieza en $(& git rev-parse --short HEAD)"
Git checkout -b etapa-2-multi-ia

# 1) Aplicar el commit de la etapa 2
Git -c user.name="Claude" -c user.email="noreply@anthropic.com" am --3way $patch

# 2) Dependencia opcional para guardar claves en el Administrador de credenciales
Write-Host ""
Write-Host "Instalando keyring (claves en el Administrador de credenciales de Windows)..."
& python -m pip install "keyring>=24"
if ($LASTEXITCODE -ne 0) { Write-Host "AVISO: no se pudo instalar keyring; las claves se guardaran en un archivo local y el panel lo avisara." }

Write-Host ""
Write-Host "Listo. Comprueba con:  python -m pytest -q tests   (esperado: 223 passed)"
Write-Host "Si todo va bien, sube con:  git push -u origin etapa-2-multi-ia"

