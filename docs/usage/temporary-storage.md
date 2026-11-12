# Temporary storage

Keep clones, Git worktrees, dependency installations, and build outputs in a
workspace on disk, such as a project's ignored `.cache/agent-work/` directory.
These are working files: review Git status and unpublished commits before removing
a checkout. Setup and scheduled temporary cleanup do not purge project workspaces.

## Disposable command files

After setup, run foreground commands that need temporary files through:

```sh
workstation-manager-scratch -- python3 -m pytest
```

The wrapper gives the command a private `TMPDIR` under
`~/.cache/workstation-manager/scratch/`, checks that its filesystem is neither
`tmpfs` nor `ramfs`, and preserves the current working directory and exit status.
It cleans this invocation's disposable directory when the command finishes,
including failures, and reports any entries still protected by locks or mounts.
Use it only for files that can be regenerated; write results
and source changes into the project workspace.

A cleanup error is reported and makes the wrapper fail, even if the command
succeeded.

Commands must honor `TMPDIR`; explicit writes to `/tmp` are unaffected. Existing
files in `/tmp`, other caches, and unrelated processes remain unmanaged.

## Active tasks and abandoned files

The wrapper holds a BSD directory lock while the command runs and passes it to
the command. Cleanup preserves the directory while a child still holds that lock.
Run each worker through the wrapper and wait for its children; a daemon that closes
inherited file descriptors no longer holds this protection.

Setup enables `workstation-manager-scratch-clean.timer` for the managed user.
Its daily cleanup removes unlocked disposable files after one day without use,
including files left after a crash. The timer starts in the current user session
when available, otherwise at the next login. Its service invokes
`systemd-tmpfiles` with only the manager's scratch rule; it does not activate
other user cleanup rules.

Inspect the schedule with:

```sh
systemctl --user status workstation-manager-scratch-clean.timer
```

Only the dedicated scratch directory is covered by the manager's rule. Cleanup
does not inspect repositories or decide whether source changes have been published.
