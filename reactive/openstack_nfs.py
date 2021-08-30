import subprocess
import os
import json
import shutil

from charms.apt import queue_install
from charms.reactive import when, when_not, set_flag, hook
from charms.reactive.flags import register_trigger

from charmhelpers.core.hookenv import config, status_set, relation_set, relation_ids
from charmhelpers.core.fstab import Fstab
from charmhelpers.core.host import mkdir, owner

register_trigger(when='config.changed',
                 clear_flag='openstack-nfs.installed')


@when_not('openstack-nfs.installed')
def install_nova_compute_nfs_config():
    queue_install(['nfs-common'])
    status_set('maintenance', 'waiting for installation')


@when('apt.installed.nfs-common')
@when_not('openstack-nfs.installed')
def set_installed_message():
    set_flag('openstack-nfs.installed')
    status_set('maintenance', 'performing setup')


@hook('ephemeral-backend-relation-changed')
def nova_compute_changed():
    status_set('maintenance', 'nova-compute connected')
    set_flag('nova-compute.connected')


@hook('glance-backend-relation-changed')
def glance_changed():
    status_set('maintenance', 'glance connected')
    set_flag('glance.connected')


@when('nova-compute.connected', 'openstack-nfs.installed')
def update_nova_config():
    status_set('maintenance', 'configuring nova-compute')
    filesystem = config('nova-compute-filesystem')
    mountpoint = config('nova-compute-mountpoint')
    fstype = config('nova-compute-fstype')
    fsoptions = config('nova-compute-fsoptions')

    if filesystem is None:
        status_set('blocked', 'nova-compute-filesystem not set')
        return

    add_to_fstab(filesystem, mountpoint, fstype, fsoptions)
    try:
        create_or_chown_path(mountpoint, 'nova', 'nova')
    except PermissionError:
        status_set(
            'error', 'insufficient permissions to create {}'.format(mountpoint))
        return

    try:
        mount_filesystem_by_path(mountpoint)
    except subprocess.TimeoutExpired:
        status_set('blocked', 'Timed out on mount. Check configuration.')
        return
    except subprocess.CalledProcessError:
        status_set('blocked', 'Mount error. Check configuraton.')
        return

    ctx = {
        'nova': {
            '/etc/nova/nova.conf': {
                'sections': {
                    'DEFAULT': [
                        ('instances_path', mountpoint)
                    ]
                }
            }
        },
    }
    for r in relation_ids('ephemeral-backend'):
        relation_set(r, subordinate_configuration=json.dumps(ctx))
    status_set('active', 'mounted at {}'.format(mountpoint))


@when('glance.connected', 'openstack-nfs.installed')
def update_glance_config():
    status_set('maintenance', 'configuring glance')
    filesystem = config('glance-filesystem')
    mountpoint = config('glance-mountpoint')
    fstype = config('glance-fstype')
    fsoptions = config('glance-fsoptions')

    if filesystem is None:
        status_set('blocked', 'glance-filesystem not set')
        return

    add_to_fstab(filesystem, mountpoint, fstype, fsoptions)
    try:
        create_or_chown_path(mountpoint, 'glance', 'glance')
    except PermissionError:
        status_set(
            'error', 'insufficient permissions to create {}'.format(mountpoint))
        return

    try:
        mount_filesystem_by_path(mountpoint)
    except subprocess.TimeoutExpired:
        status_set('blocked', 'Timed out on mount. Check configuration.')
        return
    except subprocess.CalledProcessError:
        status_set('blocked', 'Mount error. Check configuraton.')
        return

    ctx = {
        'glance': {
            '/etc/glance/glance-api.conf': {
                'sections': {
                    'glance_store': [
                        ('filesystem_store_datadir', mountpoint)
                    ]
                }
            }
        },
    }
    for r in relation_ids('glance-backend'):
        relation_set(r, subordinate_configuration=json.dumps(ctx))
    status_set('active', 'mounted at {}'.format(mountpoint))


def create_or_chown_path(path, user, group):
    if not os.path.exists(path):
        mkdir(path, owner=user, group=group)

    path_owner = owner(path)
    if path_owner != (user, group):
        shutil.chown(path, user, group)


def add_to_fstab(filesystem, mountpoint, fstype, fsoptions):
    fstab = Fstab()

    existing_entry = fstab.get_entry_by_attr('mountpoint', filesystem)
    if existing_entry:
        fstab.remove_entry(existing_entry)

    Fstab.add(filesystem, mountpoint, fstype, fsoptions)


def mount_filesystem_by_path(mountpoint):
    if not os.path.exists(mountpoint):
        mkdir(mountpoint, force=True)

    subprocess.check_output(
        ['mount', mountpoint], timeout=config('mount-timeout')
    )
