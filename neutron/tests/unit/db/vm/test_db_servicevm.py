# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 Intel Corporation.
# Copyright 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
# All Rights Reserved.
#
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
#
# @author: Isaku Yamahata, Intel Corporation.

import contextlib
import eventlet
import functools
import os
import time
import uuid

from oslo.config import cfg
import webob.exc

from neutron.api import extensions as api_extensions
from neutron.common import config
from neutron import context
from neutron import extensions
from neutron.extensions import servicevm
from neutron.openstack.common import importutils
from neutron.plugins.common import constants
from neutron.tests.unit import test_db_plugin


DB_CORE_PLUGIN_KLASS = 'neutron.db.db_base_plugin_v2.NeutronDbPluginV2'
DB_SERVICEVM_PLUGIN_KLASS = "neutron.vm.plugin.ServiceVMPlugin"
#DB_SERVICEVM_PLUGIN_KLASS = "neutron.db.vm.vm_db.ServiceResourcePluginDb"
ETCDIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'etc'))

EXTENSIONS_PATH = ':'.join(extensions.__path__)


_uuid = lambda: str(uuid.uuid4())


class ServiceVMPluginDbTestCaseMixin(object):
    resource_prefix_map = dict(
        (k.replace('_', '-'), constants.COMMON_PREFIXES[constants.SERVICEVM])
        for k in servicevm.RESOURCE_ATTRIBUTE_MAP.keys()
    )

    _DEVICE_TEMPLATES = 'device_templates'
    _DEVICE_TEMPLATE = 'device_template'
    _SERVICE_INSTANCES = 'service_instances'
    _SERVICE_INSTANCE = 'service_instance'
    _DEVICES = 'devices'
    _DEVICE = 'device'

    _PATH_DEVICE_TEMPLATES = 'device-templates'
    _PATH_SERVICE_INSTANCES = 'service-instances'
    _PATH_DEVICES = 'devices'

    _DEVICE_TEMPLATE_DICT_DEFAULT = {
        'name': 'template0',
        'description': 'description0',
        'service_types': [{'service_type': 'SERVICE_TYPE0'},
                          {'service_type': 'SERVICE_TYPE1'}],
        'device_driver': 'noop',
        'mgmt_driver': 'noop',
        'attributes': {
            'key0': 'value0',
            'key1': 'value1',
        },
    }
    _DEVICE_KWARGS_DEFAULT = {
        'hd-key0': 'hd-value0',
        'hd-key1': 'hd-value1'
    }
    _DEVICE_DICT_DEFAULT = {
        'mgmt_address': 'no-address',
        'kwargs': _DEVICE_KWARGS_DEFAULT,
        'services': [],
        'service_context': [],
    }
    _SERVICE_INSTANCE_KWARGS_DEFAULT = {
        'si-key0': 'value0',
        'si-key1': 'value1',
    }
    _SERVICE_INSTANCE_DICT_DEFAULT = {
        'mgmt_address': 'no-address',
        'mgmt_driver': 'noop',
        'name': 'service_instance0',
        'service_context': [],
        'kwargs': _SERVICE_INSTANCE_KWARGS_DEFAULT,
    }

    def _create(self, path, data, fmt, expected_res_status):
        req = self.new_create_request(path, data, fmt=fmt)
        res = req.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(res.status_int, expected_res_status)
        return res

    def _wait_active(self, fmt, path, obj_id):
        start = time.time()
        while True:
            if time.time() - start > 1:
                raise RuntimeError('timeout to delete')
            eventlet.sleep(0)
            req = self.new_show_request(path, obj_id, fmt=fmt)
            res = req.get_response(self.ext_api)
            if res.status_int != webob.exc.HTTPOk.code:
                raise RuntimeError(res)
            res = self.deserialize(self.fmt, res)
            _key, data = res.popitem()
            status = data.get('status', 'ACTIVE')
            if status == 'ACTIVE':
                break
            if status in ['PENDING_CREATE', 'PENDING_UPDATE']:
                continue
            raise RuntimeError(res)

    def _wait_delete(self, fmt, path, obj_id):
        start = time.time()
        while True:
            if time.time() - start > 1:
                raise RuntimeError('timeout to delete')
            eventlet.sleep(0)
            req = self.new_show_request(path, obj_id, fmt=fmt)
            res = req.get_response(self.ext_api)
            if res.status_int == webob.exc.HTTPNotFound.code:
                break
            if res.status_int != webob.exc.HTTPOk.code:
                raise RuntimeError(res)
            _key, data = res.popitem()
            status = data.get('status', 'ACTIVE')
            if status != 'PENDING_DELETE':
                raise RuntimeError(res)

    def _yield_result(self, fmt, res, no_delete, path, key):
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int)
        try:
            result = self.deserialize(fmt, res)
            yield result
        finally:
            if not no_delete:
                obj_id = result[key]['id']
                self._wait_active(fmt, path, obj_id)
                self._delete(path, obj_id)
                self._wait_delete(fmt, path, obj_id)

    def _create_device_template(
            self, fmt=None, name='template0', description='desription0',
            service_types=None,
            device_driver='noop', mgmt_driver='noop', attributes=None,
            expected_res_status=None):
        fmt = fmt or self.fmt
        if service_types is None:
            service_types = [{'service_type': 'SERVICE_TYPE0'},
                             {'service_type': 'SERVICE_TYPE1'}]
        if attributes is None:
            attributes = {
                'key0': 'value0',
                'key1': 'value1',
            }
        data = {
            self._DEVICE_TEMPLATE: {
                'tenant_id': self._tenant_id,
                'name': name,
                'description': description,
                'service_types': service_types,
                'device_driver': device_driver,
                'mgmt_driver': mgmt_driver,
                'attributes': attributes,
            }
        }
        return self._create(self._PATH_DEVICE_TEMPLATES, data, fmt,
                            expected_res_status)

    @contextlib.contextmanager
    def device_template(
            self, fmt=None, name='template0', description='description0',
            service_types=None,
            device_driver='noop', mgmt_driver='noop', attributes=None,
            no_delete=False):
        fmt = fmt or self.fmt
        res = self._create_device_template(
            fmt, name, description, service_types, device_driver,
            mgmt_driver, attributes)
        for result in self._yield_result(fmt, res, no_delete,
                                         self._PATH_DEVICE_TEMPLATES,
                                         self._DEVICE_TEMPLATE):
            yield result

    def _create_device(self, fmt, template_id, kwargs, service_contexts,
                       expected_res_status=None):
        data = {
            self._DEVICE: {
                'tenant_id': self._tenant_id,
                'template_id': template_id,
                'kwargs': kwargs,
                'service_contexts': service_contexts,
            }
        }
        return self._create(self._PATH_DEVICES, data, fmt,
                            expected_res_status)

    @contextlib.contextmanager
    def device(self, fmt=None, template=None, kwargs=None,
               service_contexts=None, no_delete=False):
        fmt = fmt or self.fmt
        if kwargs is None:
            kwargs = self._DEVICE_KWARGS_DEFAULT
        if service_contexts is None:
            service_contexts = []

        with test_db_plugin.optional_ctx(
                template, self.device_template) as tmp_template:
            template_id = tmp_template[self._DEVICE_TEMPLATE]['id']
            res = self._create_device(fmt, template_id, kwargs,
                                      service_contexts)
            for result in self._yield_result(fmt, res, no_delete,
                                             self._PATH_DEVICES,
                                             self._DEVICE):
                yield result

    def _create_service_instance_user(
            self, fmt, name, service_type_id, service_table_id, mgmt_driver,
            mgmt_address, service_contexts, device_id, kwargs,
            expected_res_status=None):
        data = {
            self._SERVICE_INSTANCE: {
                'tenant_id': self._tenant_id,
                'name': name,
                'service_type_id': service_type_id,
                'service_table_id': service_table_id,
                'mgmt_driver': mgmt_driver,
                'mgmt_address': mgmt_address,
                'service_contexts': service_contexts,
                'devices': [device_id],
                'kwargs': kwargs,
            }
        }
        return self._create(self._PATH_SERVICE_INSTANCES, data, fmt,
                            expected_res_status)

    @contextlib.contextmanager
    def service_instance_user(
            self, fmt=None, name='service_instance0', service_type_id=None,
            service_table_id=None, mgmt_driver='noop',
            mgmt_address='no-address', service_contexts=None, device=None,
            kwargs=None, no_delete=False):
        fmt = fmt or self.fmt
        if service_table_id is None:
            service_table_id = _uuid()
        if service_contexts is None:
            service_contexts = []
        if kwargs is None:
            kwargs = self._SERVICE_INSTANCE_KWARGS_DEFAULT

        def yield_none():
            yield None
        create_device_template = (self.device_template
                                  if service_type_id is None else yield_none)
        with create_device_template() as tmp_template:
            if service_type_id is None:
                service_type_id = tmp_template
                service_type = tmp_template[
                    self._DEVICE_TEMPLATE]['service_types'][0]
                service_type_id = service_type['id']
            with test_db_plugin.optional_ctx(
                    device, self.device) as tmp_device:
                res = self._create_service_instance_user(
                    fmt, name, service_type_id, service_table_id, mgmt_driver,
                    mgmt_address, service_contexts,
                    tmp_device['device']['id'], kwargs)
                for result in self._yield_result(fmt, res, no_delete,
                                                 self._PATH_SERVICE_INSTANCES,
                                                 self._SERVICE_INSTANCE):
                    yield result

    def _create_service_instance(self, fmt, device_id, service_instance_param,
                                 managed_by_user):
        service_instance = self.plugin._create_service_instance(
            context.get_admin_context(), device_id, service_instance_param,
            managed_by_user)
        return {self._SERVICE_INSTANCE: service_instance}

    @contextlib.contextmanager
    def service_instance(self, fmt=None, template=None, device=None,
                         params=None, no_delete=False):
        fmt = fmt or self.fmt
        default_params = {
            'name': 'service_instance0',
            'service_table_id': _uuid(),
            'mgmt_driver': 'noop',
            'mgmt_address': 'no-address',
            'service_contexts': [],
            'kwargs': {'key0': 'value0', 'key1': 'value1'},
        }
        params = params or {}
        for key, value in default_params.iteritems():
            params.setdefault(key, value)

        with test_db_plugin.optional_ctx(
                template, self.device_template) as tmp_template:
            self_device = functools.partial(self.device, template=tmp_template)
            with test_db_plugin.optional_ctx(
                    device, self_device) as tmp_device:
                if 'service_type_id' not in params:
                    service_type = tmp_template[
                        self._DEVICE_TEMPLATE]['service_types'][0]
                    params['service_type_id'] = service_type['id']
                service_instance = self._create_service_instance(
                    fmt, tmp_device[self._DEVICE]['id'], params, False)
                try:
                    yield service_instance
                finally:
                    if not no_delete:
                        obj_id = service_instance[
                            self._SERVICE_INSTANCE]['id']
                        self._wait_active(
                            fmt, self._PATH_SERVICE_INSTANCES, obj_id)
                        self.plugin._delete_service_instance(
                            context.get_admin_context(), obj_id, False)
                        self._wait_delete(
                            fmt, self._PATH_SERVICE_INSTANCES, obj_id)


class ServiceVMPluginDbTestCase(ServiceVMPluginDbTestCaseMixin,
                                test_db_plugin.NeutronDbPluginV2TestCase):
    def setUp(self):
        # load the class first such that the related config options
        # are loaded
        plugin_cls = importutils.import_class(DB_SERVICEVM_PLUGIN_KLASS)

        cfg.CONF.set_override('device_driver', ['noop'], 'servicevm')
        cfg.CONF.set_override('mgmt_driver', ['noop'], 'servicevm')
        service_plugins = {'servicevm_plugin': DB_SERVICEVM_PLUGIN_KLASS}
        super(ServiceVMPluginDbTestCase, self).setUp(
            service_plugins=service_plugins)

        self.plugin = plugin_cls()
        ext_mgr = api_extensions.PluginAwareExtensionManager(
            EXTENSIONS_PATH, {constants.SERVICEVM: self.plugin})
        app = config.load_paste_app('extensions_test_app')
        self.ext_api = api_extensions.ExtensionMiddleware(app, ext_mgr=ext_mgr)

        self.addCleanup(cfg.CONF.reset)

    def _assertEqualDict(self, keys, expected, observed):
        for key in keys:
            self.assertEqual(expected[key], observed[key])

    def _assertEqualListDict(self, keys, expected, observed):
        class HashableDict(dict):
            def __hash__(self):
                return hash(tuple(sorted(self.items())))

        expected_set = set(
            HashableDict((key, value) for key, value in d.iteritems()
                         if key in keys)
            for d in expected)
        observed_set = set(
            HashableDict((key, value) for key, value in d.iteritems()
                         if key in keys)
            for d in observed)
        self.assertEqual(expected_set, observed_set)

    def _assertEqualTemplate(self, expected, observed):
        self.assertIn('id', observed)
        self._assertEqualDict(
            ('tenant_id', 'name', 'description',
             'device_driver', 'mgmt_driver', 'attributes'),
            expected, observed)
        self._assertEqualListDict(
            ('service_type', ),
            expected['service_types'], observed['service_types'])

    def _assertEqualDevice(self, expected, observed):
        for key in ('id', 'mgmt_address'):
            self.assertIn(key, observed)
        self.assertIn(observed['status'], ['ACTIVE', 'PENDING_CREATE'])
        self._assertEqualDict(
            ('tenant_id', 'template_id', 'kwargs'), expected, observed)
        self.assertEqual(set(expected['services']), set(observed['services']))

    def _assertEqualServiceInstance(self, expected, observed):
        for key in ('id', 'devices', 'service_table_id',
                    'service_type_id',):
            self.assertIn(key, observed)
        self._assertEqualDict(
            ('tenant_id', 'name', 'mgmt_driver', 'mgmt_address', ),
            expected, observed)

    # hosting device template
    def test_create_device_template(self):
        expected = self._DEVICE_TEMPLATE_DICT_DEFAULT.copy()
        expected['tenant_id'] = self._tenant_id
        with self.device_template() as template:
            self._assertEqualTemplate(expected,
                                      template[self._DEVICE_TEMPLATE])

    def test_delete_device_template(self):
        with self.device_template(no_delete=True) as template:
            req = self.new_delete_request(
                self._PATH_DEVICE_TEMPLATES,
                template[self._DEVICE_TEMPLATE]['id'], fmt=self.fmt)
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_update_device_template(self):
        with self.device_template() as template:
            data = {
                self._DEVICE_TEMPLATE: {
                    'name': 'new-name',
                    'description': 'new-description',
                },
            }
            req = self.new_update_request(
                self._PATH_DEVICE_TEMPLATES,
                data, template[self._DEVICE_TEMPLATE]['id'], fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))

            self._assertEqualDict(
                ('name', 'description'),
                data[self._DEVICE_TEMPLATE], res[self._DEVICE_TEMPLATE])

    def test_update_device_template_fail(self):
        with self.device_template() as template:
            keys = (('id', _uuid()),
                    ('tenant_id', _uuid()),
                    ('service_types', [{'service_type': 'NEW_SERVICE'}]),
                    ('mgmt_driver', 'new_mgmt_driver'),
                    ('device_driver', 'new_driver'),
                    ('attributes', {'key0': 'new_value0'}),
                    ('attributes', {'new_key': 'new_value'}),)
            for key, value in keys:
                data = {self._DEVICE_TEMPLATE: {key: value}}
                req = self.new_update_request(
                    self._PATH_DEVICE_TEMPLATES, data,
                    template[self._DEVICE_TEMPLATE]['id'], fmt=self.fmt)
                res = req.get_response(self.ext_api)
                self.assertEqual(webob.exc.HTTPBadRequest.code, res.status_int)

    def test_show_device_template(self):
        expected = self._DEVICE_TEMPLATE_DICT_DEFAULT.copy()
        expected['tenant_id'] = self._tenant_id
        with self.device_template() as template:
            req = self.new_show_request(
                self._PATH_DEVICE_TEMPLATES,
                template[self._DEVICE_TEMPLATE]['id'], fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            self._assertEqualTemplate(expected, res[self._DEVICE_TEMPLATE])

    def test_list_device_templates(self):
        expected = self._DEVICE_TEMPLATE_DICT_DEFAULT.copy()
        expected['tenant_id'] = self._tenant_id
        with self.device_template():
            req = self.new_list_request(self._PATH_DEVICE_TEMPLATES,
                                        fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            device_tempaltes = res[self._DEVICE_TEMPLATES]
            self.assertEqual(len(device_tempaltes), 1)
            self._assertEqualTemplate(expected, device_tempaltes[0])

    # hosting device
    def test_create_device(self):
        expected = self._DEVICE_DICT_DEFAULT.copy()
        with self.device_template() as template:
            expected['template_id'] = template[self._DEVICE_TEMPLATE]['id']
            expected['tenant_id'] = self._tenant_id
            with self.device(template=template) as device:
                self._assertEqualDevice(expected, device[self._DEVICE])

    def test_delete_device(self):
        with self.device_template() as template:
            with self.device(template=template, no_delete=True) as device:
                req = self.new_delete_request(
                    self._PATH_DEVICES,
                    device[self._DEVICE]['id'], fmt=self.fmt)
                res = req.get_response(self.ext_api)
                self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_show_device(self):
        expected = self._DEVICE_DICT_DEFAULT.copy()
        with self.device_template() as template:
            expected['template_id'] = template[
                self._DEVICE_TEMPLATE]['id']
            expected['tenant_id'] = self._tenant_id
            with self.device(template=template) as device:
                req = self.new_show_request(
                    self._PATH_DEVICES,
                    device[self._DEVICE]['id'], fmt=self.fmt)
                res = self.deserialize(self.fmt,
                                       req.get_response(self.ext_api))
                self._assertEqualDevice(expected, res[self._DEVICE])

    def test_list_devices(self):
        expected = self._DEVICE_DICT_DEFAULT.copy()
        with self.device_template() as template:
            expected['template_id'] = template[self._DEVICE_TEMPLATE]['id']
            expected['tenant_id'] = self._tenant_id
            with self.device(template=template):
                req = self.new_list_request(self._PATH_DEVICES, fmt=self.fmt)
                res = req.get_response(self.ext_api)
                res = self.deserialize(self.fmt, res)
                devices = res[self._DEVICES]
                self.assertEqual(len(devices), 1)
                self._assertEqualDevice(expected, devices[0])

    def test_update_device(self):
        with self.device_template() as template:
            with self.device(template=template) as device:
                data = {self._DEVICE:
                        {'kwargs': {'new-key0': 'new-value0',
                                    'new-key1': 'new-value1'}}}
                req = self.new_update_request(
                    self._PATH_DEVICES, data,
                    device[self._DEVICE]['id'], fmt=self.fmt)
                res = req.get_response(self.ext_api)
                self.assertEqual(webob.exc.HTTPOk.code, res.status_int)

    def test_update_device_fail(self):
        with self.device_template() as template:
            with self.device(template=template) as device:
                keys = (('id', _uuid()),
                        ('tenant_id', _uuid()),
                        ('template_id', _uuid()),
                        ('instance_id', _uuid()),
                        ('mgmt_address', 'new-address'),
                        ('service_contexts', []),
                        ('services', 'new-service'),
                        ('status', 'ACTIVE'),)
                for key, value in keys:
                    data = {self._DEVICE: {key: value}}
                    req = self.new_update_request(
                        self._PATH_DEVICES, data,
                        device[self._DEVICE]['id'], fmt=self.fmt)
                    res = req.get_response(self.ext_api)
                    self.assertEqual(webob.exc.HTTPBadRequest.code,
                                     res.status_int)

    # logical service instance
    def test_create_service_instance_user(self):
        expected = self._SERVICE_INSTANCE_DICT_DEFAULT.copy()
        with self.service_instance_user() as service_instance:
            expected['tenant_id'] = self._tenant_id
            self._assertEqualServiceInstance(
                expected, service_instance[self._SERVICE_INSTANCE])

    def test_delete_service_instance_user(self):
        with self.service_instance_user(no_delete=True) as service_instance:
            req = self.new_delete_request(
                self._PATH_SERVICE_INSTANCES,
                service_instance[self._SERVICE_INSTANCE]['id'], fmt=self.fmt)
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

    def test_create_service_instance(self):
        expected = self._SERVICE_INSTANCE_DICT_DEFAULT.copy()
        with self.service_instance() as service_instance:
            expected['tenant_id'] = self._tenant_id
            self._assertEqualServiceInstance(
                expected, service_instance[self._SERVICE_INSTANCE])

    def test_create_service_instance_fail(self):
        with self.device() as device:
            obj_id = device[self._DEVICE]['id']
            self._wait_active(self.fmt, self._PATH_DEVICES, obj_id)
            data = {
                self._SERVICE_INSTANCE: {
                    'tenant_id': self._tenant_id,
                    'devices': [obj_id],
                }
            }
            req = self.new_create_request(
                self._PATH_SERVICE_INSTANCES, data, fmt=self.fmt)
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPBadRequest.code, res.status_int)

    def test_delete_service_instance_fail(self):
        with self.service_instance() as service_instance:
            obj_id = service_instance[self._SERVICE_INSTANCE]['id']
            self._wait_active(self.fmt, self._PATH_SERVICE_INSTANCES, obj_id)
            req = self.new_delete_request(
                self._PATH_SERVICE_INSTANCES, obj_id, fmt=self.fmt)
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPConflict.code, res.status_int)

    def test_show_service_instance(self):
        expected = self._SERVICE_INSTANCE_DICT_DEFAULT.copy()
        expected['tenant_id'] = self._tenant_id
        with self.service_instance() as service_instance:
            req = self.new_show_request(
                self._PATH_SERVICE_INSTANCES,
                service_instance[self._SERVICE_INSTANCE]['id'], fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            self._assertEqualServiceInstance(expected,
                                             res[self._SERVICE_INSTANCE])

    def test_list_service_instances(self):
        expected = self._SERVICE_INSTANCE_DICT_DEFAULT.copy()
        expected['tenant_id'] = self._tenant_id
        with self.service_instance():
            req = self.new_list_request(self._PATH_SERVICE_INSTANCES,
                                        fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            service_instances = res[self._SERVICE_INSTANCES]
            self.assertEqual(len(service_instances), 1)
            self._assertEqualServiceInstance(expected, service_instances[0])

    def test_update_service_instance_fail(self):
        with self.service_instance() as service_instance:
            obj_id = service_instance[
                self._SERVICE_INSTANCE]['id']
            self._wait_active(self.fmt, self._PATH_SERVICE_INSTANCES,
                              obj_id)
            data = {
                self._SERVICE_INSTANCE: {
                    'kwargs': {}
                }
            }
            req = self.new_update_request(self._PATH_SERVICE_INSTANCES,
                                          data, obj_id, fmt=self.fmt)
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPOk.code, res.status_int)


class ServiceVMPluginDbTestCaseXML(ServiceVMPluginDbTestCase):
    fmt = 'xml'
