import subprocess
import os
import json
import shutil

from charms.apt import queue_install
from charms.reactive import when, when_not, set_flag, endpoint_from_flag, hook
from charms.reactive.flags import register_trigger

from charmhelpers.core.hookenv import config, status_set, relation_set, log, relation_ids
from charmhelpers.core.fstab import Fstab
from charmhelpers.core.host import mkdir, owner

register_trigger(when='config.changed',
                 clear_flag='openstack-nfs.configured')


@when_not('openstack-nfs.installed')
def install_nova_compute_nfs_config():
    queue_install(['nfs-common'])
    status_set('maintenance', 'waiting for installation')


@when('apt.installed.nfs-common')
@when_not('openstack-nfs.installed')
def set_installed_message():
    set_flag('openstack-nfs.installed')
    status_set('maintenance', 'performing setup')


@when_not('openstack-nfs.configured')
@when('openstack-nfs.installed')
def configure():
    device = config('filesystem')
    mountpoint = config('mountpoint')
    filesystem_type = config('type')
    options = config('options')

    set_flag('openstack-nfs.configured')

    if not device:
        status_set('blocked', 'waiting for filesystem configuration')
        return

    fstab = Fstab()

    existing_entry = fstab.get_entry_by_attr('mountpoint', mountpoint)
    if existing_entry:
        try:
            status_set('maintenance', 'unmounting existing filesystem')
            subprocess.check_output(
                ['umount', mountpoint], timeout=config('mount-timeout')
            )
            fstab.remove_entry(existing_entry)
        except subprocess.TimeoutExpired:
            status_set('blocked', 'Timed out unmounting existing filesystem.')
            return
        except subprocess.CalledProcessError:
            status_set('blocked', 'Error unmounting existing filesystem.')
            return

    Fstab.add(device, mountpoint, filesystem_type, options)
    set_flag('openstack-nfs.mount')


@when('openstack-nfs.mount')
def mount():
    mountpoint = config('mountpoint')

    if not os.path.exists(mountpoint):
        try:
            mkdir(mountpoint, force=True)
        except PermissionError:
            status_set(
                'blocked', 'insufficient permissions to create {}'.format(mountpoint))
            return

    try:
        subprocess.check_output(
            ['mount', '-a'], timeout=config('mount-timeout')
        )
    except subprocess.TimeoutExpired:
        status_set('blocked', 'Timed out on mount. Check configuration.')
        return
    except subprocess.CalledProcessError:
        status_set('blocked', 'Mount error. Check configuraton.')
        return

    status_set('maintenance',
               'filesystem mounted successfully, waiting for relations')
    set_flag('openstack-nfs.ready')


@hook('ephemeral-backend-relation-changed')
def nova_compute_changed():
    status_set('maintenance', 'nova-compute connected, but not yet configured')
    set_flag('nova-compute.connected')


@hook('glance-backend-relation-changed')
def glance_changed():
    status_set('maintenance', 'glance connected, but not yet configured')
    set_flag('glance.connected')


@when('nova-compute.connected', 'openstack-nfs.ready')
def update_nova_config():
    status_set('maintenance', 'configuring nova-compute')
    path = os.path.join(config('mountpoint'), config('nova-path'))
    create_or_chown_path(path)
    ctx = {
        'nova': {
            '/etc/nova/nova.conf': {
                'sections': {
                    'DEFAULT': [
                        ('instances_path', path)
                    ]
                }
            }
        },
    }
    for r in relation_ids('ephemeral-backend'):
        relation_set(r, subordinate_configuration=json.dumps(ctx))
    status_set('active', 'filesystem mounted and config applied')


@when('glance.connected', 'openstack-nfs.ready')
def update_glance_config():
    status_set('maintenance', 'configuring glance')
    path = os.path.join(config('mountpoint'), config('glance-path'))
    create_or_chown_path(path)

    ctx = {
        'glance': {
            '/etc/glance/glance.conf': {
                'sections': {
                    'DEFAULT': [
                        ('instances_path', path)
                    ]
                }
            }
        },
    }
    for r in relation_ids('glance-backend'):
        relation_set(r, subordinate_configuration=json.dumps(ctx))
    status_set('active', 'filesystem mounted and config applied')


def create_or_chown_path(path, user, group):
    if not os.path.exists(path):
        try:
            mkdir(path, owner=user, group=group)
        except PermissionError:
            status_set(
                'blocked', 'unsufficient permissions to create {}'.format(path))
            return

    path_owner = owner(path)
    if path_owner != (user, group):
        try:
            shutil.chown(path, user, group)
        except PermissionError:
            status_set(
                'blocked', 'insufficient permissions to chown {} to {}'.format(path, user))
            return
