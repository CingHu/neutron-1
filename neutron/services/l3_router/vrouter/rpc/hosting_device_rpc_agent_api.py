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

from neutron.common import rpc
from neutron.common import topic
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class HostingDeviceAgentNotifyAPI(rpc.RpcProxy):
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic=topic.CFG_AGENT):
        super(HostingDeviceAgentNotifyAPI, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)

    def _host_notification(self, context, method, payload, host):
        """Notify the cfg agent that is handling the hosting device."""
        LOG.debug('Notify Cisco cfg agent at %(host)s the message '
                  '%(method)s', {'host': host, 'method': method})
        self.cast(context,
                  self.make_msg(method, payload=payload),
                  topic='%s.%s' % (self.topic, host))

    def hosting_devices_removed(self, context, hosting_data, deconfigure,
                                host):
        """Notify cfg agent that some hosting devices have been removed.

        This notification informs the cfg agent in <host> that the
        hosting devices in the <hosting_data> dictionary have been removed
        from the hosting device pool. The <hosting_data> dictionary also
        contains the ids of the affected logical resources for each hosting
        devices:
             {'hd_id1': {'routers': [id1, id2, ...],
                         'fw': [id1, ...],
                         ...},
              'hd_id2': {'routers': [id3, id4, ...]},
                         'fw': [id1, ...],
                         ...},
              ...}
        The <deconfigure> argument is True if any configurations for the
        logical resources should be removed from the hosting devices
        """
        if hosting_data:
            self._host_notification(context, 'hosting_devices_removed',
                                    {'hosting_data': hosting_data,
                                     'deconfigure': deconfigure}, host)
