# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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
# @author: Bob Melander, Cisco Systems, Inc.
# @author: Isaku Yamahata, Intel Cooperation

from oslo.config import cfg

from neutron.common import exceptions as n_exc
from neutron import manager
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants
from neutron.services.l3_router import l3_router_plugin
from neutron.services.l3_router.vrouter.common import exceptions as l3_exc
from neutron.services.l3_router.vrouter.db import device_handling_db
from neutron.services.l3_router.vrouter.db import l3_vrouter_db
from neutron.services.l3_router.vrouter import l3_vrouter_driver
from neutron.services.l3_router.vrouter import mgmt_network
from neutron.services.l3_router.vrouter.rpc import l3_rpc_config_agent_api


LOG = logging.getLogger(__name__)


class L3GuestAgentCallbacks(l3_router_plugin.L3RouterPluginRpcCallbacks):
    def __init__(self, vrouter_driver):
        super(L3GuestAgentCallbacks, self).__init__()
        self._vrouter_driver = vrouter_driver

    def update_router_binding(self, context, router_ids,
                              old_status, new_status):
        self._vrouter_driver._update_biding_router(
            context, router_ids, old_status, new_status)

    # def bind_device(self, context, agent_type, host, hosting_device_id):
    #     """Bind the router to the caller agent."""
    #     if agent_type != n_const.AGENT_TYPE_L3:
    #         return
    #     l3_plugin = self._vrouter_driver._l3_plugin
    #     with context.session.begin(subtransactions=True):
    #         binding_db = (l3_plugin._model_query(
    #             context, device_handling_db.HostingDeviceAgentBinding).
    #             filter(device_handling_db.HostingDeviceAgentBinding.
    #                    hosting_device_id == hosting_device_id).one())
    #         agent_db = l3_plugin._model_query(agents_db.Agent).filter(
    #             agents_db.agent_type == agent_type,
    #             agents_db.host == host).one()
    #         #binding_db.agent_id = agent_db.id
    #         binding_db.agent = agent_db
    #         LOG.debug(
    #             'cfg agent of HostingDevice %(hosting_device_id)s is bind '
    #             'to %(agent_id)s on %(host)s',
    #             {'hosting_device_id': hosting_device_id,
    #              'agetn_id': agent_db.id, 'host': host})


# TODO(yamahata): use context.auth_token
# TODO(yamahata): backlog so this new router gets scheduled asynchronously
#                 For now, they are synchronously processed for simplicity
class L3VRouterGuestAgentDriver(
        l3_vrouter_driver.L3VRouterDisownPortDriver):

    # callback from hosting_device
    def handle_non_responding_hosting_devices_post(
            self, context, binding, hosting_info):
        # TODO(yamahata)
        pass

    def __init__(self, l3_plugin):
        super(L3VRouterGuestAgentDriver, self).__init__(
            l3_plugin,
            notifider_cls=l3_rpc_config_agent_api.L3ConfigAgentNotifyAPI,
            callback_cls=L3GuestAgentCallbacks)

        conf = cfg.CONF.management_network
        self._mgmt_net = mgmt_network.ManagementNetwork(
            conf.l3_admin_tenant, conf.management_network,
            conf.management_security_group)

        self._device_handling = device_handling_db.DeviceHandling()
        self._device_handling.register_service(self)

    @property
    def _core_plugin(self):
        return manager.NeutronManager.get_plugin()

    def create_router_pre(self, driver_context):
        if self._mgmt_net.mgmt_nw_id is None:
            raise l3_exc.RouterCreateInternalError()

    def create_router_db(self, driver_context):
        context = driver_context.context
        router_created = driver_context.router
        rhdb_db = self._device_handling.create_resource_binding(
            context, constants.L3_ROUTER_NAT, router_created['id'])
        driver_context.aux = rhdb_db

    def create_router_post(self, driver_context):
        context = driver_context.context
        router = driver_context.router
        router_id = router['id']
        device_id = self._device_handling.schedule_service_on_hosing_device(
            driver_context, constants.L3_ROUTER_NAT, router_id)
        self._device_handling.update_resource_binding(
            context, router_id, constants.PENDING_CREATE, constants.ACTIVE,
            device_id)

        # TODO(yamahata):
        # wait for agent report
        # then, bind router

    def update_router_pre(self, driver_context):
        router_id = driver_context.aux
        r = driver_context.router['router']
        # Check if external gateway has changed so we may have to
        # update trunking
        o_r_db = self._l3_plugin._get_router(driver_context.context, router_id)
        old_ext_gw_port = o_r_db.gw_port
        old_ext_gw = (o_r_db.gw_port or {}).get('network_id')
        new_ext_gw = (r.get('external_gateway_info', {}) or {}).get(
            'network_id')
        driver_context.aux = {
            'o_r_db': o_r_db,
            'old_ext_gw_port': old_ext_gw_port,
            'old_ext_gw': old_ext_gw,
            'new_ext_gw': new_ext_gw,
        }
        # TODO(yamahata): check if the hosting device can be connected
        # the external network.
        # check if The host which the vm resides on has the access to
        # the given external network.

    def update_router_db_pre(self, driver_context):
        context = driver_context.context
        router_id = driver_context.router['router']['id']
        e_context = context.elevated()
        driver_context.aux['e_context'] = e_context

        self._device_handling.update_resource_binding(
            context, router_id, constants.ACTIVE, constants.PENDING_UPDATE)

    def update_router_post(self, driver_context):
        context = driver_context.context
        router = driver_context.router['router']
        router_id = router['id']
        hosting_info = router['hosting_info']
        device_id = hosting_info['hosting_device_id']

        aux = driver_context.aux
        old_ext_gw = aux['old_ext_gw']
        new_ext_gw = aux['new_ext_gw']
        if old_ext_gw is not None and old_ext_gw != new_ext_gw:
            old_gw_port_id = aux['old_ext_gw_port']
            new_gw_port_id = router['gw_port_id']

            old_gw_port_db = self._core_plugin._get_port(context,
                                                         old_gw_port_id)
            self._device_handling.teardown_logical_port_connectivity(
                driver_context, old_gw_port_db, device_id)

            new_gw_port_db = self._core_plugin._get_port(
                context, new_gw_port_id)
            self._device_handling.teardown_logical_port_connectivity(
                driver_context, new_gw_port_db, device_id)

        super(L3VRouterGuestAgentDriver, self).update_router_post(
            driver_context)
        self._device_handling.update_resource_binding(
            context, router_id, constants.PENDING_UPDATE, constants.ACTIVE)

    def delete_router_db(self, driver_context):
        context = driver_context.context
        router_id = driver_context.router['id']

        self._device_handling.update_resource_binding(
            context, router_id, constants.ACTIVE, constants.PENDING_DELETE)

    def delete_router_post(self, driver_context):
        context = driver_context.context
        super(L3VRouterGuestAgentDriver, self).delete_router_post(
            driver_context)

        router_id = driver_context.router['id']
        self._device_handling.unschedule_from_hosting_device(
            driver_context, router_id)
        self._device_handling.delete_resource_binding(context, router_id)

    def _get_interface_info(self, driver_context):
        context = driver_context.context
        router = driver_context.router
        router_id = router['id']
        hosting_info = router['hosting_info']
        device_id = hosting_info['hosting_device_id']
        router_interface_info = driver_context.aux
        port_id = router_interface_info['port_id']
        port_db = self._core_plugin._get_port(context, port_id)
        return router_id, port_db, device_id

    def add_router_interface_db(self, driver_context):
        context = driver_context.context
        router = driver_context.router
        router_id = router['id']
        self._device_handling.update_resource_binding(
            context, router_id, constants.ACTIVE, constants.PENDING_UPDATE)

    def add_router_interface_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).add_router_interface_post(
            driver_context)

        router_id, port_db, device_id = self._get_interface_info(
            self, driver_context)
        self._device_handling.setup_logical_port_connectivity(
            driver_context, port_db, device_id)
        self._device_handling.update_resource_binding(
            driver_context.context, router_id,
            constants.PENDING_UPDATE, constants.ACTIVE)

    def remove_router_interface_pre(self, driver_context):
        context = driver_context.context
        aux = driver_context.aux
        router_id = aux['router_id']
        interface_info = aux['interface_info']

        if 'port_id' in (interface_info or {}):
            port_db = self._core_plugin._get_port(
                context, interface_info['port_id'])
        elif 'subnet_id' in (interface_info or {}):
            subnet_db = self._core_plugin._get_subnet(
                context, interface_info['subnet_id'])
            port_db = self._l3_plugin._get_router_port_db_on_subnet(
                context, router_id, subnet_db)
        else:
            msg = "Either subnet_id or port_id must be specified"
            raise n_exc.BadRequest(resource='router', msg=msg)
        driver_context.router = self._l3_router.get_router(context, router_id)
        driver_context.aux['port_db'] = port_db

    def remove_router_interface_db(self, driver_context):
        context = driver_context.context
        router_id = driver_context.router['id']
        self._device_handling.update_resource_binding(
            context, router_id, constants.ACTIVE, constants.PENDING_UPDATE)

    def remove_router_interface_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).remove_router_interface_post(
            driver_context)

        router_id, port_db, device_id = self._get_interface_info(
            self, driver_context)
        self._device_handling.teardown_logical_port_connectivity(
            driver_context, port_db, device_id)
        self._device_handling.update_resource_binding(
            driver_context.context, router_id,
            constants.PENDING_UPDATE, constants.ACTIVE)

    def create_floatingip_db(self, driver_context):
        context = driver_context.context
        info = driver_context.aux
        router_id = info['router_id']
        if router_id:
            router = self._l3_router.get_router(context, router_id)
            self._add_type_and_hosting_device_info(context.elevated(), router)
            self._device_handling.update_resource_binding(
                context, router_id, constants.ACTIVE, constants.PENDING_UPDATE)

    def create_floatingip_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).create_floatingip_post(
            driver_context)
        # TODO(yamahata): notify floating ip creation
        context = driver_context.context
        router_id = driver_context.router['id']
        if router_id:
            self._device_handling.update_resource_binding(
                context, router_id, constants.PENDING_UPDATE, constants.ACTIVE)

    def _update_router_binding(self, context, router_ids,
                               old_status, new_status):
        for router_id in router_ids:
            self._device_handling.update_resource_binding(
                context, router_id, old_status, new_status)

    def _update_floatingip_router(self, driver_context,
                                  old_status, new_status):
        context = driver_context.context
        aux = driver_context.aux
        router_ids = l3_vrouter_db.floatingips_to_router_ids_ordered(
            [aux['old_floatingip'], aux['floatingip']])
        self._update_router_binding(
            context, router_ids, old_status, new_status)

    def update_floatingip_db(self, driver_context):
        self._update_floatingip_router(
            driver_context, constants.ACTIVE, constants.PENDING_UPDATE)

    def update_floatingip_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).update_floatingip_post(
            driver_context)
        self._update_floatingip_router(
            driver_context, constants.PENDING_UPDATE, constants.ACTIVE)

    def delete_floatingip_db(self, driver_context):
        self._update_floatingip_router(
            driver_context, constants.ACTIVE, constants.PENDING_UPDATE)

    def delete_floatingip_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).delete_floatingip_post(
            driver_context)
        # TODO(yamahata): notify floating ip deleation
        self._update_floatingip_router(
            driver_context, constants.PENDING_UPDATE, constants.ACTIVE)

    def disassociate_floatingips_db(self, driver_context):
        context = driver_context.context
        router_ids = driver_context.aux
        self._update_router_binding(
            context, router_ids, constants.ACTIVE, constants.PENDING_UPDATE)

    def disassociate_floatingips_post(self, driver_context):
        super(L3VRouterGuestAgentDriver, self).disassociate_floatingips_post(
            driver_context)
        # TODO(yamahata): notify disassociation
        context = driver_context.context
        router_ids = driver_context.aux
        self._update_router_binding(
            context, router_ids, constants.PENDING_UPDATE, constants.ACTIVE)
