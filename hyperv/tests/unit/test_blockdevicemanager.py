# Copyright (c) 2015 Cloudbase Solutions Srl
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

from nova.virt import driver
from nova.virt import configdrive

from hyperv.nova import block_device_manager
from hyperv.nova import constants
from hyperv.nova import vmutils
from hyperv.tests import fake_instance
from hyperv.tests.unit import test_base


class BlockDeviceManagerTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V BlockDeviceInfoManager class."""

    def setUp(self):
        super(BlockDeviceManagerTestCase, self).setUp()

        self._bdman = block_device_manager.BlockDeviceInfoManager()

    def test_validate_and_update_bdi(self):
        self._bdman._initialize_controller_slot_counter = mock.MagicMock()
        mock_init_ctrl_cntr = self._bdman._initialize_controller_slot_counter

        self._bdman._check_and_update_ephemerals = mock.MagicMock()
        self._bdman._check_and_update_volumes = mock.MagicMock()

        self._bdman.validate_and_update_bdi(mock.sentinel.FAKE_INSTANCE,
            mock.sentinel.IMAGE_META, mock.sentinel.VM_GEN,
            mock.sentinel.BLOCK_DEV_INFO)

        mock_init_ctrl_cntr.assert_called_once_with(
            mock.sentinel.FAKE_INSTANCE)
        self._bdman._check_and_update_ephemerals.assert_called_once_with(
            mock.sentinel.VM_GEN, mock.sentinel.BLOCK_DEV_INFO)
        self._bdman._check_and_update_volumes.assert_called_once_with(
            mock.sentinel.VM_GEN, mock.sentinel.BLOCK_DEV_INFO)

    @mock.patch('nova.virt.configdrive.required_by', return_value=True)
    def _test_check_controller_slot_available(self, mock_config_drive_req, 
        exception=False):

        self._bdman._initialize_controller_slot_counter(mock.sentinel.FAKE_VM)

        if exception:
            self._bdman.free_slots_by_device_type[constants.CTRL_TYPE_IDE] = 0
            self.assertRaises(vmutils.HyperVException,
                              self._bdman._check_controller_slot_available,
                              constants.CTRL_TYPE_IDE)
        else:
            self._bdman._check_controller_slot_available(
                constants.CTRL_TYPE_IDE)

            self.assertEquals(
                self._bdman.free_slots_by_device_type[constants.CTRL_TYPE_IDE],
                2)

    def test_check_controller_slot_available(self):
        self._test_check_controller_slot_available()

    def test_check_controller_slot_available_exception(self):
        self._test_check_controller_slot_available(exception=True)

    def test_is_boot_from_volume_true(self):
        vol = {'mount_device': self._bdman._DEFAULT_ROOT_DEVICE}
        block_device_info = {'block_device_mapping': [vol]}
        ret = self._bdman._is_boot_from_volume(block_device_info)

        self.assertTrue(ret)

    def test_is_boot_from_volume_false(self):
        block_device_info = {'block_device_mapping': []}
        ret = self._bdman._is_boot_from_volume(block_device_info)

        self.assertFalse(ret)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_controller_slot_available')
    def _test_check_and_update_ephemerals(self, mock_check_ctrl_slot,
        block_device_info, exception=False, vm_gen=constants.VM_GEN_1):

        if exception:
            self.assertRaises(vmutils.HyperVException,
                self._bdman._check_and_update_ephemerals, vm_gen,
                block_device_info)
        else:
            self._bdman._check_and_update_ephemerals(vm_gen, block_device_info)
            expected_calls = []
            for eph in block_device_info['ephemerals']:
                expected_calls.append(mock.call(eph['disk_bus']))
            mock_check_ctrl_slot.assert_has_calls(expected_calls)

    def test_check_and_update_ephemerals_with_defaults(self):
        eph = {'device_type': None,
               'disk_bus': None,
               'boot_index': None
              }
        bdi = {'ephemerals': [eph]}

        self._test_check_and_update_ephemerals(block_device_info=bdi)
        self.assertEquals(eph['device_type'], 'disk')
        self.assertEquals(eph['disk_bus'], self._bdman._DEFAULT_BUS)
        self.assertEquals(eph['boot_index'], None)

    def test_check_and_update_ephemerals(self):
        eph = {'device_type': 'disk',
               'disk_bus': 'IDE',
               'boot_index': 1
              }
        bdi = {'ephemerals': [eph]}

        self._test_check_and_update_ephemerals(block_device_info=bdi)

    def test_check_and_update_ephemerals_exception_device_type(self):
        eph = {'device_type': 'cdrom',
               'disk_bus': 'IDE',
              }
        bdi = {'ephemerals': [eph]}

        self._test_check_and_update_ephemerals(block_device_info=bdi,
            exception=True)

    def test_check_and_update_ephemerals_exception_disk_bus(self):
        eph = {'device_type': 'disk',
               'disk_bus': 'fake_bus',
              }
        bdi = {'ephemerals': [eph]}

        self._test_check_and_update_ephemerals(block_device_info=bdi,
            exception=True)

    @mock.patch.object(block_device_manager.BlockDeviceInfoManager,
                       '_check_controller_slot_available')
    def _test_check_and_update_volumes(self, mock_check_ctrl_slot,
        block_device_info, exception=False, vm_gen=constants.VM_GEN_1):

        if exception:
            self.assertRaises(vmutils.HyperVException,
                self._bdman._check_and_update_volumes, vm_gen,
                block_device_info)
        else:
            self._bdman._check_and_update_volumes(vm_gen, block_device_info)
            expected_calls = []
            for vol in block_device_info['block_device_mapping']:
                expected_calls.append(mock.call(vol['disk_bus']))
            mock_check_ctrl_slot.assert_has_calls(expected_calls)

    def test_check_and_update_volumes_defaults(self):
        vol = {'device_type': None,
               'disk_bus': None,
               'boot_index': None
              }
        bdi = {'block_device_mapping': [vol]}

        self._test_check_and_update_volumes(block_device_info=bdi)
        self.assertEquals(vol['device_type'], 'disk')
        self.assertEquals(vol['disk_bus'], self._bdman._DEFAULT_BUS)
        self.assertEquals(vol['boot_index'], None)

    def test_check_and_update_volumes(self):
        vol = {'device_type': 'disk',
               'disk_bus': 'IDE',
               'boot_index': 1
              }
        bdi = {'block_device_mapping': [vol]}

        self._test_check_and_update_volumes(block_device_info=bdi)

    def test_check_and_update_volumes_exception_device_type(self):
        vol = {'device_type': 'cdrom',
               'disk_bus': 'IDE',
              }
        bdi = {'block_device_mapping': [vol]}

        self._test_check_and_update_volumes(block_device_info=bdi,
            exception=True)

    def test_check_and_update_volumes_exception_disk_bus(self):
        vol = {'device_type': 'disk',
               'disk_bus': 'fake_bus',
              }
        bdi = {'block_device_mapping': [vol]}

        self._test_check_and_update_volumes(block_device_info=bdi,
            exception=True)

    def test_sort_by_boot_order(self):
        original = [{'boot_index': 2}, {'boot_index': None}, {'boot_index': 1}]
        expected = [original[2], original[0], original[1]]

        self._bdman._sort_by_boot_order(original)

        self.assertEquals(original, expected)
