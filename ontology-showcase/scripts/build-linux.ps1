# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$windowsScript = (Join-Path $PSScriptRoot 'build-linux.sh').Replace('\', '/')
$wslScript = (wsl.exe -d Ubuntu -- wslpath -a $windowsScript).Trim()
if (-not $wslScript) { throw 'Cannot resolve build-linux.sh inside WSL.' }
wsl.exe -d Ubuntu -- bash $wslScript
if ($LASTEXITCODE -ne 0) { throw "Linux build failed with exit code $LASTEXITCODE." }
Write-Host "Linux backend executable: $(Join-Path $projectRoot 'build\ontology-api')"
