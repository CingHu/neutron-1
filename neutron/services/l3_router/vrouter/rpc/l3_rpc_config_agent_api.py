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

from neutron.api.rpc import l3_rpc_agent_api
from neutron.openstack.common import log as logging
from neutron.plugin.common import constants
from neutron.services.l3_routers.vrouter.db import device_handling_db


LOG = logging.getLogger(__name__)


class L3ConfigAgentNotifyAPI(l3_rpc_agent_api.L3AgentNotifyAPI):

    def _agent_notification(self, context, method, router_ids,
                            operation, data):
        # should not be called
        raise RuntimeError()

    def _agent_notification_arp(self, context, method, router_id,
                                operation, data):
        raise NotImplementedError()

    def _notification(self, context, method, router_ids, operation, data):
        """Notify all the agents that are hosting the routers."""
        for router_id in router_ids:
            host = device_handling_db.get_agent_host(
                context.session, constants.L3_ROUTER_NAT, router_id)
            if host is None:
                continue
            LOG.debug(_('Notify agent at %(topic)s.%(host)s the message '
                        '%(method)s'),
                      {'topic': self.topic, 'host': host, 'method': method})
            self.cast(
                context, self.make_msg(method, routers=[router_id]),
                topic='%s.%s' % (self.topic, host))

    def _notification_fanout(self, context, method, router_id):
        """Fanout the deleted router to all L3 agents."""
        LOG.debug(_('Fanout notify agent at %(topic)s the message '
                    '%(method)s on router %(router_id)s'),
                  {'topic': self.topic,
                   'method': method,
                   'router_id': router_id})
        self.fanout_cast(
            context, self.make_msg(method, router_id=router_id))

    def router_deleted(self, context, router_id):
        self._notification(context, 'router_deleted', [router_id],
                           operation=None, data=None)

    def add_arp_entry(self, context, router_id, arp_table, operation=None):
        # should not be called
        raise NotImplementedError()

    def del_arp_entry(self, context, router_id, arp_table, operation=None):
        # should not be called
        raise NotImplementedError()
