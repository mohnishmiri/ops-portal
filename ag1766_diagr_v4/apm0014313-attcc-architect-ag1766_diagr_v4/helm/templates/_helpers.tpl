{{- define "migration-intake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "migration-intake.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "migration-intake.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "migration-intake.labels" -}}
app.kubernetes.io/name: {{ include "migration-intake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "migration-intake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "migration-intake.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- required "serviceAccount.name is required when create is false" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "migration-intake.claimName" -}}
{{- default (include "migration-intake.fullname" .) .Values.persistence.existingClaim -}}
{{- end -}}