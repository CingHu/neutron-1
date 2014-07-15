# Copyright 2014 Intel Corporation.
# Copyright 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
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
# @author: Isaku Yamahata, Intel Cooperation


from neutron.api.v2 import attributes
from neutron.db import models_v2
from neutron.common import constants
from neutron import manager
from neutron.plugin.common import constants as p_const
from neutron.services.l3_router.vrouter.common import tacker_lib
from neutron.services.l3_router.vrouter.plugging_drivers import (
    plugging_driver_base)


class GuestAgentPlugginDriver(plugging_driver_base.PluginSidePluggingDriver):
    @property
    def _core_plugin(self):
        return manager.NeutronManager.get_plugin()

    def create_hosting_device_resources(self, driver_context,
                                        complementary_id, **kwargs):
        mgmt_net = kwargs['mgmt_net']
        body = {
            'port': {
                'tenant_id': mgmt_net.l3_tanent_id,
                'admin_state_up': True,
                'name': 'mgmt-port-router-id-%s' % complementary_id,
                'network_id': mgmt_net.mgmt_nw_id,
                'mac_address': attributes.ATTR_NOT_SPECIFIED,
                'fixed_ips': attributes.ATTR_NOT_SPECIFIED,
                'device_id': complementary_id,
                'device_owner': constants.DEVICE_OWNER_MGMT_PORT,
            }
        }
        mgmt_port = self._core_plugin.create_port(driver_context.context, body)
        mgmt_port_id = mgmt_port['port']['id']

        return {'mgmt_port_id': mgmt_port_id,
                'complementary_id': complementary_id}

    def get_hosting_device_resources(self, driver_context,
                                     hosting_device_id, complementary_id):
        session = driver_context.context.session
        query = session.query(models_v2.Port)
        mgmt_port = (query.filter(models_v2.Port.device_id.in_(
            [hosting_device_id, complementary_id])).
            filter(models_v2.Port.device_owner ==
                   constants.DEVICE_OWNER_MGMT_PORT).one())

        query = session.query(models_v2.Port)
        ports = (query.filter(models_v2.Port.device_id.in_(
            [hosting_device_id, complementary_id])).
            filter(models_v2.Port.device_owner !=
                   constants.DEVICE_OWNER_MGMT_PORT).all())
        return {'mgmt_port': mgmt_port, 'ports': ports}

    def delete_hosting_device_resources(self, driver_context,
                                        hosting_device_id, **kwargs):
        if hosting_device_id is None:
            # error recovery case when failed to create vm
            mgmt_port_id = kwargs['mgmt_port_id']
            self._core_plugin.delete_port(driver_context.context, mgmt_port_id)
            return
        # ports attached to VM are auto deleted when VM destruction.

    def setup_logical_port_connectivity(self, driver_context,
                                        port_db, hosting_device_id):
        tclient = tacker_lib.get_client(driver_context.context)
        body = {'port_id': port_db['id']}
        tclient.attach_interface(hosting_device_id, body)

    def teardown_logical_port_connectivity(self, driver_context,
                                           port_db, hosting_device_id):
        tclient = tacker_lib.get_client(driver_context.context)
        body = {'port_id': port_db['id']}
        tclient.detach_interface(hosting_device_id, body)

    def extend_hosting_port_info(self, driver_context, port_db, hosting_info):
        """Extends hosting information for a logical port.

        Allows a driver to add driver specific information to the
        hosting information for a logical port.

        :param context: Neutron api request context.
        :param port_db: Neutron port that hosting information concerns.
        :param hosting_info: dict with hosting port information to be extended.
        """
        # nothing for now
        # TODO(yamahata):XXX
        pass

    def allocate_hosting_port(self, driver_context, resource_id,
                              port_db, hosting_device_id):
        # For now, logical port = hosting port. trunking is not supported yet.
        # l2-gateway extension is needed for more enhanced plugging.
        return {'allocated_port_id': port_db['id'],
                'network_type': p_const.TYPE_FLAT, 'segmentation_id': -1}
