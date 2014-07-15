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

from neutron.common import exceptions as n_exc
from neutron.openstack.common import log as logging
from neutron.plugins.cisco.db.l3 import l3_models
from neutron.services.l3_router.router_appliance.db import (
    l3_router_appliance_db)


LOG = logging.getLogger(__name__)


# TODO
class VyattaVrouterDriver(
        l3_router_appliance_db.L3RouterAplianceDriverBase):

    def create_router_pre(self, driver_context):
        if self._l3_plugin.mgmt_nw_id() is None:
            raise RouterCreateInternalError()

    def create_router_db(self, driver_context):
        router_created = driver_context.router
        context = driver_context.context
        r_hd_b_db = l3_models.RouterHostingDeviceBinding(
            router_id=router_created['id'],
            auto_schedule=True,
            hosting_device_id=None)
        context.session.add(r_hd_b_db)
        driver_context.aux = r_hd_b_db

    def create_router_post(self, driver_context):
        # backlog so this new router gets scheduled asynchronously
        r_hd_b_db = driver_context.aux
        self._l3_plugin.backlog_router(r_hd_b_db['router'])

    def update_router_pre(self, driver_context):
        router_id = driver_context.aux
        r = driver_context.router['router']
        # Check if external gateway has changed so we may have to
        # update trunking
        o_r_db = self._l3_plugin._get_router(driver_context.context, router_id)
        old_ext_gw = (o_r_db.gw_port or {}).get('network_id')
        new_ext_gw = (r.get('external_gateway_info', {}) or {}).get(
            'network_id')
        driver_context.aux = {
            'o_r_db': o_r_db,
            'old_ext_gw': old_ext_gw,
            'new_ext_gw': new_ext_gw,
        }

    def update_router_db_pre(self, driver_context):
        context = driver_context.context
        l3_plugin = self._l3_plugin
        o_r_db = driver_context.aux['o_r_db']
        old_ext_gw = driver_context.aux['old_ext_gw']
        new_ext_gw = driver_context.aux['old_ext_gw']
        e_context = context.elevated()
        driver_context.aux['e_context'] = e_context

        if old_ext_gw is not None and old_ext_gw != new_ext_gw:
            o_r = l3_plugin._make_router_dict(o_r_db, process_extensions=False)
            # no need to schedule now since we're only doing this to
            # tear-down connectivity and there won't be any if not
            # already scheduled.
            self._add_type_and_hosting_device_info(e_context, o_r,
                                                   schedule=False)
            p_drv = self.get_hosting_device_plugging_driver()
            if p_drv is not None:
                p_drv.teardown_logical_port_connectivity(e_context,
                                                         o_r_db.gw_port)

    def update_router_db_post(self, driver_context):
        self._add_type_and_hosting_device_info(driver_context.aux['e_context'],
                                               driver_context.router)

    def delete_router_db(self, driver_context):
        context = driver_context.context
        router = driver_context.router
        router_db = driver_context.aux

        e_context = context.elevated()
        r_hd_binding = self._get_router_binding_info(e_context, id)
        self._add_type_and_hosting_device_info(
            e_context, router, binding_info=r_hd_binding, schedule=False)
        if router_db.gw_port is not None:
            p_drv = self.get_hosting_device_plugging_driver()
            if p_drv is not None:
                p_drv.teardown_logical_port_connectivity(e_context,
                                                         router_db.gw_port)
        # conditionally remove router from backlog just to be sure
        self.remove_router_from_backlog('id')
        if router['hosting_device'] is not None:
            self.unschedule_router_from_hosting_device(context, r_hd_binding)

    def add_router_interface_db(self, driver_context):
        self._add_type_and_hosting_device_info(
            driver_context.context.elevated(), driver_context.router)

    def remove_router_interface_pre(self, driver_context):
        context = driver_context.context
        router_id, interface_info = driver_context.aux

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
        driver_context.aux = port_db

    def remove_router_interface_db(self, driver_context):
        e_context = driver_context.context.elevated()
        port_db = driver_context.aux
        self._add_type_and_hosting_device_info(
            e_context, driver_context.router)
        p_drv = self.get_hosting_device_plugging_driver()
        if p_drv is not None:
            p_drv.teardown_logical_port_connectivity(e_context, port_db)

    def create_floatingip_db(self, driver_context):
        context = driver_context.context
        info = driver_context.aux
        router_id = info['router_id']
        if router_id:
            router = self._l3_router.get_router(context, router_id)
            self._add_type_and_hosting_device_info(context.elevated(), router)

    def update_floatingip_db(self, driver_context):
        context = driver_context.context
        aux = driver_context.aux
        router_ids = l3_router_appliance_db.floatingips_to_router_ids_ordered(
            [aux['old_floatingip'], aux['floatingip']])
        for router_id in router_ids:
            router = self._l3_plugin.get_router(context, router_id)
            self._add_type_and_hosting_device_info(context.elevated(), router)

    def delete_floatingip_db(self, driver_context):
        context = driver_context.context
        router_id = driver_context.aux
        if router_id:
            routers = [self._l3_plugin.get_router(context, router_id)]
            self._add_type_and_hosting_device_info(context.elevated(),
                                                   routers[0])

    def disassociate_floatingips_db(self, driver_context):
        context = driver_context.context
        router_ids = driver_context.aux
        for router_id in router_ids:
            router = self._l3_plugin.get_router(context, router_id)
            self._add_type_and_hosting_device_info(context.elevated(), router)
