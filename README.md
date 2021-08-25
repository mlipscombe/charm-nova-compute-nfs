# Overview

This charm provides a simple NFS backend for ephemeral storage in Nova.

It will create an entry in /etc/fstab, mount the filesystem and then
configure nova-compute to use the mounted filesystem as its `instances_path`
location.

# Usage

Step by step instructions on using the charm:

```
  juju deploy nova-compute-nfs \
    --config filesystem="10.10.64.10:/mnt/rpool/nova"
    --config mountpoint="/srv/nova"
    --config type=nfs4
    --config options="rsize=131072,wsize=131072"

  juju add-relation nova-compute nova-compute-nfs
```

## Known Limitations and Issues

This is an alpha quality charm.  It does not yet gracefully handle reconfiguring
any parameters, and will require manual intervention on removal to restore the
original `instances_path` in `/etc/nova/nova.conf`.
