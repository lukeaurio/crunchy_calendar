# Crunchy Calendar Helm chart

This chart installs two connected workloads in one namespace:

```text
Kubernetes CronJob -> private ClusterIP Postfix relay -> upstream SMTP relay -> recipient inbox
```

The CronJob uses the same standard-library Python batch command as the container and emails an ICS prediction based on the previous week's Crunchyroll schedule. Postfix is deliberately a private outbound relay, not an end-user mailbox server. The selected `bokysan/docker-postfix` image is an open-source Postfix null-client image intended for application email queues and supports Kubernetes Secrets for upstream relay credentials. Its submission listener is port 587. [Project documentation](https://github.com/bokysan/docker-postfix#description)

## Before installing

Build and publish the calendar image from this repository, then make a non-secret values file from `values.example.yaml`. Every image reference, mail address, schedule, resource limit, sender policy, and upstream relay is a chart value. The chart intentionally refuses to render until you select a calendar image version and a Postfix image version (or digests).

Create the Postfix upstream password Secret outside Helm. This avoids placing credentials in a release values file or rendered ConfigMap:

```sh
kubectl -n your-namespace create secret generic crunchy-calendar-relay \
  --from-file=relay-password=/path/to/upstream-smtp-password
```

The `relay-password` key must agree with `smtp.relay.passwordKey`. Set `smtp.relay.host`, `smtp.relay.username`, and `smtp.relay.existingSecret` together. An empty `smtp.relay.host` asks Postfix to deliver directly to MX records; that requires unblocked egress on port 25 plus SPF, DKIM, PTR, and IP reputation, so an authenticated upstream relay is the normal production choice. [Postfix image delivery guidance](https://github.com/bokysan/docker-postfix#tldr)

`smtp.allowedSenderDomains` must include the domain in `batch.mail.from`, for example `example.com` for `calendar-bot@example.com`. The relay Service is always `ClusterIP`, and the chart’s NetworkPolicy allows TCP/587 only from this release’s CronJob Pods. NetworkPolicy enforcement depends on the cluster’s CNI.

## Install and verify

```sh
cp charts/crunchy-calendar/values.example.yaml crunchy-calendar-values.yaml
# Edit crunchy-calendar-values.yaml; do not commit it.

helm lint charts/crunchy-calendar -f crunchy-calendar-values.yaml
helm upgrade --install crunchy-calendar charts/crunchy-calendar \
  --namespace your-namespace --create-namespace \
  --values crunchy-calendar-values.yaml
```

The default schedule is 06:00 Monday in `America/New_York`. It prevents overlapping runs and does not retry after a mail attempt, since an SMTP acknowledgement can be ambiguous.

Run once without waiting for the schedule:

```sh
kubectl -n your-namespace create job \
  --from=cronjob/crunchy-calendar-crunchy-calendar \
  crunchy-calendar-manual
kubectl -n your-namespace logs job/crunchy-calendar-manual
```

The actual CronJob name is rendered as `<release>-crunchy-calendar`; use `kubectl get cronjob` if a name override is set.

## Mail transport and storage

By default the Python job connects in `plain` mode only to the generated private ClusterIP Service. That keeps the internal hop simple while the relay makes a TLS-protected upstream connection (`smtp.postfix.upstreamTlsSecurityLevel: encrypt`). Do not set `batch.smtp.security: plain` for a public SMTP endpoint. Set `starttls` or `ssl`, provide `batch.smtp.host` and `batch.smtp.port`, and disable the bundled relay when using an external SMTP server.

The Postfix queue uses an `emptyDir` by default. Enable `smtp.persistence` to retain messages queued while the upstream is unavailable; persistent queues require exactly one relay replica. The bundled Postfix image needs write access to its queue, so its security contexts are values instead of forced non-root defaults.

For the complete configurable surface, use `helm show values charts/crunchy-calendar`. `values.schema.json` checks basic types and ranges; template validation checks the required cross-field combinations before Kubernetes receives a manifest.
