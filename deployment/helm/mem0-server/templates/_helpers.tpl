{{/*
Expand the name of the chart.
*/}}
{{- define "mem0-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "mem0-server.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "mem0-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "mem0-server.labels" -}}
helm.sh/chart: {{ include "mem0-server.chart" . }}
{{ include "mem0-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "mem0-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mem0-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "mem0-server.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "mem0-server.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Rules for the HTTPRoute. Every rule in `httpRoute.rules` gets this chart's
Service filled in as its backend unless it sets its own, and an empty
`httpRoute.rules` yields a single rule matching everything under `/`, which is
the HTTPRoute equivalent of the Ingress default.
*/}}
{{- define "mem0-server.httpRouteRules" -}}
{{- $route := .Values.httpRoute -}}
{{- $default := list (dict "matches" (list (dict "path" (dict "type" "PathPrefix" "value" "/")))) -}}
{{- $backend := dict "name" (include "mem0-server.fullname" .) "port" (int .Values.service.port) -}}
{{- $out := list -}}
{{- range default $default $route.rules -}}
{{- $rule := deepCopy . -}}
{{- if not (hasKey $rule "backendRefs") -}}
{{- $_ := set $rule "backendRefs" (list $backend) -}}
{{- end -}}
{{- if and $route.timeouts (not (hasKey $rule "timeouts")) -}}
{{- $_ := set $rule "timeouts" $route.timeouts -}}
{{- end -}}
{{- $out = append $out $rule -}}
{{- end -}}
{{- toYaml $out -}}
{{- end }}

{{/*
targetRefs entry pointing Envoy Gateway policies at this chart's HTTPRoute.
*/}}
{{- define "mem0-server.httpRouteTargetRef" -}}
- group: gateway.networking.k8s.io
  kind: HTTPRoute
  name: {{ include "mem0-server.fullname" . }}
{{- end }}
