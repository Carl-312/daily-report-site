<#
.SYNOPSIS
    Daily Report Generator - Local Runner
.DESCRIPTION
    本地运行脚本，支持随时生成 AI 新闻日报
.PARAMETER Offline
    使用离线模式（不调用 AI API，生成简单列表）
.PARAMETER NoCommit
    不自动提交到 Git
.EXAMPLE
    .\run_daily.ps1
    .\run_daily.ps1 -Offline
    .\run_daily.ps1 -NoCommit
#>

param(
    [switch]$Offline,
    [switch]$NoCommit
)

# 设置环境变量解决 Windows 控制台 Unicode 编码问题
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 彩色输出函数
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

function Write-Step {
    param([string]$Message)
    Write-ColorOutput "`n📌 $Message" "Cyan"
}

function Write-Success {
    param([string]$Message)
    Write-ColorOutput "✅ $Message" "Green"
}

function Write-Error {
    param([string]$Message)
    Write-ColorOutput "❌ $Message" "Red"
}

function Write-Warning {
    param([string]$Message)
    Write-ColorOutput "⚠️  $Message" "Yellow"
}

# 脚本开始
Write-ColorOutput "`n========================================" "Magenta"
Write-ColorOutput "   Daily Report Generator" "Magenta"
Write-ColorOutput "========================================" "Magenta"

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 验证 Python 可用
Write-Step "检查运行环境"
try {
    $PythonVersion = python --version 2>&1
    Write-Success "Python: $PythonVersion"
}
catch {
    Write-Error "Python 不可用，请检查环境配置"
    exit 1
}

# 检查依赖
Write-Step "检查项目依赖"
if (-not (Test-Path "requirements.txt")) {
    Write-Error "未找到 requirements.txt"
    exit 1
}

# 执行生成流程
Write-Step "开始生成日报"

try {
    if ($Offline) {
        Write-ColorOutput "命令: python main.py run --offline`n" "Gray"
        python main.py run --offline
    }
    else {
        Write-ColorOutput "命令: python main.py run`n" "Gray"
        python main.py run
    }
    
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        Write-Error "生成失败，退出代码: $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    
    Write-Success "日报生成成功！"
}
catch {
    Write-Error "执行出错: $_"
    exit 1
}

# Git 提交（可选）
if (-not $NoCommit) {
    Write-Step "准备提交到 Git"
    
    # 检查是否有变更
    $GitStatus = git status --porcelain 2>$null
    if ($GitStatus) {
        $Date = Get-Date -Format "yyyy-MM-dd"
        $CommitMessage = "Daily report: $Date"
        
        try {
            git add content/ data/ docs/
            git commit -m $CommitMessage
            Write-Success "已提交: $CommitMessage"
            
            # 询问是否推送
            $Push = Read-Host "`n是否推送到远程仓库？(y/N)"
            if ($Push -eq "y" -or $Push -eq "Y") {
                git push
                Write-Success "已推送到远程仓库"
            }
            else {
                Write-Warning "跳过推送，请手动运行: git push"
            }
        }
        catch {
            Write-Warning "Git 操作失败: $_"
        }
    }
    else {
        Write-Warning "没有新的变更需要提交"
    }
}
else {
    Write-Warning "跳过 Git 提交（使用了 -NoCommit）"
}

# 完成
Write-ColorOutput "`n========================================" "Magenta"
Write-Success "全部完成！"
Write-ColorOutput "========================================`n" "Magenta"

# 提示本地预览
Write-ColorOutput "💡 本地预览:" "Yellow"
Write-ColorOutput "   cd docs" "Gray"
Write-ColorOutput "   python -m http.server 8000" "Gray"
Write-ColorOutput "   访问 http://localhost:8000`n" "Gray"
