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

import mock
import time

from nova.compute import power_state
from nova.compute import vm_states
from nova import objects
from os_win import exceptions as os_win_exc
from os_win.utils.compute import clusterutils
from os_win import utilsfactory

from hyperv.nova.cluster import clusterops
from hyperv.tests.unit import test_base


class ClusterOpsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V ClusterOps class."""

    _FAKE_INSTANCE_NAME = 'fake_instance_name'

    @mock.patch.object(utilsfactory, 'get_cluster_failover_monitor')
    @mock.patch.object(clusterutils.ClusterFailoverMonitor, 'get_node_name')
    @mock.patch.object(clusterops.ClusterOps,
                       '_start_failover_listener_daemon')
    @mock.patch.object(clusterops.ClusterOps, '_update_instance_map')
    def setUp(self, mock_update_instance_map, mock_start_listener,
              mock_get_node_name, mock_get_failover_mon):
        super(ClusterOpsTestCase, self).setUp()
        self.context = 'fake_context'
        self.fake_instance = mock.MagicMock()

        self._clusterops = clusterops.ClusterOps(mock.sentinel.virtapi,
                                                 cluster_monitor=True)
        self._clusterops._clustutils = mock.MagicMock()
        self._clusterops._failovermon = mock.MagicMock()
        self._clusterops._context = self.context
        self._clusterops._network_api = mock.MagicMock()

    def test_get_instance_host(self):
        self._clusterops.get_instance_host(self.fake_instance)
        self._clusterops._clustutils.get_vm_host.assert_called_once_with(
            self.fake_instance.name)

    def test_add_to_cluster(self):
        self._clusterops.add_to_cluster(self.fake_instance)
        mock_add_vm = self._clusterops._clustutils.add_vm_to_cluster
        mock_add_vm.assert_called_once_with(self.fake_instance.name)
        mock_add_to_map = self._clusterops._failovermon.add_to_cluster_map
        mock_add_to_map.assert_called_once_with(self.fake_instance.name)

    @mock.patch.object(clusterops, 'LOG')
    def test_add_to_cluster_exception(self, mock_log):
        mock_add_vm = self._clusterops._clustutils.add_vm_to_cluster
        mock_add_vm.side_effect = os_win_exc.HyperVClusterException
        self._clusterops.add_to_cluster(self.fake_instance)
        self.assertTrue(mock_log.exception.called)

    def test_remove_from_cluster(self):
        self._clusterops.remove_from_cluster(self.fake_instance)
        self._clusterops._clustutils.delete.assert_called_once_with(
            self.fake_instance.name)
        mock_clear = self._clusterops._failovermon.clear_from_cluster_map
        mock_clear.assert_called_once_with(self.fake_instance.name)

    @mock.patch.object(clusterops, 'LOG')
    def test_remove_from_cluster_exception(self, mock_log):
        mock_delete = self._clusterops._clustutils.delete
        mock_delete.side_effect = os_win_exc.HyperVClusterException
        self._clusterops.remove_from_cluster(self.fake_instance)
        self.assertTrue(mock_log.exception.called)

    def test_post_migration(self):
        self._clusterops.post_migration(self.fake_instance)

        mock_add_to_map = self._clusterops._failovermon.add_to_cluster_map
        mock_add_to_map.assert_called_once_with(self.fake_instance.name)
        self.assertEqual(
            self._clusterops._instance_map[self.fake_instance.name],
            self.fake_instance.id)

    def test_start_failover_listener_daemon_already_started(self):
        self._clusterops._daemon = mock.sentinel.daemon
        self._clusterops._start_failover_listener_daemon()
        self.assertEqual(mock.sentinel.daemon, self._clusterops._daemon)

    def test_start_failover_listener_daemon(self):
        self.flags(cluster_event_check_interval=0, group='hyperv_cluster')
        self._clusterops._failovermon.monitor.side_effect = (
            os_win_exc.HyperVClusterException)
        self._clusterops._start_failover_listener_daemon()

        # wait for the daemon to do something.
        time.sleep(0.5)
        self._clusterops._failovermon.monitor.assert_called_with(
            self._clusterops._failover_migrate)

    def test_failover_migrate_networks(self):
        fake_source = mock.MagicMock()
        fake_migration = {'source_compute': fake_source,
                          'dest_compute': self._clusterops._this_node}

        self._clusterops._failover_migrate_networks(self.fake_instance,
                                                    fake_source)
        mock_network_api = self._clusterops._network_api
        calls = [mock.call(self._clusterops._context, self.fake_instance,
                           self._clusterops._this_node),
                 mock.call(self._clusterops._context, self.fake_instance,
                           self._clusterops._this_node),
                 mock.call(self._clusterops._context, self.fake_instance,
                           self._clusterops._this_node),
                 mock.call(self._clusterops._context, self.fake_instance,
                           fake_source, teardown=True)]
        mock_network_api.setup_networks_on_host.assert_has_calls(calls)
        mock_network_api.migrate_instance_start.assert_called_once_with(
            self._clusterops._context, self.fake_instance, fake_migration)
        mock_network_api.migrate_instance_finish.assert_called_once_with(
            self._clusterops._context, self.fake_instance, fake_migration)

    @mock.patch.object(objects.Instance, 'get_by_id')
    def _test_get_instance_by_name(self, mock_get_by_id,
                                   get_vm_id_side_effect):
        self._clusterops._instance_map = mock.MagicMock()
        self._clusterops._instance_map.get.side_effect = get_vm_id_side_effect
        self._clusterops._update_instance_map = mock.MagicMock()
        mock_get_by_id.return_value = mock.sentinel.FAKE_INSTANCE

        ret = self._clusterops._get_instance_by_name(self._FAKE_INSTANCE_NAME)

        if not get_vm_id_side_effect[0]:
            self._clusterops._update_instance_map.assert_called_once_with()

        self.assertEqual(ret, mock.sentinel.FAKE_INSTANCE)

    def test_get_instance_by_name(self):
        self._test_get_instance_by_name(
            get_vm_id_side_effect=[mock.sentinel.VM_ID])

    def test_get_instance_by_name_update_map(self):
        self._test_get_instance_by_name(
            get_vm_id_side_effect=[None, mock.sentinel.VM_ID])

    @mock.patch.object(clusterops.block_device, 'DriverVolumeBlockDevice')
    @mock.patch.object(clusterops.objects.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_get_instance_block_device_mappings(self, mock_get_by_uuid,
                                                mock_DriverVBD):
        mock_get_by_uuid.return_value = [mock.sentinel.bdm]
        mock_instance = mock.MagicMock()

        bdms = self._clusterops._get_instance_block_device_mappings(
            mock_instance)

        self.assertEqual([mock_DriverVBD.return_value], bdms)
        mock_get_by_uuid.assert_called_once_with(self._clusterops._context,
                                                 mock_instance.id)
        mock_DriverVBD.assert_called_once_with(mock.sentinel.bdm)

    @mock.patch.object(clusterops.objects.InstanceList, 'get_by_filters')
    def test_update_instance_map(self, mock_get_by_filters):
        mock_instance = mock.MagicMock(id=mock.sentinel.id)
        mock_instance.configure_mock(name=mock.sentinel.name)
        mock_get_by_filters.return_value = [mock_instance]

        self._clusterops._update_instance_map()

        expected_attrs = ['id', 'uuid', 'name', 'project_id', 'host',
                          'hostname', 'node', 'availability_zone']
        mock_get_by_filters.assert_called_once_with(
            self._clusterops._context, {'deleted': False},
            expected_attrs=expected_attrs)
        self.assertEqual(mock.sentinel.id,
                         self._clusterops._instance_map[mock.sentinel.name])

    def test_nova_failover_server(self):
        mock_instance = mock.MagicMock(vm_state=vm_states.ERROR,
                                       power_state=power_state.NOSTATE)

        self._clusterops._nova_failover_server(mock_instance,
                                               mock.sentinel.host)

        self.assertEqual(vm_states.ACTIVE, mock_instance.vm_state)
        self.assertEqual(power_state.RUNNING, mock_instance.power_state)
        self.assertEqual(mock.sentinel.host, mock_instance.host)
        self.assertEqual(mock.sentinel.host, mock_instance.node)
        mock_instance.save.assert_called_once_with(expected_task_state=[None])
