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
import uuid

import mock
from oslo.config import cfg

from neutron.common import exceptions
from neutron import context
from neutron.extensions import loadbalancer
from neutron import manager
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants
from neutron.tests.unit.db.loadbalancer import test_db_loadbalancer


LOG = logging.getLogger(__name__)
HOSTING_DEVICE_PROVIDER = (
    'LOADBALANCER:hosting_device:neutron.services.loadbalancer.drivers.'
    'hosting_device.plugin_driver.HostingDevicePluginDriver:default')
PROVIDER = 'hosting_device'
_uuid = lambda: str(uuid.uuid4())
_network_id = _uuid()


class FakeHostingDevicePlugin(object):
    def __init__(self):
        self._devices = set()
        self._service_table_ids = set()

    def subnet_id_to_network_id(self, context, subnet_id):
        if test_db_loadbalancer._subnet_id == subnet_id:
            return _network_id

        core_plugin = manager.NeutronManager.get_plugin()
        subnet = core_plugin.get_subnet(context, subnet_id)
        return subnet['network_id']

    def create_device_sync(
            self, context, template_id, kwargs, service_context):
        device_id = _uuid()
        self._devices.add(device_id)
        return {'id': device_id}

    def _create_service_instance(
            self, context, device_id, service_instance_param, bool_param):
        service_table_id = service_instance_param['service_table_id']
        self._service_table_ids.add(service_table_id)

    def create_service_instance_by_type(
            self, context, device, vip_name, service_type, service_table_id):
        self._service_table_ids.add(service_table_id)

    def _update_service_table_instance(
            self, context, service_table_id, kwargs, callback, errorback):
        if service_table_id not in self._service_table_ids:
            raise exceptions.NotFound()
        callback()

    def _delete_service_table_instance(
            self, context, service_table_id, kwargs,
            callback, errorback):
        if service_table_id not in self._service_table_ids:
            raise exceptions.NotFound()
        self._service_table_ids.remove(service_table_id)
        callback()


def _fake_schedule(plugin, context,
                   service_type, service_instance_id, name, service_context):
    device_id = _uuid()
    service_type_id = _uuid()
    service_instance_param = {
        'name': name,
        'service_table_id': service_instance_id,
        'service_type': service_type,
        'service_type_id': service_type_id,
    }
    plugin._create_service_instance(
        context, device_id, service_instance_param, False)
    return True


class TestLoadBalancerPluginBase(
    test_db_loadbalancer.LoadBalancerPluginDbTestCase):

    def setUp(self):
        super(TestLoadBalancerPluginBase, self).setUp(
            lbaas_provider=HOSTING_DEVICE_PROVIDER)

        loaded_plugins = manager.NeutronManager().get_service_plugins()
        self.plugin_instance = loaded_plugins[constants.LOADBALANCER]

        fake_plugin = FakeHostingDevicePlugin()
        self.mock_device_plugin = mock.Mock(wraps=fake_plugin)
        loaded_plugins[constants.SERVICEVM] = self.mock_device_plugin

        self.mock_schedule_p = mock.patch(
            cfg.CONF.loadbalancer_hosting_device_scheduler_driver +
            '.schedule')
        self.mock_schedule = self.mock_schedule_p.start()
        self.mock_schedule.side_effect = _fake_schedule


# class TestLoadBalancerPlugin0(test_db_loadbalancer.TestLoadBalancer,
#                               TestLoadBalancerPluginBase):
#     def test_driver_call_create_pool_health_monitor(self):
#         self.skipTest("n/a test")


class TestLoadBalancerPlugin(TestLoadBalancerPluginBase):
    _MEMBER_ADDRESS = '192.168.1.100'

    def _vip_data(self, subnet_id, pool_id):
        return {
            'name': 'vip1',
            'subnet_id': subnet_id,
            'pool_id': pool_id,
            'description': '',
            'protocol_port': 80,
            'protocol': 'HTTP',
            'connection_limit': -1,
            'admin_state_up': True,
            'status': constants.PENDING_CREATE,
            'tenant_id': self._tenant_id,
            'session_persistence': '',
        }

    def _expected_vip(self, vip_data, vip):
        return {
            'id': vip['id'],
            'address': vip['address'],
            'port_id': vip['port_id'],
            'status_description': vip['status_description'],

            'status': vip_data['status'],
            'protocol': vip_data['protocol'],
            'protocol_port': vip_data['protocol_port'],
            'name': vip_data['name'],
            'admin_state_up': vip_data['admin_state_up'],
            'subnet_id': vip_data['subnet_id'],
            'connection_limit': vip_data['connection_limit'],
            'pool_id': vip_data['pool_id'],

            'description': '',
            'tenant_id': self._tenant_id,
            'session_persistence': None,
        }

    def _pool_data(self, subnet_id):
        return {
            'name': 'testpool',
            'description': 'a test pool',
            'tenant_id': self._tenant_id,
            'subnet_id': subnet_id,
            'protocol': 'HTTP',
            'vip_id': None,
            'admin_state_up': True,
            'lb_method': 'ROUND_ROBIN',
            'status': constants.PENDING_CREATE,
            'status_description': '',
            'members': [],
            'health_monitors': [],
            'health_monitors_status': None,
            'provider': PROVIDER,
        }

    def _expected_pool(self, pool):
        key_list = (
            'id', 'name', 'description', 'tenant_id', 'subnet_id',
            'protocol', 'vip_id', 'admin_state_up', 'lb_method', 'status')
        expected_pool = dict((key, pool[key]) for key in key_list)
        const_part = {
            'status_description': None,
            'members': [],
            'health_monitors': [],
            'health_monitors_status': [],
            'provider': PROVIDER}
        expected_pool.update(const_part)
        return expected_pool

    def _expected_member(self, member_id, pool_id, vip_protocol_port):
        return {
            'id': member_id,
            'admin_state_up': True,
            'status': constants.PENDING_CREATE,
            'status_description': None,
            'weight': 1,
            'address': self._MEMBER_ADDRESS,
            'tenant_id': self._tenant_id,
            'protocol_port': vip_protocol_port,
            'pool_id': pool_id}

    def _expected_health_monitor(self,
                                 health_monitor_id, pool_id, pool_status):
        return {
            'id': health_monitor_id,
            'admin_state_up': True,
            'tenant_id': self._tenant_id,
            'delay': 30,
            'max_retries': 3,
            'timeout': 10,
            'pools': [{'status': pool_status,
                       'status_description': None,
                       'pool_id': pool_id}],
            'type': 'TCP'}

    def setUp(self):
        super(TestLoadBalancerPlugin, self).setUp()
        self._ctxt = context.get_admin_context()

    def test_vip(self):
        mock_dp = self.mock_device_plugin
        ctxt = self._ctxt
        with contextlib.nested(
            self.subnet(),
            self.pool(provider=PROVIDER)
        ) as (subnet, pool):
            vip_data = self._vip_data(subnet['subnet']['id'],
                                      pool['pool']['id'])
            vip = self.plugin_instance.create_vip(ctxt, {'vip': vip_data})
            expected_vip_base = self._expected_vip(vip_data, vip)

            mock_dp._create_service_instance.assert_called_once_with(
                ctxt, mock.ANY,
                {'service_table_id': vip['id'],
                 'service_type': 'LOADBALANCER',
                 'service_type_id': mock.ANY,
                 'name': vip['name']},
                False)
            expected_vip = expected_vip_base.copy()
            mock_dp._update_service_table_instance.assert_called_once_with(
                ctxt, vip['id'],
                {'action': 'create_vip', 'kwargs': {'vip': expected_vip}},
                mock.ANY, mock.ANY)

            new_vip = self.plugin_instance.get_vip(self._ctxt, vip['id'])
            self.assertEqual(new_vip['status'], constants.ACTIVE)

            mock_dp.reset_mock()
            vip_data['status'] = constants.PENDING_UPDATE
            self.plugin_instance.update_vip(ctxt, vip['id'], {'vip': vip_data})
            expected_vip = expected_vip_base.copy()
            expected_vip['status'] = constants.PENDING_UPDATE
            expected_old_vip = expected_vip_base.copy()
            expected_old_vip['status'] = constants.ACTIVE
            mock_dp._update_service_table_instance.assert_called_once_with(
                ctxt, vip['id'],
                {'action': 'update_vip',
                 'kwargs': {'vip': expected_vip, 'old_vip': expected_old_vip}},
                mock.ANY, mock.ANY)
            updated_vip = self.plugin_instance.get_vip(ctxt, vip['id'])
            self.assertEqual(updated_vip['status'], constants.ACTIVE)

            mock_dp.reset_mock()
            self.plugin_instance.delete_vip(ctxt, vip['id'])
            expected_vip = expected_vip_base.copy()
            expected_vip['status'] = constants.PENDING_DELETE
            mock_dp._delete_service_table_instance.assert_called_once_with(
                ctxt, vip['id'],
                {'action': 'delete_vip', 'kwargs': {'vip': expected_vip}},
                mock.ANY, mock.ANY)

    def test_pool(self):
        mock_dp = self.mock_device_plugin
        ctxt = self._ctxt
        with self.subnet() as subnet:
            with self.vip(subnet=subnet, no_delete=True) as vip:
                vip = vip['vip']
                vip_id = vip['id']
                expected_vip_base = self._expected_vip(vip, vip)

                mock_dp.reset_mock()
                pool_data = self._pool_data(subnet['subnet']['id'])
                pool = self.plugin_instance.create_pool(
                    context.get_admin_context(), {'pool': pool_data})
                expected_pool_base = self._expected_pool(pool)
                self.assertFalse(mock_dp._update_service_table_instance.called)
                pool_id = pool['id']

                mock_dp.reset_mock()
                new_vip = self.plugin_instance.update_vip(
                    ctxt, vip_id, {'vip': {'pool_id': pool_id}})
                expected_old_vip = expected_vip_base.copy()
                expected_old_vip['status'] = constants.ACTIVE
                expected_vip = expected_vip_base.copy()
                expected_vip['pool_id'] = pool_id
                expected_vip['status'] = constants.PENDING_UPDATE
                self.assertEqual(new_vip, expected_vip)
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'update_vip',
                     'kwargs': {'vip': expected_vip,
                                'old_vip': expected_old_vip}},
                    mock.ANY, mock.ANY)

                updated_pool = self.plugin_instance.get_pool(ctxt, pool_id)
                self.assertEqual(updated_pool['vip_id'], vip_id)

                mock_dp.reset_mock()
                pool_data = {}
                pool = self.plugin_instance.update_pool(
                    ctxt, pool_id, {'pool': pool_data})
                expected_old_pool = expected_pool_base.copy()
                expected_old_pool['vip_id'] = vip_id
                expected_old_pool['status'] = constants.ACTIVE
                expected_pool = expected_pool_base.copy()
                expected_pool['vip_id'] = vip_id
                expected_pool['status'] = constants.PENDING_UPDATE
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'update_pool',
                     'kwargs': {'old_pool': expected_old_pool,
                                'pool': expected_pool}
                     },
                    mock.ANY, mock.ANY)
                self.assertRaises(loadbalancer.PoolInUse,
                                  self.plugin_instance.delete_pool,
                                  ctxt, pool_id)

                mock_dp.reset_mock()
                self.plugin_instance.delete_vip(ctxt, vip_id)
                expected_vip = expected_vip_base.copy()
                expected_vip['status'] = constants.PENDING_DELETE
                expected_vip['pool_id'] = pool_id
                mock_dp._delete_service_table_instance.assert_called_once_with(
                    ctxt, vip['id'],
                    {'action': 'delete_vip', 'kwargs': {'vip': expected_vip}},
                    mock.ANY, mock.ANY)

                mock_dp.reset_mock()
                self.plugin_instance.delete_pool(ctxt, pool_id)
                self.assertFalse(mock_dp._delete_service_table_instance.called)

    # def test_pool_without_vip(self):
    #     mock_dp = self.mock_device_plugin
    #     ctxt = self._ctxt
    #     with self.subnet() as subnet:
    #         pool_data = self._pool_data(subnet['subnet']['id'])
    #         pool = self.plugin_instance.create_pool(ctxt,
    #                                                 {'pool': pool_data})
    #         mock_dp._update_service_table_instance.assert_has_calls([])

    #         mock_dp.reset_mock()
    #         pool_update = pool_data.copy()
    #         pool_update['id'] = pool['id']
    #         del pool_update['provider']
    #         pool = self.plugin_instance.update_pool(ctxt, pool['id'],
    #                                                 {'pool': pool_update})
    #         mock_dp._update_service_table_instance.assert_has_calls([])

    #         mock_dp.reset_mock()
    #         pool = self.plugin_instance.delete_pool(ctxt, pool['id'])
    #         mock_dp._update_service_table_instance.assert_has_calls([])

    def test_member(self):
        mock_dp = self.mock_device_plugin
        ctxt = self._ctxt
        with contextlib.nested(
                self.subnet(), self.pool(provider=PROVIDER)) as (subnet, pool):
            with self.vip(subnet=subnet, pool=pool) as vip:
                pool = pool['pool']
                pool_id = pool['id']
                vip = vip['vip']
                vip_id = vip['id']
                vip_protocol_port = vip['protocol_port']

                mock_dp.reset_mock()
                member_data = {
                    'address': self._MEMBER_ADDRESS,
                    'protocol_port': vip['protocol_port'],
                    'admin_state_up': True,
                    'tenant_id': self._tenant_id,
                    'weight': 1,
                    'pool_id': pool_id
                }
                member = self.plugin_instance.create_member(
                    ctxt, {'member': member_data})
                member_id = member['id']
                expected_member = self._expected_member(
                    member_id, pool_id, vip_protocol_port)
                (mock_dp._update_service_table_instance.
                 assert_called_once_with(
                     ctxt, vip_id,
                     {'action': 'create_member',
                      'kwargs': {'member': expected_member}},
                     mock.ANY, mock.ANY))

                mock_dp.reset_mock()
                member['status'] = constants.PENDING_UPDATE
                updated_member = self.plugin_instance.update_member(
                    ctxt, member_id, {'member': member})
                self.assertEqual(updated_member['status'],
                                 constants.PENDING_UPDATE)
                expected_member = self._expected_member(
                    member_id, pool_id, vip_protocol_port)
                expected_member['status'] = constants.PENDING_UPDATE
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'update_member',
                     'kwargs': {'member': expected_member}},
                    mock.ANY, mock.ANY)

                mock_dp.reset_mock()
                self.plugin_instance.delete_member(self._ctxt, member_id)
                expected_member = self._expected_member(
                    member_id, pool_id, vip_protocol_port)
                expected_member['status'] = constants.PENDING_DELETE
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'delete_member',
                     'kwargs': {'member': expected_member}},
                    mock.ANY, mock.ANY)

    def test_update_member_without_vip(self):
        mock_dp = self.mock_device_plugin
        with contextlib.nested(
                self.subnet(), self.pool(provider=PROVIDER)) as (subnet, pool):
            with self.member(pool_id=pool['pool']['id']) as member:
                mock_dp.reset_mock()
                member['member']['status'] = constants.PENDING_UPDATE
                updated_member = self.plugin_instance.update_member(
                    self._ctxt, member['member']['id'], member)
                self.assertEqual(updated_member['status'],
                                 constants.PENDING_UPDATE)
                self.assertFalse(mock_dp._update_service_table_instance.called)

    def test_pool_health_monitor(self):
        mock_dp = self.mock_device_plugin
        ctxt = self._ctxt
        with contextlib.nested(
                self.subnet(), self.pool(provider=PROVIDER),
                self.health_monitor()) as (subnet, pool, hm):
            with self.vip(subnet=subnet, pool=pool) as vip:
                pool = pool['pool']
                pool_id = pool['id']
                vip = vip['vip']
                vip_id = vip['id']
                hm = hm['health_monitor']
                hm_id = hm['id']

                mock_dp.reset_mock()
                monitors = self.plugin_instance.create_pool_health_monitor(
                    ctxt, {'health_monitor': hm}, pool_id)
                expected_monitors = {'health_monitor': [hm_id]}
                self.assertEqual(monitors, expected_monitors)
                expected_kwargs = {
                    'pool_id': pool_id,
                    'health_monitor': self._expected_health_monitor(
                        hm_id, pool_id, constants.PENDING_CREATE)
                }
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'create_pool_health_monitor',
                     'kwargs': expected_kwargs},
                    mock.ANY, mock.ANY)

                mock_dp.reset_mock()
                self.plugin_instance.update_health_monitor(
                    ctxt, hm_id, {'health_monitor': {}})
                expected_kwargs = {
                    'pool_id': pool_id,
                    'old_health_monitor': self._expected_health_monitor(
                        hm_id, pool_id, constants.ACTIVE),
                    'health_monitor': self._expected_health_monitor(
                        hm_id, pool_id, constants.ACTIVE)
                }
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'update_pool_health_monitor',
                     'kwargs': expected_kwargs},
                    mock.ANY, mock.ANY)

                mock_dp.reset_mock()
                self.plugin_instance.delete_pool_health_monitor(
                    ctxt, hm_id, pool_id)
                expected_kwargs = {
                    'pool_id': pool_id,
                    'health_monitor': self._expected_health_monitor(
                        hm_id, pool_id, constants.PENDING_DELETE)
                }
                mock_dp._update_service_table_instance.assert_called_once_with(
                    ctxt, vip_id,
                    {'action': 'delete_pool_health_monitor',
                     'kwargs': expected_kwargs},
                    mock.ANY, mock.ANY)
