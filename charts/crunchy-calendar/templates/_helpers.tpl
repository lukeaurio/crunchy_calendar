{{- define "crunchy-calendar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "crunchy-calendar.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "crunchy-calendar.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "crunchy-calendar.labels" -}}
app.kubernetes.io/name: {{ include "crunchy-calendar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "crunchy-calendar.selectorLabels" -}}
app.kubernetes.io/name: {{ include "crunchy-calendar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "crunchy-calendar.smtpServiceName" -}}
{{- printf "%s-smtp" (include "crunchy-calendar.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "crunchy-calendar.batchConfigName" -}}
{{- printf "%s-batch" (include "crunchy-calendar.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "crunchy-calendar.smtpConfigName" -}}
{{- printf "%s-smtp" (include "crunchy-calendar.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "crunchy-calendar.batchSmtpHost" -}}
{{- default (include "crunchy-calendar.smtpServiceName" .) .Values.batch.smtp.host }}
{{- end }}

{{- define "crunchy-calendar.batchSmtpPort" -}}
{{- default .Values.smtp.service.port .Values.batch.smtp.port }}
{{- end }}

{{- define "crunchy-calendar.image" -}}
{{- if .image.digest -}}
{{- printf "%s@%s" .image.repository .image.digest -}}
{{- else -}}
{{- printf "%s:%s" .image.repository .image.tag -}}
{{- end -}}
{{- end }}

{{- define "crunchy-calendar.validate" -}}
{{- if not .Values.batch.image.repository }}{{ fail "batch.image.repository is required" }}{{ end }}
{{- if and (not .Values.batch.image.tag) (not .Values.batch.image.digest) }}{{ fail "batch.image.tag or batch.image.digest is required" }}{{ end }}
{{- if and .Values.batch.image.tag .Values.batch.image.digest }}{{ fail "set only one of batch.image.tag and batch.image.digest" }}{{ end }}
{{- if not .Values.batch.mail.from }}{{ fail "batch.mail.from is required" }}{{ end }}
{{- if not .Values.batch.mail.to }}{{ fail "batch.mail.to is required" }}{{ end }}
{{- if not (regexMatch "^[^@[:space:]]+@[^@[:space:]]+$" .Values.batch.mail.from) }}{{ fail "batch.mail.from must be a single email address" }}{{ end }}
{{- if regexMatch "[\\r\\n]" .Values.batch.mail.to }}{{ fail "batch.mail.to must not contain newlines" }}{{ end }}
{{- if ne (empty .Values.batch.smtp.auth.username) (empty .Values.batch.smtp.auth.existingSecret) }}{{ fail "batch.smtp.auth.username and batch.smtp.auth.existingSecret must be set together" }}{{ end }}
{{- if and .Values.batch.smtp.auth.existingSecret (not .Values.batch.smtp.auth.passwordKey) }}{{ fail "batch.smtp.auth.passwordKey is required when batch.smtp.auth.existingSecret is set" }}{{ end }}
{{- if .Values.smtp.enabled }}
  {{- if not .Values.smtp.image.repository }}{{ fail "smtp.image.repository is required" }}{{ end }}
  {{- if and (not .Values.smtp.image.tag) (not .Values.smtp.image.digest) }}{{ fail "smtp.image.tag or smtp.image.digest is required" }}{{ end }}
  {{- if and .Values.smtp.image.tag .Values.smtp.image.digest }}{{ fail "set only one of smtp.image.tag and smtp.image.digest" }}{{ end }}
  {{- if not .Values.smtp.allowedSenderDomains }}{{ fail "smtp.allowedSenderDomains is required" }}{{ end }}
  {{- if and .Values.smtp.persistence.enabled (ne (int .Values.smtp.replicas) 1) }}{{ fail "smtp.persistence.enabled requires smtp.replicas to be 1" }}{{ end }}
  {{- if ne (empty .Values.smtp.relay.username) (empty .Values.smtp.relay.existingSecret) }}{{ fail "smtp.relay.username and smtp.relay.existingSecret must be set together" }}{{ end }}
  {{- if and .Values.smtp.relay.existingSecret (not .Values.smtp.relay.passwordKey) }}{{ fail "smtp.relay.passwordKey is required when smtp.relay.existingSecret is set" }}{{ end }}
  {{- if and .Values.smtp.relay.existingSecret (not .Values.smtp.relay.host) }}{{ fail "smtp.relay.host is required when smtp.relay.existingSecret is set" }}{{ end }}
{{- else if not .Values.batch.smtp.host }}
  {{- fail "batch.smtp.host is required when smtp.enabled is false" }}
{{- else if eq (int .Values.batch.smtp.port) 0 }}
  {{- fail "batch.smtp.port must be between 1 and 65535 when smtp.enabled is false" }}
{{- end }}
{{- end }}
