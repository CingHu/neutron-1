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

from neutron.common import constants as l3_constants
from neutron.db import extraroute_db
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging
from neutron.services.l3_routers.vrouter import l3_vrouter_driver

LOG = logging.getLogger(__name__)


# TODO(yamahata): multiple driver support

ROUTER_APPLIANCE_OPTS = [
    cfg.IntOpt('backlog_processing_interval',
               default=10,
               help=_('Time in seconds between renewed scheduling attempts of '
                      'non-scheduled routers.')),
]

cfg.CONF.register_opts(ROUTER_APPLIANCE_OPTS, 'l3_vrouter')


def floatingips_to_router_ids_ordered(floatingips):
        router_ids = [fip['router_id'] for fip
                      in floatingips if fip['router_id']]
        seen = set()
        return [rid for rid in router_ids
                if not (rid in seen or (lambda x: seen.add(x))(rid))]


class L3VRouterDbMixin(extraroute_db.ExtraRouteDbMixin):
    """Mixin class implementing Neutron's routing service using appliances."""
    def __init__(self):
        super(L3VRouterDbMixin, self).__init__()

        # TODO(yamahata): allow multiple drivers
        self._driver = importutils.import_object(cfg.CONF.router_driver, self)

    def initialize(self):
        self._driver.initialize()

    def _core_plugin_delete_port(self, context, port_id):
        self._driver.delete_port(context, port_id)

    def _core_plugin__delete_port(self, context, port_id):
        self._driver._delete_port(context, port_id)

    def create_router(self, context, router):
        driver = self._driver
        driver_context = l3_vrouter_driver.L3PluginDriverContext(
            context, router)
        driver.create_router_pre(driver_context)
        with context.session.begin(subtransactions=True):
            router_created = super(
                L3VRouterDbMixin, self).create_router(context, router)
            driver_context.router = router_created
            driver.router_create_db(driver_context)
        driver.router_create_post(driver_context)
        return router_created

    # XXX: neutron port create/delete
    # XXX: port plugging
    def update_router(self, context, id, router):
        driver = self._driver
        driver_context = l3_vrouter_driver.L3PluginDriverContext(
            context, router, id)

        driver.update_router_pre(driver_context)
        with context.session.begin(subtransactions=True):
            driver.update_router_db_pre(driver_context)
            router_updated = super(
                L3VRouterDbMixin, self).update_router(context, id, router)
            driver_context.router = router_updated
            driver.update_router_db_post(driver_context)
        driver.update_router_post(driver_context)
        return router_updated

    def delete_router(self, context, id):
        driver = self._driver
        router_db = self._get_router(context, id)
        router = self._make_router_dict(router_db)
        driver_context = l3_vrouter_driver.L3PluginDriverContext(
            context, router, router_db)

        with context.session.begin(subtransactions=True):
            driver.delete_router_db(driver_context)
            super(L3VRouterDbMixin, self).delete_router(context, id)
        driver.delete_router_post(driver_context)

    def add_router_interface(self, context, router_id, interface_info):
        driver = self._driver

        with context.session.begin(subtransactions=True):
            router = self.get_router(context, router_id)
            info = (super(L3VRouterDbMixin, self).
                    add_router_interface(context, router_id, interface_info))
            driver_context = l3_vrouter_driver.L3PluginDriverContext(
                context, router, info)
            driver.add_router_interface_db(driver_context)
        driver.add_router_interface_post(driver_context)
        return info

    def remove_router_interface(self, context, router_id, interface_info):
        driver = self._driver
        driver_context = l3_vrouter_driver.L3PluginDriverContext(
            context, None,
            {'router_id': router_id, 'interface_info': interface_info})

        driver.remove_router_interface_pre(driver_context)
        with context.session.begin(subtransactions=True):
            driver.remove_router_interface_db(driver_context)
            info = (super(L3VRouterDbMixin, self).
                    remove_router_interface(context, router_id,
                                            interface_info))
            driver_context.aux.update(info)
        driver.remove_router_interface_post(driver_context)
        return info

    def create_floatingip(
            self, context, floatingip,
            initial_status=l3_constants.FLOATINGIP_STATUS_ACTIVE):
        driver = self._driver

        with context.session.begin(subtransactions=True):
            info = super(L3VRouterDbMixin, self).create_floatingip(
                context, floatingip)
            driver_context = l3_vrouter_driver.L3PluginDriverContext(
                context, None, info)
            driver.create_floatingip_db(driver_context)
        driver.create_floatingip_post(driver_context)
        return info

    def update_floatingip(self, context, id, floatingip):
        driver = self._driver

        with context.session.begin(subtransactions=True):
            old_floatingip, floatingip = self._update_floatingip(
                context, id, floatingip)
            aux = {'old_floatingip': old_floatingip, 'floatingip': floatingip}
            driver_context = l3_vrouter_driver.L3PluginDriverContext(
                context, None, aux)
            driver.update_floatingip_db(driver_context)

        driver.update_floatingip_post(driver_context)
        return floatingip

    def delete_floatingip(self, context, id):
        driver = self._driver

        with context.session.begin(subtransactions=True):
            router_id = self._delete_floatingip(context, id)
            driver_context = l3_vrouter_driver.L3PluginDriverContext(
                context, None, router_id)
            driver.delete_floatingip_db(driver_context)
        driver.delete_floatingip_post(driver_context)

    def disassociate_floatingips(self, context, port_id):
        driver = self._driver

        with context.session.begin(subtransactions=True):
            router_ids = super(
                L3VRouterDbMixin, self).disassociate_floatingips(
                    context, port_id)
            driver_context = l3_vrouter_driver.L3PluginDriverContext(
                context, None, router_ids)
            driver.disassociate_floatingips_db(driver_context)
        driver.disassociate_floatingips_post(driver_context)
