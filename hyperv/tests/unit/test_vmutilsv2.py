#  Copyright 2014 Cloudbase Solutions Srl
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

from hyperv.nova import constants
from hyperv.nova import vmutils
from hyperv.nova import vmutilsv2
from hyperv.tests.unit import test_vmutils


class VMUtilsV2TestCase(test_vmutils.VMUtilsTestCase):
    """Unit tests for the Hyper-V VMUtilsV2 class."""

    _DEFINE_SYSTEM = 'DefineSystem'
    _DESTROY_SYSTEM = 'DestroySystem'
    _DESTROY_SNAPSHOT = 'DestroySnapshot'

    _ADD_RESOURCE = 'AddResourceSettings'
    _REMOVE_RESOURCE = 'RemoveResourceSettings'
    _SETTING_TYPE = 'VirtualSystemType'
    _VM_GEN = constants.VM_GEN_2

    _VIRTUAL_SYSTEM_TYPE_REALIZED = 'Microsoft:Hyper-V:System:Realized'
    _FAKE_MONITOR_COUNT = 1

    def setUp(self):
        super(VMUtilsV2TestCase, self).setUp()
        self._vmutils = vmutilsv2.VMUtilsV2()
        self._vmutils._conn = mock.MagicMock()

    def test_create_vm(self):
        super(VMUtilsV2TestCase, self).test_create_vm()
        mock_vssd = self._vmutils._conn.Msvm_VirtualSystemSettingData.new()
        self.assertEqual(self._vmutils._VIRTUAL_SYSTEM_SUBTYPE_GEN2,
                         mock_vssd.VirtualSystemSubType)
        self.assertFalse(mock_vssd.SecureBootEnabled)

    def test_modify_virt_resource(self):
        mock_svc = self._vmutils._conn.Msvm_VirtualSystemManagementService()[0]
        mock_svc.ModifyResourceSettings.return_value = (self._FAKE_JOB_PATH,
                                                        mock.MagicMock(),
                                                        self._FAKE_RET_VAL)
        mock_res_setting_data = mock.MagicMock()
        mock_res_setting_data.GetText_.return_value = self._FAKE_RES_DATA

        self._vmutils._modify_virt_resource(mock_res_setting_data,
                                            self._FAKE_VM_PATH)

        mock_svc.ModifyResourceSettings.assert_called_with(
            ResourceSettings=[self._FAKE_RES_DATA])

    @mock.patch.object(vmutilsv2, 'wmi', create=True)
    @mock.patch.object(vmutilsv2.VMUtilsV2, 'check_ret_val')
    def test_take_vm_snapshot(self, mock_check_ret_val, mock_wmi):
        self._lookup_vm()

        mock_svc = self._get_snapshot_service()
        mock_svc.CreateSnapshot.return_value = (self._FAKE_JOB_PATH,
                                                mock.MagicMock(),
                                                self._FAKE_RET_VAL)

        self._vmutils.take_vm_snapshot(self._FAKE_VM_NAME)

        mock_svc.CreateSnapshot.assert_called_with(
            AffectedSystem=self._FAKE_VM_PATH,
            SnapshotType=self._vmutils._SNAPSHOT_FULL)

        mock_check_ret_val.assert_called_once_with(self._FAKE_RET_VAL,
                                                   self._FAKE_JOB_PATH)

    @mock.patch.object(vmutilsv2.VMUtilsV2, '_add_virt_resource')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_get_new_setting_data')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_get_nic_data_by_name')
    def test_set_nic_connection(self, mock_get_nic_data, mock_get_new_sd,
                                mock_add_virt_res):
        self._lookup_vm()
        fake_eth_port = mock_get_new_sd.return_value

        self._vmutils.set_nic_connection(self._FAKE_VM_NAME, None, None)
        mock_add_virt_res.assert_called_with(fake_eth_port, self._FAKE_VM_PATH)

    @mock.patch('hyperv.nova.vmutils.VMUtils._get_vm_disks')
    def test_enable_vm_metrics_collection(self, mock_get_vm_disks):
        self._lookup_vm()
        mock_svc = self._vmutils._conn.Msvm_MetricService()[0]

        metric_def = mock.MagicMock()
        mock_disk = mock.MagicMock()
        mock_disk.path_.return_value = self._FAKE_RES_PATH
        mock_get_vm_disks.return_value = ([mock_disk], [mock_disk])

        fake_metric_def_paths = ['fake_0', 'fake_0', None]
        fake_metric_resource_paths = [self._FAKE_VM_PATH,
                                      self._FAKE_VM_PATH,
                                      self._FAKE_RES_PATH]

        metric_def.path_.side_effect = fake_metric_def_paths
        self._vmutils._conn.CIM_BaseMetricDefinition.return_value = [
            metric_def]

        self._vmutils.enable_vm_metrics_collection(self._FAKE_VM_NAME)

        calls = [mock.call(Name=def_name)
                 for def_name in [self._vmutils._METRIC_AGGR_CPU_AVG,
                                  self._vmutils._METRIC_AGGR_MEMORY_AVG]]
        self._vmutils._conn.CIM_BaseMetricDefinition.assert_has_calls(calls)

        calls = []
        for i in range(len(fake_metric_def_paths)):
            calls.append(mock.call(
                Subject=fake_metric_resource_paths[i],
                Definition=fake_metric_def_paths[i],
                MetricCollectionEnabled=self._vmutils._METRIC_ENABLED))

        mock_svc.ControlMetrics.assert_has_calls(calls, any_order=True)

    def _get_snapshot_service(self):
        return self._vmutils._conn.Msvm_VirtualSystemSnapshotService()[0]

    def _assert_add_resources(self, mock_svc):
        getattr(mock_svc, self._ADD_RESOURCE).assert_called_with(
            self._FAKE_VM_PATH, [self._FAKE_RES_DATA])

    def _assert_remove_resources(self, mock_svc):
        getattr(mock_svc, self._REMOVE_RESOURCE).assert_called_with(
            [self._FAKE_RES_PATH])

    def test_list_instance_notes(self):
        vs = mock.MagicMock()
        attrs = {'ElementName': 'fake_name',
                 'Notes': ['4f54fb69-d3a2-45b7-bb9b-b6e6b3d893b3']}
        vs.configure_mock(**attrs)
        vs2 = mock.MagicMock(ElementName='fake_name2', Notes=None)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.return_value = [vs,
                                                                          vs2]
        response = self._vmutils.list_instance_notes()

        self.assertEqual([(attrs['ElementName'], attrs['Notes'])], response)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.assert_called_with(
            ['ElementName', 'Notes'],
            VirtualSystemType=self._vmutils._VIRTUAL_SYSTEM_TYPE_REALIZED)

    def _get_fake_instance_notes(self):
        return [self._FAKE_VM_UUID]

    @mock.patch('hyperv.nova.vmutilsv2.VMUtilsV2.check_ret_val')
    @mock.patch('hyperv.nova.vmutilsv2.VMUtilsV2._get_wmi_obj')
    def _test_create_vm_obj(self, mock_get_wmi_obj, mock_check_ret_val,
                            vm_path, dynamic_memory_ratio=1.0):
        mock_vs_man_svc = mock.MagicMock()
        mock_vs_data = mock.MagicMock()
        mock_job = mock.MagicMock()
        fake_job_path = 'fake job path'
        fake_ret_val = 'fake return value'
        fake_vm_name = 'fake_vm_name'
        _conn = self._vmutils._conn.Msvm_VirtualSystemSettingData

        mock_check_ret_val.return_value = mock_job
        _conn.new.return_value = mock_vs_data
        mock_vs_man_svc.DefineSystem.return_value = (fake_job_path,
                                                     vm_path,
                                                     fake_ret_val)
        mock_job.associators.return_value = ['fake vm path']

        response = self._vmutils._create_vm_obj(
            vs_man_svc=mock_vs_man_svc,
            vm_name=fake_vm_name,
            vm_gen='fake vm gen',
            notes='fake notes',
            dynamic_memory_ratio=dynamic_memory_ratio,
            instance_path=mock.sentinel.instance_path)

        if not vm_path:
            mock_job.associators.assert_called_once_with(
                self._vmutils._AFFECTED_JOB_ELEMENT_CLASS)

        _conn.new.assert_called_once_with()
        self.assertEqual(mock_vs_data.ElementName, fake_vm_name)
        mock_vs_man_svc.DefineSystem.assert_called_once_with(
            ResourceSettings=[], ReferenceConfiguration=None,
            SystemSettings=mock_vs_data.GetText_(1))
        mock_check_ret_val.assert_called_once_with(fake_ret_val, fake_job_path)

        if dynamic_memory_ratio > 1:
            self.assertFalse(mock_vs_data.VirtualNumaEnabled)

        mock_get_wmi_obj.assert_called_with('fake vm path')

        self.assertEqual(mock_vs_data.Notes, 'fake notes')
        self.assertEqual(mock.sentinel.instance_path,
                         mock_vs_data.ConfigurationDataRoot)
        self.assertEqual(mock.sentinel.instance_path, mock_vs_data.LogDataRoot)
        self.assertEqual(mock.sentinel.instance_path,
                         mock_vs_data.SnapshotDataRoot)
        self.assertEqual(mock.sentinel.instance_path,
                         mock_vs_data.SuspendDataRoot)
        self.assertEqual(mock.sentinel.instance_path,
                         mock_vs_data.SwapFileDataRoot)
        self.assertEqual(response, mock_get_wmi_obj())

    def test_create_vm_obj(self):
        self._test_create_vm_obj(vm_path='fake vm path')

    def test_create_vm_obj_no_vm_path(self):
        self._test_create_vm_obj(vm_path=None)

    def test_create_vm_obj_dynamic_memory(self):
        self._test_create_vm_obj(vm_path=None, dynamic_memory_ratio=1.1)

    def test_list_instances(self):
        vs = mock.MagicMock()
        attrs = {'ElementName': 'fake_name'}
        vs.configure_mock(**attrs)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.return_value = [vs]
        response = self._vmutils.list_instances()

        self.assertEqual([(attrs['ElementName'])], response)
        self._vmutils._conn.Msvm_VirtualSystemSettingData.assert_called_with(
            ['ElementName'],
            VirtualSystemType=self._vmutils._VIRTUAL_SYSTEM_TYPE_REALIZED)

    def test_get_attached_disks(self):
        mock_scsi_ctrl_path = mock.MagicMock()
        expected_query = ("SELECT * FROM %(class_name)s "
                          "WHERE (ResourceSubType='%(res_sub_type)s' OR "
                          "ResourceSubType='%(res_sub_type_virt)s' OR "
                          "ResourceSubType='%(res_sub_type_dvd)s') AND "
                          "Parent = '%(parent)s'" %
                          {"class_name":
                           self._vmutils._RESOURCE_ALLOC_SETTING_DATA_CLASS,
                           "res_sub_type":
                           self._vmutils._PHYS_DISK_RES_SUB_TYPE,
                           "res_sub_type_virt":
                           self._vmutils._DISK_DRIVE_RES_SUB_TYPE,
                           "res_sub_type_dvd":
                           self._vmutils._DVD_DRIVE_RES_SUB_TYPE,
                           "parent": mock_scsi_ctrl_path.replace("'", "''")})
        expected_disks = self._vmutils._conn.query.return_value

        ret_disks = self._vmutils.get_attached_disks(mock_scsi_ctrl_path)

        self._vmutils._conn.query.assert_called_once_with(expected_query)
        self.assertEqual(expected_disks, ret_disks)

    def test_get_vm_dvd_disk_paths(self):
        mock_vm = self._lookup_vm()
        mock_sasd1 = mock.MagicMock(
            ResourceSubType=self._vmutils._DVD_DISK_RES_SUB_TYPE,
            HostResource=[mock.sentinel.FAKE_DVD_PATH1])
        mock_settings = mock.MagicMock()
        mock_settings.associators.return_value = [mock_sasd1]
        mock_vm.associators.return_value = [mock_settings]

        ret_val = self._vmutils.get_vm_dvd_disk_paths(self._FAKE_VM_NAME)
        self.assertEqual(mock.sentinel.FAKE_DVD_PATH1, ret_val[0])

    @mock.patch.object(vmutilsv2.VMUtilsV2, '_get_vm_setting_data')
    def _test_get_vm_gen(self, mock_get_vm_setting_data, vm_gen):
        mock_vm = self._lookup_vm()
        vm_gen_string = "Microsoft:Hyper-V:SubType:" + str(vm_gen)
        mock_vssd = mock.MagicMock(VirtualSystemSubType=vm_gen_string)
        mock_get_vm_setting_data.return_value = mock_vssd

        ret = self._vmutils.get_vm_gen(mock_vm)
        self.assertEqual(vm_gen, ret)

    def test_get_vm_generation_gen1(self):
        self._test_get_vm_gen(vm_gen=constants.VM_GEN_1)

    def test_get_vm_generation_gen2(self):
        self._test_get_vm_gen(vm_gen=constants.VM_GEN_2)

    @mock.patch.object(vmutilsv2.VMUtilsV2, '_get_new_resource_setting_data')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_add_virt_resource')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_modify_virt_resource')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_remove_virt_resource')
    def test_enable_remotefx_video_adapter(self,
                                           mock_remove_virt_resource,
                                           mock_modify_virt_resource,
                                           mock_add_virt_res,
                                           mock_new_res_setting_data):
        mock_vm = self._lookup_vm()

        mock_r1 = mock.MagicMock()
        mock_r1.ResourceSubType = self._vmutils._SYNTH_DISP_CTRL_RES_SUB_TYPE

        mock_r2 = mock.MagicMock()
        mock_r2.ResourceSubType = self._vmutils._S3_DISP_CTRL_RES_SUB_TYPE

        mock_vm.associators()[0].associators.return_value = [mock_r1, mock_r2]

        self._vmutils._conn.Msvm_Synth3dVideoPool()[0].IsGpuCapable = True
        self._vmutils._conn.Msvm_Synth3dVideoPool()[0].IsSlatCapable = True
        self._vmutils._conn.Msvm_Synth3dVideoPool()[0].DirectXVersion = '11.1'

        mock_synth_3d_disp_ctrl_res = mock.MagicMock(
            MaximumMonitors=self._FAKE_MONITOR_COUNT,
            MaximumScreenResolution=0)
        mock_new_res_setting_data.return_value = mock_synth_3d_disp_ctrl_res

        self._vmutils.enable_remotefx_video_adapter(
            mock.sentinel.fake_vm_name,
            self._FAKE_MONITOR_COUNT,
            constants.REMOTEFX_MAX_RES_1024x768)

        mock_remove_virt_resource.assert_called_once_with(mock_r1,
                                                          mock_vm.path_())
        mock_new_res_setting_data.assert_called_once_with(
            self._vmutils._SYNTH_3D_DISP_CTRL_RES_SUB_TYPE,
            self._vmutils._SYNTH_3D_DISP_ALLOCATION_SETTING_DATA_CLASS)
        mock_add_virt_res.assert_called_once_with(mock_synth_3d_disp_ctrl_res,
                                                  mock_vm.path_())

        mock_modify_virt_resource.assert_called_once_with(mock_r2,
                                                          mock_vm.path_())
        self.assertEqual(self._vmutils._DISP_CTRL_ADDRESS_DX_11,
                         mock_r2.Address)

    def test_enable_remotefx_video_adapter_already_configured(self):
        mock_vm = self._lookup_vm()

        mock_r = mock.MagicMock()
        mock_r.ResourceSubType = self._vmutils._SYNTH_3D_DISP_CTRL_RES_SUB_TYPE

        mock_vm.associators()[0].associators.return_value = [mock_r]

        self.assertRaises(vmutils.HyperVException,
                          self._vmutils.enable_remotefx_video_adapter,
                          mock.sentinel.fake_vm_name, self._FAKE_MONITOR_COUNT,
                          constants.REMOTEFX_MAX_RES_1024x768)

    def test_enable_remotefx_video_adapter_no_gpu(self):
        self._lookup_vm()

        self._vmutils._conn.Msvm_Synth3dVideoPool()[0].IsGpuCapable = False

        self.assertRaises(vmutils.HyperVException,
                          self._vmutils.enable_remotefx_video_adapter,
                          mock.sentinel.fake_vm_name, self._FAKE_MONITOR_COUNT,
                          constants.REMOTEFX_MAX_RES_1024x768)

    def test_enable_remotefx_video_adapter_no_slat(self):
        self._lookup_vm()

        self._vmutils._conn.Msvm_Synth3dVideoPool()[0].IsSlatCapable = False

        self.assertRaises(vmutils.HyperVException,
                          self._vmutils.enable_remotefx_video_adapter,
                          mock.sentinel.fake_vm_name, self._FAKE_MONITOR_COUNT,
                          constants.REMOTEFX_MAX_RES_1024x768)

    @mock.patch.object(vmutilsv2.VMUtilsV2,
                       '_get_mounted_disk_resource_from_path')
    @mock.patch.object(vmutilsv2.VMUtilsV2, '_modify_virt_resource')
    def _test_set_disk_qos_specs(self, mock_modify_virt_resource,
                                 mock_get_disk_resource, qos_available=True):
        mock_disk = mock.Mock()
        if not qos_available:
            type(mock_disk).IOPSLimit = mock.PropertyMock(
                side_effect=AttributeError)
        mock_get_disk_resource.return_value = mock_disk

        self._vmutils.set_disk_qos_specs(mock.sentinel.vm_name,
                                         mock.sentinel.disk_path,
                                         mock.sentinel.min_iops,
                                         mock.sentinel.max_iops)

        mock_get_disk_resource.assert_called_once_with(
            mock.sentinel.disk_path, is_physical=False)

        if qos_available:
            self.assertEqual(mock.sentinel.max_iops, mock_disk.IOPSLimit)
            self.assertEqual(mock.sentinel.min_iops, mock_disk.IOPSReservation)
            mock_modify_virt_resource.assert_called_once_with(mock_disk,
                                                              None)
        else:
            self.assertFalse(mock_modify_virt_resource.called)

    def test_set_disk_qos_specs(self):
        self._test_set_disk_qos_specs()

    def test_set_disk_qos_specs_unsupported_feature(self):
        self._test_set_disk_qos_specs(qos_available=False)
