#  Copyright 2014 IBM Corp.
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

import os
import time

import ddt
import mock
from nova import exception
from six.moves import builtins

from hyperv.nova import constants
from hyperv.nova import pathutils
from hyperv.tests.unit import test_base


@ddt.ddt
class PathUtilsTestCase(test_base.HyperVBaseTestCase):
    """Unit tests for the Hyper-V PathUtils class."""

    def setUp(self):
        super(PathUtilsTestCase, self).setUp()
        self.fake_instance_dir = os.path.join('C:', 'fake_instance_dir')
        self.fake_instance_name = 'fake_instance_name'

        self._pathutils = pathutils.PathUtils()
        self._pathutils._smb_conn_attr = mock.MagicMock()
        self._pathutils._smbutils = mock.MagicMock()
        self._smbutils = self._pathutils._smbutils

    def _mock_lookup_configdrive_path(self, ext, rescue=False):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)

        def mock_exists(*args, **kwargs):
            path = args[0]
            return True if path[(path.rfind('.') + 1):] == ext else False
        self._pathutils.exists = mock_exists
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name, rescue)
        return configdrive_path

    def _test_lookup_configdrive_path(self, rescue=False):
        configdrive_name = 'configdrive'
        if rescue:
            configdrive_name += '-rescue'

        for format_ext in constants.DISK_FORMAT_MAP:
            configdrive_path = self._mock_lookup_configdrive_path(format_ext,
                                                                  rescue)
            expected_path = os.path.join(self.fake_instance_dir,
                                         configdrive_name + '.' + format_ext)
            self.assertEqual(expected_path, configdrive_path)

    def test_lookup_configdrive_path(self):
        self._test_lookup_configdrive_path()

    def test_lookup_rescue_configdrive_path(self):
        self._test_lookup_configdrive_path(rescue=True)

    def test_lookup_configdrive_path_non_exist(self):
        self._pathutils.get_instance_dir = mock.MagicMock(
            return_value=self.fake_instance_dir)
        self._pathutils.exists = mock.MagicMock(return_value=False)
        configdrive_path = self._pathutils.lookup_configdrive_path(
            self.fake_instance_name)
        self.assertIsNone(configdrive_path)

    def test_get_instances_sub_dir(self):

        class WindowsError(Exception):
            def __init__(self, winerror=None):
                self.winerror = winerror

        fake_dir_name = "fake_dir_name"
        fake_windows_error = WindowsError
        self._pathutils.check_create_dir = mock.MagicMock(
            side_effect=WindowsError(pathutils.ERROR_INVALID_NAME))
        with mock.patch.object(builtins, 'WindowsError',
                               fake_windows_error, create=True):
            self.assertRaises(exception.AdminRequired,
                              self._pathutils._get_instances_sub_dir,
                              fake_dir_name)

    def test_copy_vm_console_logs(self):
        fake_local_logs = [mock.sentinel.log_path,
                           mock.sentinel.archived_log_path]
        fake_remote_logs = [mock.sentinel.remote_log_path,
                            mock.sentinel.remote_archived_log_path]

        self._pathutils.exists = mock.Mock(return_value=True)
        self._pathutils.copy = mock.Mock()
        self._pathutils.get_vm_console_log_paths = mock.Mock(
            side_effect=[fake_local_logs, fake_remote_logs])

        self._pathutils.copy_vm_console_logs(mock.sentinel.instance_name,
                                            mock.sentinel.dest_host)

        self._pathutils.get_vm_console_log_paths.assert_has_calls(
            [mock.call(mock.sentinel.instance_name),
             mock.call(mock.sentinel.instance_name,
                       remote_server=mock.sentinel.dest_host)])
        self._pathutils.copy.assert_has_calls([
            mock.call(mock.sentinel.log_path,
                      mock.sentinel.remote_log_path),
            mock.call(mock.sentinel.archived_log_path,
                      mock.sentinel.remote_archived_log_path)])

    @mock.patch.object(pathutils.PathUtils, 'get_base_vhd_dir')
    @mock.patch.object(pathutils.PathUtils, 'exists')
    def _test_get_image_path(self, mock_exists, mock_get_base_vhd_dir,
                             found=True):
        fake_image_name = 'fake_image_name'
        if found:
            mock_exists.side_effect = [False, True]
        else:
            mock_exists.return_value = False
        mock_get_base_vhd_dir.return_value = 'fake_base_dir'

        res = self._pathutils.get_image_path(fake_image_name)

        mock_get_base_vhd_dir.assert_called_once_with()
        if found:
            self.assertEqual(
                res, os.path.join('fake_base_dir', 'fake_image_name.vhdx'))
        else:
            self.assertIsNone(res)

    def test_get_image_path(self):
        self._test_get_image_path()

    def test_get_image_path_not_found(self):
        self._test_get_image_path(found=False)

    @mock.patch('os.path.getmtime')
    @mock.patch.object(pathutils, 'time')
    def test_get_age_of_file(self, mock_time, mock_getmtime):
        mock_time.time.return_value = time.time()
        mock_getmtime.return_value = mock_time.time.return_value - 42

        actual_age = self._pathutils.get_age_of_file(mock.sentinel.filename)
        self.assertEqual(42, actual_age)
        mock_time.time.assert_called_once_with()
        mock_getmtime.assert_called_once_with(mock.sentinel.filename)

    @mock.patch('os.path.exists')
    @mock.patch('tempfile.NamedTemporaryFile')
    def test_check_dirs_shared_storage(self, mock_named_tempfile,
                                       mock_exists):
        fake_src_dir = 'fake_src_dir'
        fake_dest_dir = 'fake_dest_dir'

        mock_exists.return_value = True
        mock_tmpfile = mock_named_tempfile.return_value.__enter__.return_value
        mock_tmpfile.name = 'fake_tmp_fname'
        expected_src_tmp_path = os.path.join(fake_src_dir,
                                             mock_tmpfile.name)

        self._pathutils.check_dirs_shared_storage(
            fake_src_dir, fake_dest_dir)

        mock_named_tempfile.assert_called_once_with(dir=fake_dest_dir)
        mock_exists.assert_called_once_with(expected_src_tmp_path)

    @ddt.data({},
              {'local_share_path': None},
              {'is_same_dir': True},
              {'raised_exc': Exception})
    @ddt.unpack
    @mock.patch.object(pathutils.PathUtils, 'check_dirs_shared_storage')
    def test_get_loopback_share_path(
            self, mock_check_dirs_shared_storage,
            local_share_path=mock.sentinel.local_share_path,
            is_same_dir=False, raised_exc=None):
        self._smbutils.get_smb_share_path.return_value = local_share_path
        mock_check_dirs_shared_storage.side_effect = (
            raised_exc or [is_same_dir])

        share_address = r'\\1.2.3.4\fake_share'
        expected_path = (
            local_share_path
            if local_share_path and is_same_dir and not raised_exc
            else None)
        share_path = self._pathutils.get_loopback_share_path(share_address)

        self.assertEqual(expected_path, share_path)
        self._smbutils.get_smb_share_path.assert_called_once_with(
            'fake_share')

        if local_share_path:
            mock_check_dirs_shared_storage.assert_called_once_with(
                local_share_path, share_address)
        else:
            self.assertFalse(mock_check_dirs_shared_storage.called)

    @mock.patch.object(pathutils.PathUtils, 'check_dirs_shared_storage')
    @mock.patch.object(pathutils.PathUtils, 'get_instances_dir')
    def test_check_remote_instances_shared(self, mock_get_instances_dir,
                                           mock_check_dirs_shared_storage):
        mock_get_instances_dir.side_effect = [mock.sentinel.local_inst_dir,
                                              mock.sentinel.remote_inst_dir]

        shared_storage = self._pathutils.check_remote_instances_dir_shared(
            mock.sentinel.dest)

        self.assertEqual(mock_check_dirs_shared_storage.return_value,
                         shared_storage)
        mock_get_instances_dir.assert_has_calls(
            [mock.call(), mock.call(mock.sentinel.dest)])
        mock_check_dirs_shared_storage.assert_called_once_with(
            mock.sentinel.local_inst_dir, mock.sentinel.remote_inst_dir)
