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

import abc
import six

from oslo.config import cfg
from oslo import messaging

from neutron.api.v2 import attributes
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.db import l3_db
from neutron.extension import l3
from neutron.openstack.common import log as logging
from neutron.services.l3_router import l3_router_plugin


LOG = logging.getLogger(__name__)


class L3VRouterDriverContext(object):
    def __init__(self, context, router=None, aux=None):
        super(L3VRouterDriverContext, self).__init__()
        self.context = context
        self.router = router
        self.aux = aux


@six.add_metaclass(abc.meta)
class L3VRouterDriverBase(object):
    def __init__(self, l3_plugin):
        super(L3VRouterDriverBase, self).__init__()
        self._l3_plugin = l3_plugin

    def initialize(self):
        pass

    def delete_port(self, context, port_id):
        self._l3_plugin._core_plugin_delete_port(context, port_id)

    def _delete_port(self, context, port_id):
        self._l3_plugin._core_plugin__delete_port(context, port_id)

    def create_router_pre(self, driver_context):
        pass

    def create_router_db(self, driver_context):
        pass

    def create_router_post(self, driver_context):
        pass

    def update_router_pre(self, driver_context):
        pass

    def update_router_db_pre(self, driver_context):
        pass

    def update_router_db_post(self, driver_context):
        pass

    def update_router_post(self, driver_context):
        pass

    def delete_router_db(self, driver_context):
        pass

    def delete_router_post(self, driver_context):
        pass

    def add_router_interface_db(self, driver_context):
        pass

    def add_router_interface_post(self, driver_context):
        pass

    def remove_router_interface_pre(self, driver_context):
        pass

    def remove_router_interface_db(self, driver_context):
        pass

    def remove_router_interface_post(self, driver_context):
        pass

    def create_floatingip_db(self, driver_context):
        pass

    def create_floatingip_post(self, driver_context):
        pass

    def update_floatingip_db(self, driver_context):
        pass

    def update_floatingip_post(self, driver_context):
        pass

    def delete_floatingip_db(self, driver_context):
        pass

    def delete_floatingip_post(self, driver_context):
        pass

    def disassociate_floatingips_db(self, driver_context):
        pass

    def disassociate_floatingips_post(self, driver_context):
        pass


class L3VRouterNotifierDriver(L3VRouterDriverBase):
    def __init__(self, l3_plugin, notifier_cls=None):
        super(L3VRouterNotifierDriver, self).__init__(l3_plugin)
        if notifier_cls is None:
            notifier_cls = l3_db.L3PluginRpcNotifierMixin
        self._l3_rpc_notifier = notifier_cls()

    def update_router_post(self, driver_context):
        r = driver_context.router['router']
        payload = {'gw_exists':
                   r.get(l3.EXTERNAL_GW_INFO, attributes.ATTR_NOT_SPECIFIED) !=
                   attributes.ATTR_NOT_SPECIFIED}
        self._l3_rpc_notifier.notify_router_updated(
            driver_context.context, driver_context.router['id'], None, payload)

    def delete_router_post(self, driver_context):
        self._l3_rpc_notifier.notify_router_deleted(
            driver_context.context, driver_context.router['id'])

    def add_router_interface_post(self, driver_context):
        router_interface_info = driver_context.aux
        self._l3_rpc_notifier.notify_router_updated(
            driver_context.context, driver_context.router['id'],
            'add_router_interface',
            {'subnet': router_interface_info['subnet_id']})

    def remove_router_interface_post(self, driver_context):
        self._l3_rpc_notifier.notify_router_updated(
            driver_context.context, driver_context.router['id'],
            'remove_router_interface',
            {'subnet_id': driver_context.aux['subnet_id']})

    def create_floatingip_post(self, driver_context):
        info = driver_context.aux
        router_id = info['router_id']
        self._l3_rpc_notifier.notify_router_updated(
            driver_context.context, router_id, 'create_floatingip', {})

    def update_floatingip_post(self, driver_context):
        aux = driver_context.aux
        router_ids = self._l3_plugin._floatingips_to_router_ids(
            [aux['old_floatingip'], aux['floatingip']])
        self._l3_rpc_notifier.notify_routers_updated(
            driver_context.context, router_ids, 'update_floatingip', {})

    def delete_floatingip_post(self, driver_context):
        router_id = driver_context.aux
        self._l3_rpc_notifier.notify_router_updated(
            driver_context.context, router_id, 'delete_floatingip', {})

    def disassociate_floatingips_post(self, driver_context):
        router_ids = driver_context.aux
        self._l3_rpc_notifier.notify_routers_updated(
            driver_context.context, list(router_ids),
            'disassociate_floatingips', {})


class L3VRouterRpcCallbackDriver(L3VRouterNotifierDriver):
    def __init__(self, l3_plugin, notifier_cls=None,
                 callback_cls=l3_router_plugin.L3RouterPluginRpcCallbacks):
        super(L3VRouterNotifierDriver, self).__init__(
            l3_plugin, notifier_cls=notifier_cls)
        self._endpoint = callback_cls(self)
        self._target = messaging.Target(
            topic=topics.L3_PLUGIN, server=cfg.CONF.host, fanout=False)
        self._server = None

    def initialize(self):
        self._server = n_rpc.get_server(self._target, [self._endpoint])
        self._server.start()


class L3VRouterDisownPortDriver(L3VRouterRpcCallbackDriver):
    _DEVICE_OWDER_DELETING = dict(
        (owner, owner + ":deleting") for owner in
        l3_db.L3_NAT_dbonly_mixin.router_device_owners)

    def _disown_port(self, context, port_id):
        # NOTE(yamahata):
        # neutron port will be deleted on behalf of nova interface-detach
        # which issues normal port-delete. So we need to allow port deletion.
        # Since Neutron ports that is owned by router is considered as
        # neutron internal use, the normal port deletion via REST API
        # is prohibited.
        core_plugin = self._l3_plugin._core_plugin
        port = core_plugin.get_port(context, port_id)
        port = {"port": {"device_owner":
                    self._DEVICE_OWNER_DELETING[port["device_owner"]]}}
        core_plugin.update_port(context, port_id, port)

    def delete_port(self, context, port_id):
        self._disown_port(context, port_id)

    def _delete_port(self, context, port_id):
        self._disown_port(context, port_id)
