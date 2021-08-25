import subprocess
import sys
import os
import json
import shutil

from charms.apt import queue_install
from charms.reactive import when, when_not, set_flag, endpoint_from_flag, hook
from charms.reactive.flags import register_trigger

from charmhelpers.core.hookenv import config, status_set, relation_set, log, relation_ids
from charmhelpers.core.fstab import Fstab
from charmhelpers.core.host import mkdir, owner

register_trigger(when='config.changed', clear_flag='nova-compute-nfs.configured')

@when_not('nova-compute-nfs.installed')
def install_nova_compute_nfs_config():
    queue_install(['nfs-common'])
    status_set('maintenance', 'waiting for installation')

@when('apt.installed.nfs-common')
@when_not('nova-compute-nfs.installed')
def set_installed_message():
    set_flag('nova-compute-nfs.installed')
    status_set('maintenance', 'performing setup')

@when_not('nova-compute-nfs.configured')
@when('nova-compute-nfs.installed')
def configure():
    device = config('filesystem')
    mountpoint = config('mountpoint')
    filesystem_type = config('type')
    options = config('options')

    set_flag('nova-compute-nfs.configured')

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
    set_flag('nova-compute-nfs.mount')

@when('nova-compute-nfs.mount')
def mount():
    mountpoint = config('mountpoint')
    instances_path = config('instances-path') or mountpoint

    if not os.path.exists(mountpoint):
        try:
            mkdir(mountpoint, force=True)
        except PermissionError:
            status_set('blocked', 'insufficient permissions to create {}'.format(mountpoint))
            return
    
    try:
        subprocess.check_output(
            ['mount', '-a'], timeout=config('mount-timeout')
        )
        if mountpoint != instances_path and not os.path.exists(instances_path):
            try:
                mkdir(instances_path, owner='nova', group='nova')
            except PermissionError:
                status_set('blocked', 'unsufficient permissions to create {}'.format(instances_path))
                return
    except subprocess.TimeoutExpired:
        status_set('blocked', 'Timed out on mount. Check configuration.')
        return
    except subprocess.CalledProcessError:
        status_set('blocked', 'Mount error. Check configuraton.')
        return

    path_owner = owner(instances_path)
    if path_owner != ('nova', 'nova'):
        try:
            shutil.chown(mountpoint, 'nova', 'nova')
        except PermissionError:
            status_set('blocked', 'insufficient permissions to chown {} to nova'.format(mountpoint))
            return

    status_set('maintenance', 'filesystem mounted successfully, waiting for relation to nova-compute')
    set_flag('nova-compute-nfs.ready')

@hook('ephemeral-backend-relation-changed')
def nova_compute_changed():
    status_set('maintenance', 'nova-compute connected, but not yet configured')
    set_flag('nova-compute-nfs.connected')

@when('nova-compute-nfs.connected', 'nova-compute-nfs.ready')
def update_nova_config():
    status_set('maintenance', 'configuring nova-compute')
    ctx = {
        'nova': {
            '/etc/nova/nova.conf': {
                'sections': {
                    'DEFAULT': [
                        ('instances_path', config('instances-path') or config('mountpoint'))
                    ]
                }
            }
        }
    }
    for r in relation_ids('ephemeral-backend'):
        relation_set(r, subordinate_configuration=json.dumps(ctx))
    status_set('active', 'filesystem mounted and config applied')

if __name__ == '__main__':
    hooks.execute(sys.argv)

