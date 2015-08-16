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

"""
Handling of block device information and mapping

Module contains helper methods for dealing with block device information
"""

from nova import block_device
from nova.virt import configdrive
from nova.virt import driver

from hyperv.nova import constants
from hyperv.nova import vmutils
from hyperv.i18n import _


class BlockDeviceInfoManager(object):

    _VALID_BUS = {constants.VM_GEN_1: (constants.CTRL_TYPE_IDE,
                                       constants.CTRL_TYPE_SCSI),
                  constants.VM_GEN_2: (constants.CTRL_TYPE_SCSI,)
                 }

    _DEFAULT_BUS = constants.CTRL_TYPE_SCSI

    _TYPE_FOR_DISK_FORMAT = {'vhd': constants.DISK,
                             'iso': constants.DVD
                            }

    _SUPPORTED_BLOCK_DEVICE_TYPES = {'eph': 'disk',
                                     'volume': 'disk'}

    _DEFAULT_ROOT_DEVICE = '/dev/sda'

    def __init__(self):
        pass

    def _initialize_controller_slot_counter(self, instance):
        # we have 2 IDE controllers, for a total of 4 slots
        self.free_slots_by_device_type = {
            constants.CTRL_TYPE_IDE: constants.IDE_CONTROLLER_SLOTS_NUMBER * 2,
            constants.CTRL_TYPE_SCSI: constants.SCSI_CONTROLLER_SLOTS_NUMBER
            }
        if configdrive.required_by(instance):
            # reserve one slot for the config drive
            self.free_slots_by_device_type[constants.CTRL_TYPE_IDE] -= 1

    def validate_and_update_bdi(self, instance, image_meta, vm_gen,
                                block_device_info):
        self._initialize_controller_slot_counter(instance)
        self._check_and_update_ephemerals(vm_gen, block_device_info)
        self._check_and_update_volumes(vm_gen, block_device_info)

    def get_root_device(self, vm_gen, image_meta, block_device_info):

        # either booting from volume, or booting from image/iso
        root_disk = {}

        root_device = driver.block_device_info_get_root(block_device_info) or \
            self._DEFAULT_ROOT_DEVICE

        if self._is_boot_from_volume(block_device_info):
            root_volume = self._get_bdm(block_device_info, root_device)
            root_disk['type'] = constants.VOLUME
            root_disk['path'] = None
            root_disk['connection_info'] = root_volume['connection_info']
        else:
            root_disk['type'] = self._TYPE_FOR_DISK_FORMAT.get(
                image_meta['disk_format'])
            root_disk['path'] = None
            root_disk['connection_info'] = None

        root_disk['disk_bus'] = constants.CTRL_TYPE_IDE if \
            vm_gen == constants.VM_GEN_1 else constants.CTRL_TYPE_SCSI
        # check if there is a free slot for this device
        self._check_controller_slot_available(root_disk['disk_bus'])
        root_disk['boot_index'] = 0
        root_disk['mount_device'] = root_device

        return root_disk

    def _check_controller_slot_available(self, controller_type):
        if self.free_slots_by_device_type[controller_type] >= 1:
            self.free_slots_by_device_type[controller_type] -= 1
            return
        msg = _("There are no more free slots on controller %(ctrl_type)s"
                ) % {'ctrl_type': controller_type}
        raise vmutils.HyperVException(msg)

    def _is_boot_from_volume(self, block_device_info):
        if block_device_info:
            root_device = block_device_info.get('root_device_name')
            if not root_device:
                root_device = self._DEFAULT_ROOT_DEVICE

            return block_device.volume_in_mapping(root_device,
                                                  block_device_info)

    def _get_bdm(self, block_device_info, mount_device=None):
        for mapping in driver.block_device_info_get_mapping(block_device_info):
            if mapping['mount_device'] == mount_device:
                return mapping

    def _check_and_update_ephemerals(self, vm_gen, block_device_info):
        ephemerals = driver.block_device_info_get_ephemerals(block_device_info)
        for eph in ephemerals:
            device_type = eph.get('device_type')
            if not device_type:
                eph['device_type'] = 'disk'

            if device_type and device_type is not 'disk':
                msg = _("Hyper-V does not support disk type %(disk_type)s "
                        "for ephemerals.") % {'disk_type': device_type}
                raise vmutils.HyperVException(msg)

            disk_bus = eph.get('disk_bus')
            if not disk_bus:
                eph['disk_bus'] = self._DEFAULT_BUS
            if disk_bus and disk_bus not in self._VALID_BUS[vm_gen]:
                msg = _("Hyper-V does not support bus type %(disk_bus)s "
                        "for generation %(vm_gen)s instances"
                       ) % {'disk_bus': disk_bus,
                            'vm_gen': vm_gen}

                raise vmutils.HyperVException(msg)

            self._check_controller_slot_available(eph['disk_bus'])

            boot_index = eph.get('boot_index')
            eph['boot_index'] = boot_index

        self._sort_by_boot_order(ephemerals)

    def _check_and_update_volumes(self, vm_gen, block_device_info):
        volumes = driver.block_device_info_get_mapping(block_device_info)
        for vol in volumes:
            disk_bus = vol.get('disk_bus')
            if not disk_bus:
                vol['disk_bus'] = self._DEFAULT_BUS
            if disk_bus and disk_bus not in self._VALID_BUS[vm_gen]:
                msg = _("Hyper-V does not support bus type %(disk_bus)s "
                        "for generation %(vm_gen)s instances"
                       ) % {'disk_bus': disk_bus,
                            'vm_gen': vm_gen}
                raise vmutils.HyperVException(msg)
            self._check_controller_slot_available(vol['disk_bus'])

            device_type = vol.get('device_type')
            if not device_type:
                vol['device_type'] = 'disk'

            if device_type and device_type is not 'disk':
                msg = _("Hyper-V does not support disk type %(disk_type)s "
                        "for ephemerals.") % {'disk_type': device_type}
                raise vmutils.HyperVException(msg)

            boot_index = vol.get('boot_index')
            vol['boot_index'] = boot_index
        self._sort_by_boot_order(volumes)

    def _sort_by_boot_order(self, bd_list):
        # we sort the block devices by boot_index leaving the ones that don't
        # have a specified boot_index at the end
        bd_list.sort(key=lambda x: (x['boot_index'] is None, x['boot_index']))
