# Copyright 2016 Cloudbase Solutions Srl
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Management class for Cluster VM operations."""

from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import network
from nova import objects
from nova.virt import block_device
from os_win import exceptions as os_win_exc
from os_win import utilsfactory
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall

from hyperv.i18n import _LI, _LE
from hyperv.nova import serialconsoleops
from hyperv.nova import vmops
from hyperv.nova import volumeops

LOG = logging.getLogger(__name__)

hyperv_cluster_opts = [
    cfg.IntOpt('cluster_event_check_interval',
               default=2),
]

CONF = cfg.CONF
CONF.register_opts(hyperv_cluster_opts, 'hyperv_cluster')


class ClusterOps(object):

    def __init__(self, host='.'):
        self._clustutils = utilsfactory.get_clusterutils()
        self._clustutils.check_cluster_state()
        self._serial_console_ops = serialconsoleops.SerialConsoleOps()

        self._daemon = None
        self._instance_map = {}

        self._failovermon = utilsfactory.get_cluster_failover_monitor()
        self._this_node = self._failovermon.get_node_name()

        self._volops = volumeops.VolumeOps()

        self._context = context.get_admin_context()
        self._network_api = network.API()
        self._vmops = vmops.VMOps()

        self._start_failover_listener_daemon()

        self._update_instance_map()

    def get_instance_host(self, instance):
        return self._clustutils.get_vm_host(instance.name)

    def add_to_cluster(self, instance):
        try:
            self._clustutils.add_vm_to_cluster(instance.name)
            self._failovermon.add_to_cluster_map(instance.name)
            self._instance_map[instance.name] = instance.id
        except os_win_exc.HyperVClusterException:
            LOG.exception(_LE('Adding instance to cluster failed'),
                          instance=instance)

    def remove_from_cluster(self, instance):
        try:
            self._clustutils.delete(instance.name)
            self._failovermon.clear_from_cluster_map(instance.name)
        except os_win_exc.HyperVClusterException:
            LOG.exception(_LE('Removing instance to cluster failed'),
                          instance=instance)

    def post_migration(self, instance):
        # skip detecting false positve failover events due to
        # cold / live migration.
        self._failovermon.add_to_cluster_map(instance.name)
        self._instance_map[instance.name] = instance.id

    def _start_failover_listener_daemon(self):
        """Start the daemon failover listener."""
        if self._daemon:
            return

        def _looper():
            try:
                self._failovermon.monitor(self._failover_migrate)
            except Exception:
                LOG.exception(_LE('Failover observation / migration.'))

        self._daemon = loopingcall.FixedIntervalLoopingCall(_looper)

        self._daemon.start(
            interval=CONF.hyperv_cluster.cluster_event_check_interval)

    def _failover_migrate(self, instance_name, new_host):
        """This method will check if the generated event is a legitimate
        failover to this node. If it is, it will proceed to prepare the
        failovered VM if necessary and update the owner of the compute vm in
        nova and ports in neutron.
        """
        LOG.info(_LI('Checking Failover instance %(instance)s to %(host)s'),
                 {'instance': instance_name,
                  'host': new_host})
        old_host = self._failovermon.get_from_cluster_map(instance_name)
        LOG.info(_LI('Instance %(instance)s known to be on host: %(host)s'),
                 {'instance': instance_name,
                  'host': new_host})

        instance = self._get_instance_by_name(instance_name)
        nw_info = self._network_api.get_instance_nw_info(self._context,
                                                         instance)

        if not instance:
            # Some instances on the hypervisor may not be tracked by nova
            LOG.debug('Instance %s does not exist in nova. Skipping.',
                      instance_name)
            return

        if instance.task_state == task_states.MIGRATING:
            # In case of live migration triggered by the user, we get the
            # event that the instance changed host but we do not want
            # to treat it as a failover.
            LOG.debug('Instance %s is live migrating.', instance_name)
            return

        if old_host and old_host.upper() == new_host.upper():
            LOG.debug('Instance %s host did not change.', instance_name)
            return
        elif old_host and old_host.upper() == self._this_node.upper():
            LOG.debug('Actions at source node.')
            self._vmops.unplug_vifs(instance, nw_info)
            self._serial_console_ops.stop_console_handler(instance_name)

        elif new_host.upper() != self._this_node.upper():
            LOG.debug('Instance %s did not failover to this node.',
                      instance_name)
            return

        LOG.info(_LI('Failovering %(instance)s to %(host)s'),
                 {'instance': instance_name,
                  'host': new_host})

        self._nova_failover_server(instance, new_host)
        self._failover_migrate_networks(instance, old_host)
        self._vmops.post_start_vifs(instance, nw_info)
        self._serial_console_ops.start_console_handler(instance_name)

    def _failover_migrate_networks(self, instance, source):
        """This is called after a VM failovered to this node.
        This will change the owner of the neutron ports to this node.
        """
        migration = {'source_compute': source,
                     'dest_compute': self._this_node, }

        self._network_api.setup_networks_on_host(
            self._context, instance, self._this_node)
        self._network_api.migrate_instance_start(
            self._context, instance, migration)
        self._network_api.setup_networks_on_host(
            self._context, instance, self._this_node)
        self._network_api.migrate_instance_finish(
            self._context, instance, migration)
        self._network_api.setup_networks_on_host(
            self._context, instance, self._this_node)
        self._network_api.setup_networks_on_host(
            self._context, instance, source, teardown=True)

    def _get_instance_by_name(self, instance_name):
        vm_id = self._instance_map.get(instance_name, None)
        if not vm_id:
            self._update_instance_map()
            vm_id = self._instance_map.get(instance_name, None)

        if not vm_id:
            return

        return objects.Instance.get_by_id(self._context, vm_id)

    def _get_instance_block_device_mappings(self, instance):
        """Transform block devices to the driver block_device format."""
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self._context, instance.id)
        return [block_device.DriverVolumeBlockDevice(bdm) for bdm in bdms]

    def _update_instance_map(self):
        expected_attrs = ['id', 'uuid', 'name', 'project_id', 'host',
                          'hostname', 'node', 'availability_zone']

        for server in objects.InstanceList.get_by_filters(
                self._context, {'deleted': False},
                expected_attrs=expected_attrs):
            self._instance_map[server.name] = server.id

    def _nova_failover_server(self, instance, new_host):
        if instance.vm_state == vm_states.ERROR:
        # Sometimes during a failover nova can set the instance state
        # to error depending on how much time the failover takes.
            instance.vm_state = vm_states.ACTIVE
        if instance.power_state == power_state.NOSTATE:
            instance.power_state = power_state.RUNNING

        instance.host = new_host
        instance.node = new_host
        instance.save(expected_task_state=[None])
