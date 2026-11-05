# BunnyLoL - Reconexion automatica del overlay del iPad.
# Escrito para Windows PowerShell 5.1 (tambien funciona en PowerShell 7).
#
# COMO USARLO: abre PowerShell en la carpeta del proyecto (la que contiene app.py),
# con fix-ipad-reconexion.patch en esa misma carpeta, y ejecuta:
#
#     powershell -ExecutionPolicy Bypass -File .\aplicar_fix_ipad.ps1
#
# QUE HACE:
#   - Parte de la rama etapa-2-multi-ia y crea la rama nueva fix-ipad-reconexion.
#   - Aplica los 3 commits de fix-ipad-reconexion.patch con "git am --3way".
#
# QUE NO HACE: no toca main, no hace push, no usa reset --hard, no borra archivos
# y no sobrescribe cambios locales. Si algo no cuadra, se detiene ANTES de cambiar nada.

$ErrorActionPreference = "Stop"

$RamaBase   = "etapa-2-multi-ia"
$RamaNueva  = "fix-ipad-reconexion"
$Parche     = "fix-ipad-reconexion.patch"

# Unicos archivos sin seguimiento que se permiten en la carpeta (nombre exacto).
$Auxiliares = @(
    "fix-ipad-reconexion.patch",
    "aplicar_fix_ipad.ps1",
    "0001-Etapa-2-gestor-multi-IA-modular-backend-ai.patch",
    "aplicar_etapa2.ps1"
)

$script:GitCodigo = 0

# Ejecuta git y se detiene si falla. Se llama Invoke-Git (no "Git") para no llamarse a si misma.
function Invoke-Git {
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & git @args
        $codigo = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previo
    }
    if ($codigo -ne 0) {
        throw ("git " + ($args -join " ") + " fallo (codigo " + $codigo + "). Lee el mensaje de git que aparece arriba.")
    }
}

# Ejecuta git y devuelve su salida. NO se detiene si falla: deja el codigo en $script:GitCodigo.
function Get-Git {
    $previo = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $salida = & git @args
        $script:GitCodigo = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previo
    }
    if ($null -ne $salida) { return $salida }
}

function Write-Paso([string]$Texto) {
    Write-Host ""
    Write-Host $Texto -ForegroundColor Cyan
}

$codigoSalida = 0
Push-Location
try {
    # ---------------------------------------------------------------- 0) Donde estamos
    if ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "app.py"))) {
        Set-Location -LiteralPath $PSScriptRoot
    }
    if (-not (Test-Path -LiteralPath ".git") -or -not (Test-Path -LiteralPath "app.py")) {
        throw "Ejecuta esto en la raiz del proyecto (la carpeta donde estan .git y app.py)."
    }
    if (-not (Get-Command git -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "No se encuentra Git. Instalalo (https://git-scm.com) y abre una PowerShell nueva."
    }
    $dentro = @(Get-Git rev-parse --is-inside-work-tree)
    if ($script:GitCodigo -ne 0 -or $dentro[0] -ne "true") {
        throw "Esta carpeta no es un repositorio de Git valido."
    }

    # ---------------------------------------------------------------- 1) Comprobar el parche
    Write-Paso "[1/6] Comprobando el parche..."
    if (-not (Test-Path -LiteralPath $Parche)) { throw "Falta $Parche en esta carpeta." }
    $rutaParche = Join-Path (Get-Location).ProviderPath $Parche

    $bytes = [System.IO.File]::ReadAllBytes($rutaParche)
    if ([Array]::IndexOf($bytes, [byte]13) -ge 0) {
        throw ("El archivo $Parche tiene saltos de linea de Windows (CRLF) y git no podria aplicarlo bien. " +
               "Vuelve a copiar el original sin abrirlo ni guardarlo con ningun editor.")
    }
    $texto = [System.IO.File]::ReadAllText($rutaParche)
    $commits = [regex]::Matches($texto, '(?m)^From [0-9a-f]{40} Mon Sep 17 00:00:00 2001\s*$')
    if ($commits.Count -ne 3) {
        throw ("El parche debe contener exactamente 3 commits y contiene " + $commits.Count + ". No se ha cambiado nada.")
    }
    $partes = [regex]::Matches($texto, '(?m)^Subject: \[PATCH ([0-9])/3\]')
    $orden = ""
    foreach ($p in $partes) { $orden += $p.Groups[1].Value }
    if ($orden -ne "123") {
        throw "Los 3 commits del parche no estan en el orden 1/3, 2/3, 3/3. No se ha cambiado nada."
    }
    Write-Host "Parche correcto: 3 commits en orden (1/3, 2/3, 3/3)."

    # ---------------------------------------------------------------- 2) Seguridad de Git
    Write-Paso "[2/6] Comprobando que es seguro continuar..."

    $dirGit = @(Get-Git rev-parse --git-dir)
    if ($script:GitCodigo -ne 0) { throw "No se pudo localizar la carpeta .git." }
    if ([System.IO.Path]::IsPathRooted($dirGit[0])) {
        $dirGitRuta = $dirGit[0]
    } else {
        $dirGitRuta = Join-Path (Get-Location).ProviderPath $dirGit[0]
    }
    foreach ($marca in @("rebase-apply", "rebase-merge", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD")) {
        if (Test-Path -LiteralPath (Join-Path $dirGitRuta $marca)) {
            throw ("Hay una operacion de git a medias ($marca). Terminala o cancelala antes de usar este instalador. " +
                   "No se ha cambiado nada.")
        }
    }

    $urlOrigin = @(Get-Git config --get remote.origin.url)
    if ($script:GitCodigo -ne 0 -or -not $urlOrigin[0]) {
        throw "No existe el remoto 'origin' (GitHub). No se ha cambiado nada."
    }
    Write-Host "Remoto origin: $($urlOrigin[0])"

    # Arbol limpio: solo se perdonan los 4 archivos auxiliares, sin seguimiento y con nombre exacto.
    $estado = @(Get-Git status --porcelain)
    if ($script:GitCodigo -ne 0) { throw "No se pudo leer el estado de git." }
    $sucio = @()
    foreach ($linea in $estado) {
        if ($linea -and $linea.Length -ge 4 -and $linea.Substring(0, 3) -eq "?? " -and ($Auxiliares -contains $linea.Substring(3))) {
            continue
        }
        if ($linea) { $sucio += $linea }
    }
    if ($sucio.Count -gt 0) {
        throw ("Hay cambios sin guardar o archivos que no son los 4 auxiliares autorizados:`n" +
               ($sucio -join "`n") +
               "`nGuardalos con commit o stash y vuelve a ejecutar. No se ha cambiado nada.")
    }
    Write-Host "Carpeta limpia (solo hay archivos auxiliares permitidos)."

    # La rama nueva no debe existir todavia (ni aqui ni en GitHub).
    $null = Get-Git show-ref --verify --quiet "refs/heads/$RamaNueva"
    if ($script:GitCodigo -eq 0) {
        throw ("Ya existe la rama $RamaNueva en tu PC. No se ha cambiado nada.`n" +
               "  - Si es de un intento anterior y no la necesitas, apartala SIN borrar nada:`n" +
               "        git branch -m $RamaNueva $RamaNueva-antigua`n" +
               "    y vuelve a ejecutar este instalador.`n" +
               "  - Si crees que ya tiene el arreglo, mira que contiene con:`n" +
               "        git log --oneline $RamaBase..$RamaNueva")
    }

    # main: se anota para comprobar al final que no cambio.
    $mainAntes = ""
    $tmp = @(Get-Git rev-parse --verify --quiet refs/heads/main)
    if ($script:GitCodigo -eq 0) { $mainAntes = $tmp[0] }

    # ---------------------------------------------------------------- 3) Actualizar referencias
    Write-Paso "[3/6] Consultando GitHub (solo lectura, no cambia tus archivos)..."
    Invoke-Git fetch origin $RamaBase

    $remota = @(Get-Git ls-remote --exit-code --heads origin $RamaNueva)
    if ($script:GitCodigo -eq 0) {
        throw ("La rama $RamaNueva ya existe en GitHub (origin). No se ha cambiado nada.`n" +
               "Para revisarla:  git fetch origin $RamaNueva   y   git log --oneline origin/$RamaNueva`n" +
               "Si quieres rehacerla, usa otro nombre de rama o pidele ayuda a quien te dio este instalador.")
    }
    if ($script:GitCodigo -ne 2) {
        throw "No se pudo consultar GitHub (codigo $($script:GitCodigo)). Revisa tu conexion y vuelve a intentarlo."
    }

    # ---------------------------------------------------------------- 4) Partir de etapa-2-multi-ia
    Write-Paso "[4/6] Colocandose en $RamaBase..."
    Invoke-Git checkout $RamaBase
    try {
        Invoke-Git pull --ff-only origin $RamaBase
    } catch {
        throw ("Tu rama $RamaBase local y la de GitHub no se pueden unir sin mezclar historias. " +
               "No se ha creado ninguna rama ni se ha tocado nada mas.`n" + $_.Exception.Message)
    }
    $baseCorta = @(Get-Git rev-parse --short HEAD)
    $baseSha = @(Get-Git rev-parse HEAD)
    if ($script:GitCodigo -ne 0) { throw "No se pudo leer el commit actual." }
    Write-Host "Partiendo de $RamaBase en $($baseCorta[0])"

    # ---------------------------------------------------------------- 5) Crear rama y aplicar
    Write-Paso "[5/6] Creando la rama $RamaNueva y aplicando los 3 commits..."
    Invoke-Git checkout -b $RamaNueva

    # Si no tienes nombre/correo configurados en git, se usa uno generico solo para esta operacion.
    $amArgs = @()
    $null = Get-Git config --get user.name
    if ($script:GitCodigo -ne 0) { $amArgs += @("-c", "user.name=Claude") }
    $null = Get-Git config --get user.email
    if ($script:GitCodigo -ne 0) { $amArgs += @("-c", "user.email=noreply@anthropic.com") }
    $amArgs += @("am", "--3way", $Parche)

    try {
        Invoke-Git @amArgs
    } catch {
        throw ("No se pudieron aplicar los 3 commits. NO se ha descartado nada: git quedo a mitad de la operacion.`n" +
               "Para dejarlo todo como estaba (seguro, no borra tus archivos):`n" +
               "    git am --abort`n" +
               "    git checkout $RamaBase`n" +
               "    git branch -d $RamaNueva`n" +
               "Para resolver el conflicto a mano: arreglalo, usa  git add <archivo>  y luego  git am --continue`n" +
               "Detalle: " + $_.Exception.Message)
    }

    # ---------------------------------------------------------------- 6) Verificar
    Write-Paso "[6/6] Verificando el resultado..."
    $nuevos = @(Get-Git rev-list --count ($baseSha[0] + "..HEAD"))
    $ramaActual = @(Get-Git rev-parse --abbrev-ref HEAD)
    if ($nuevos[0] -ne "3") {
        throw ("Se esperaban 3 commits nuevos sobre $RamaBase y hay " + $nuevos[0] + ". Revisa con: git log --oneline -5")
    }
    if ($ramaActual[0] -ne $RamaNueva) {
        throw "Estas en la rama $($ramaActual[0]) y se esperaba $RamaNueva."
    }
    $mainDespues = ""
    $tmp = @(Get-Git rev-parse --verify --quiet refs/heads/main)
    if ($script:GitCodigo -eq 0) { $mainDespues = $tmp[0] }
    if ($mainAntes -ne $mainDespues) {
        throw "ATENCION: la rama main cambio durante la operacion. Detente y avisa antes de seguir."
    }
    Write-Host "OK: rama $RamaNueva con 3 commits nuevos sobre $RamaBase. main no ha cambiado."
    Write-Host ""
    Invoke-Git log --oneline -5

    Write-Host ""
    Write-Host "Listo. Comprueba con:  python -m pytest -q tests   (esperado: 249 passed; sin Node o Playwright se omiten algunas pruebas)"
    Write-Host "El instalador NO sube nada. Cuando lo hayas revisado, sube con:  git push -u origin $RamaNueva"
    Write-Host ""
    Write-Host "IMPORTANTE: cierra y vuelve a abrir BunnyLoL y el puente (iPad.bat) para que usen el codigo nuevo."
    Write-Host "Despues, en el iPad, abre el enlace una vez para cargar la version nueva del overlay."
    Write-Host "Si vuelve a pasar, envia: cache\overlay_conn.log y cache\ipad_bridge.log"
} catch {
    Write-Host ""
    Write-Host "DETENIDO: $($_.Exception.Message)" -ForegroundColor Red
    $codigoSalida = 1
} finally {
    Pop-Location
}
if ($PSCommandPath) { exit $codigoSalida }
