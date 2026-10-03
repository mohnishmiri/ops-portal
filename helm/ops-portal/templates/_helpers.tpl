{{/*
Common template helpers for Ops Portal Helm chart.
*/}}

{{- define "ops-portal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ops-portal.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "ops-portal.labels" -}}
helm.sh/chart: {{ include "ops-portal.name" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{/*
Non-empty when an azureKeyVaultSecrets item is synced and wired into the
container env: not `enabled: false`, envName not in `skip`, group not in
`skipGroups`.
Usage: include "ops-portal.akvsItemEnabled" (dict "cfg" .Values.backend.azureKeyVaultSecrets "item" .)
*/}}
{{- define "ops-portal.akvsItemEnabled" -}}
{{- $item := .item -}}
{{- $skip := .cfg.skip | default list -}}
{{- $skipGroups := .cfg.skipGroups | default list -}}
{{- if and (or (not (hasKey $item "enabled")) $item.enabled) (not (has $item.envName $skip)) (not (and $item.group (has $item.group $skipGroups))) -}}
true
{{- end -}}
{{- end }}

{{/*
Fails the render on a skip/skipGroups entry that matches no item, so a typo
can't silently leave a secret in place.
Usage: include "ops-portal.akvsValidateSkips" (dict "cfg" .Values.backend.azureKeyVaultSecrets "path" "backend.azureKeyVaultSecrets")
*/}}
{{- define "ops-portal.akvsValidateSkips" -}}
{{- $names := list -}}
{{- $groups := list -}}
{{- range .cfg.items -}}
{{- $names = append $names .envName -}}
{{- if .group }}{{ $groups = append $groups .group }}{{ end -}}
{{- end -}}
{{- range (.cfg.skip | default list) -}}
{{- if not (has . $names) }}{{ fail (printf "%s.skip: no item has envName %q" $.path .) }}{{ end -}}
{{- end -}}
{{- range (.cfg.skipGroups | default list) -}}
{{- if not (has . $groups) }}{{ fail (printf "%s.skipGroups: no item has group %q (known: %s)" $.path . (join ", " (uniq $groups))) }}{{ end -}}
{{- end -}}
{{- end }}
