# Memory alerts

Setup installs a desktop memory monitor that starts with your GNOME session.
When setup runs without an active graphical session, monitoring starts at the
next graphical login. The monitor warns you to save work and avoid starting more
heavy jobs. It never kills, pauses, or limits processes, and does not change swap
or Linux OOM policies.

## Warnings

The monitor checks every five seconds. Defaults are maintained in
[the public configuration](../../ansible/group_vars/all.yml):

| Reading                                         | Warning     | Urgent       |
| ----------------------------------------------- | ----------- | ------------ |
| Available RAM                                   | At most 20% | At most 10%  |
| Full memory pressure, averaged over ten seconds | At least 5% | At least 15% |

Either reading can trigger an alert. Warnings require ten seconds of sustained
pressure; urgent alerts are sent on the first matching sample. With 30 GiB of
usable RAM, the available-memory thresholds are approximately 6 GiB and 3 GiB.

Available RAM includes reclaimable cache. Memory pressure measures time when all
non-idle tasks are stalled on memory. Swap usage appears in the notification for
context; occupied swap alone does not trigger an alert.

Alerts include the largest four processes by individual RSS, with their names
and PIDs. Shared memory can appear in several processes' RSS, so these figures
are not a breakdown of unique RAM usage. Command arguments and environment
variables are not collected.

Notifications replace the previous alert. Warnings repeat at most every ten
minutes and urgent alerts every two minutes. Urgent alerts request persistent
display, subject to your desktop's notification settings. Recovery requires
30 seconds with available RAM above 1.2 times the relevant threshold and memory
pressure below 0.8 times its threshold. Failed notification delivery is logged
and retried.

## Adjust thresholds

Set overrides in your private configuration and rerun setup:

```yaml
desktop:
  memory_alerts:
    available_warning_percent: 25
    available_critical_percent: 12
```

Unspecified thresholds inherit the defaults. Each value must be a number above
zero and at most 100. The available-RAM critical threshold must be below its
warning threshold; the pressure critical threshold must be above its warning
threshold. Unknown settings are rejected.

## Check monitoring

Run these commands as your desktop user:

```sh
~/.local/bin/workstation-manager-memory-alerts --status
~/.local/bin/workstation-manager-memory-alerts --test-notification
systemctl --user status workstation-manager-memory-alerts.service
journalctl --user -u workstation-manager-memory-alerts.service -n 30 --no-pager
```

The test sends a notification without allocating memory or changing workloads.
If it succeeds but no banner appears, check GNOME notification settings and Do
Not Disturb. The journal records delivered alerts and monitoring errors.

Alerts provide reaction time; they do not reserve memory or guarantee that work
survives a sudden allocation spike. Suspend and desktop notification settings
can delay or hide warnings. Existing kernel and systemd OOM policies still
apply. When warned, save work and reduce concurrent builds, tests, or containers
before available memory runs out.
