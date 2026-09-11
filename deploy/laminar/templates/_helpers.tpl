{{- define "laminar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "laminar.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "laminar.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "laminar.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{- define "laminar.labels" -}}
helm.sh/chart: {{ include "laminar.chart" . }}
app.kubernetes.io/name: {{ include "laminar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "laminar.selectorLabels" -}}
app.kubernetes.io/name: {{ include "laminar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "laminar.componentLabels" -}}
{{ include "laminar.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "laminar.componentSelectorLabels" -}}
{{ include "laminar.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "laminar.componentName" -}}
{{- printf "%s-%s" (include "laminar.fullname" .root) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "laminar.secretName" -}}
{{- required "auth.existingSecretName is required" .Values.auth.existingSecretName | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "laminar.image" -}}
{{- printf "%s:%s" .repository .tag -}}
{{- end -}}
