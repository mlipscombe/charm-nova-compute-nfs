# Overview

This charm provides a simple NFS backend for ephemeral storage in Nova
and image storage in Glance.

It will create an entry in /etc/fstab, mount the filesystem and then
configure nova-compute and/or glance to use the mounted filesystem.

# Usage

To deploy the charm:

```
  juju deploy openstack-nfs \
    --config filesystem="10.10.64.10:/mnt/rpool/nova"
    --config mountpoint="/srv/nova"
    --config type=nfs4
    --config options="rsize=131072,wsize=131072"

  juju add-relation nova-compute openstack-nfs
  juju add-relation glance openstack-nfs
```

## Known Limitations and Issues

This is an alpha quality charm.  It does not yet gracefully handle reconfiguring
any parameters, and will require manual intervention on removal to restore the
original `instances_path` in `/etc/nova/nova.conf`.
